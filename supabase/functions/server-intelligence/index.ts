// Server-side cache API.  Clients can read a schedule and opt in to a
// short-lived availability report; provider credentials never leave Supabase.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const headers = { 
  "content-type": "application/json", 
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, GET, OPTIONS",
  "access-control-allow-headers": "apikey, Authorization, Content-Type"
};
const endpointPattern = /^[A-Za-z0-9.-]{1,253}:([0-9]{1,5})$/;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers });
}

function endpoint(value: unknown): string | null {
  if (typeof value !== "string" || !endpointPattern.test(value)) return null;
  const port = Number(value.slice(value.lastIndexOf(":") + 1));
  return port >= 1 && port <= 65535 ? value : null;
}

function serverSecretKey(): string | null {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}");
    if (typeof keys.default === "string" && keys.default) return keys.default;
  } catch {
    // Older projects expose the legacy variable below.
  }
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
}

async function hash(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (request) => {
  const url = new URL(request.url);
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = serverSecretKey();
  // This key is supplied only inside Supabase Edge Functions.  Reusing it as
  // the HMAC-like salt avoids asking the project owner to create, copy, or
  // expose another secret.
  const rateSalt = serviceRoleKey;
  if (!supabaseUrl || !serviceRoleKey) return json({ error: "service unavailable" }, 503);
  const db = createClient(supabaseUrl, serviceRoleKey);

  if (request.method === "OPTIONS") {
    return new Response("ok", { headers });
  }

  if (request.method === "GET" && url.pathname.endsWith("/server-intelligence/schedule")) {
    const server = endpoint(url.searchParams.get("endpoint"));
    if (!server) return json({ error: "invalid endpoint" }, 400);
    const { data, error } = await db
      .from("server_schedule_cache")
      .select("wipe_at,source,confidence")
      .eq("endpoint", server)
      .maybeSingle();
    if (error) return json({ error: "service unavailable" }, 503);
    const wipeAt = data?.wipe_at ? Math.floor(new Date(data.wipe_at).getTime() / 1000) : null;
    return json({ wipe_at: wipeAt, source: data?.source ?? "", confidence: data?.confidence ?? "unknown" });
  }

  if (request.method === "POST" && url.pathname.endsWith("/server-intelligence/availability")) {
    const body = await request.json().catch(() => null);
    const server = endpoint(body?.endpoint);
    if (!server) return json({ error: "invalid endpoint" }, 400);

    // The source address is supplied by Supabase's trusted edge proxy.  Only
    // a salted, one-day hash is retained to rate-limit abuse; no client ID,
    // Steam ID, log data, or raw address is stored.
    const forwardedFor = request.headers.get("x-forwarded-for")?.split(",");
    const sourceAddress = request.headers.get("cf-connecting-ip") ?? (forwardedFor ? forwardedFor[forwardedFor.length - 1].trim() : "unknown");
    
    const sourceHash = await hash(`${rateSalt}:${new Date().toISOString().slice(0, 10)}:${sourceAddress}`);
    const windowStartedAt = new Date(Math.floor(Date.now() / 60_000) * 60_000).toISOString();
    if (Math.random() < 0.05) {
      await db.from("server_intelligence_rate_limits").delete().lt(
        "window_started_at", new Date(Date.now() - 2 * 86_400_000).toISOString(),
      );
    }
    
    const { data: requestCount, error: rateWriteError } = await db.rpc("increment_server_intelligence_rate_limit", {
        p_source_hash: sourceHash,
        p_window_started_at: windowStartedAt
    });

    if (rateWriteError) return json({ error: "service unavailable" }, 503);
    if ((requestCount ?? 0) > 6) return json({ error: "rate limited" }, 429);

    const wipe_at_req = body?.wipe_at;
    const source_req = body?.source;
    
    let wipeAtDate = undefined;
    if (typeof wipe_at_req === "number" && wipe_at_req > 0) {
        wipeAtDate = new Date(wipe_at_req * 1000).toISOString();
    }

    const payload: any = {
      endpoint: server,
      last_available_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    
    if (wipeAtDate) {
        const { data: existing } = await db.from("server_schedule_cache").select("confidence").eq("endpoint", server).maybeSingle();
        if (existing && existing.confidence === "high") {
            wipeAtDate = undefined;
        } else {
            payload.wipe_at = wipeAtDate;
            payload.source = typeof source_req === "string" ? source_req.slice(0, 64) : "client-reported";
            payload.confidence = "low";
        }
    }

    const { error } = await db.from("server_schedule_cache").upsert(payload, { onConflict: "endpoint" });
    return error ? json({ error: "service unavailable" }, 503) : json({ accepted: true }, 202);
  }

  return json({ error: "not found" }, 404);
});
