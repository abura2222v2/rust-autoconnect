// Shared GameMonitoring cache. The provider is contacted only here, never by
// desktop clients. A2S remains the local source of truth for launching Rust.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const headers = {
  "content-type": "application/json", "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, OPTIONS",
  "access-control-allow-headers": "apikey, Authorization, Content-Type",
};
const endpointPattern = /^[A-Za-z0-9.-]{1,253}:([0-9]{1,5})$/;
const providerBase = "https://api.gamemonitoring.net";

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
  } catch { /* legacy variable below */ }
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
}
function providerId(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  for (const key of ["server_id", "id"]) {
    const candidate = record[key];
    if (typeof candidate === "number" && Number.isSafeInteger(candidate) && candidate > 0) return candidate;
    if (typeof candidate === "string" && /^\d+$/.test(candidate)) return Number(candidate);
  }
  for (const key of ["response", "data", "server"]) {
    const nested = providerId(record[key]);
    if (nested) return nested;
  }
  return null;
}
function providerRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object") return {};
  const record = value as Record<string, unknown>;
  return record.response && typeof record.response === "object"
    ? record.response as Record<string, unknown> : record;
}
function asInteger(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) return value;
  if (typeof value === "string" && /^\d+$/.test(value)) return Number(value);
  return null;
}
function asBoolean(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  if (value === 1 || value === "1" || value === "online") return true;
  if (value === 0 || value === "0" || value === "offline") return false;
  return null;
}
async function sourceHash(request: Request): Promise<string> {
  const forwarded = request.headers.get("cf-connecting-ip")
    ?? request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  const bytes = new TextEncoder().encode(`server-intelligence:${forwarded}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}
function asDate(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const numeric = typeof value === "number"
    ? value : (/^\d+$/.test(value) ? Number(value) : Number.NaN);
  // GameMonitoring exposes Unix seconds. JavaScript's Date constructor
  // expects milliseconds, while an ISO timestamp must remain untouched.
  const date = Number.isFinite(numeric)
    ? new Date(numeric < 100_000_000_000 ? numeric * 1000 : numeric)
    : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
function snapshot(row: Record<string, unknown>): Record<string, unknown> {
  const checkedAt = typeof row.provider_checked_at === "string" ? row.provider_checked_at : null;
  const fresh = checkedAt !== null && Date.now() - new Date(checkedAt).getTime() <= 125_000;
  return {
    wipe_at: row.wipe_at ? Math.floor(new Date(String(row.wipe_at)).getTime() / 1000) : null,
    source: row.source ?? "", confidence: row.confidence ?? "unknown",
    online: typeof row.provider_online === "boolean" ? row.provider_online : null,
    players: asInteger(row.provider_players), max_players: asInteger(row.provider_max_players),
    checked_at: checkedAt, fresh,
  };
}
async function provider(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${providerBase}${path}`, {
    ...init, headers: { "accept": "application/json", "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) throw new Error(`provider_${response.status}`);
  return await response.json();
}
async function refresh(db: ReturnType<typeof createClient>, claim: Record<string, unknown>): Promise<void> {
  const address = String(claim.endpoint);
  let serverId = providerId(claim.gamemonitoring_server_id);
  try {
    if (!serverId) {
      const registered = await provider("/servers", {
        method: "POST", body: JSON.stringify({ connect: address, steam_app_id: 252490 }),
      });
      serverId = providerId(registered);
      if (!serverId) {
        await db.from("server_intelligence_catalog").update({
          registration_retry_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
          refresh_lease_until: null, last_provider_error: "registration_id_missing", updated_at: new Date().toISOString(),
        }).eq("endpoint", address);
        return;
      }
    }
    const payload = providerRecord(await provider(`/servers/${serverId}`));
    const checkedAt = new Date().toISOString();
    await db.from("server_intelligence_catalog").update({
      gamemonitoring_server_id: serverId,
      provider_online: asBoolean(payload.status ?? payload.online),
      provider_players: asInteger(payload.numplayers), provider_max_players: asInteger(payload.maxplayers),
      wipe_at: asDate(payload.next_wipe), source: "gamemonitoring", confidence: payload.next_wipe ? "medium" : "unknown",
      provider_checked_at: checkedAt, refresh_lease_until: null, registration_retry_at: "-infinity",
      last_provider_error: "", updated_at: checkedAt,
    }).eq("endpoint", address);
  } catch (error) {
    await db.from("server_intelligence_catalog").update({
      refresh_lease_until: null, last_provider_error: error instanceof Error ? error.message.slice(0, 120) : "provider_error",
      updated_at: new Date().toISOString(),
    }).eq("endpoint", address);
  }
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers });
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = serverSecretKey();
  if (!supabaseUrl || !serviceRoleKey) return json({ error: "service unavailable" }, 503);
  if (!request.headers.get("authorization") || !request.headers.get("apikey")) {
    return json({ error: "unauthorized" }, 401);
  }
  const db = createClient(supabaseUrl, serviceRoleKey);
  const url = new URL(request.url);
  if (request.method !== "POST") return json({ error: "not found" }, 404);
  const body = await request.json().catch(() => null);

  // The Supabase gateway validates the publishable JWT. This independent,
  // privacy-preserving per-minute guard keeps the provider registration path
  // bounded even if a public app key is abused.
  const minute = new Date(Math.floor(Date.now() / 60_000) * 60_000).toISOString();
  const { data: count, error: rateError } = await db.rpc("increment_server_intelligence_rate_limit", {
    p_source_hash: await sourceHash(request), p_window_started_at: minute,
  });
  if (rateError) return json({ error: "service unavailable" }, 503);
  if (Number(count) > 20) return json({ error: "rate limited" }, 429);

  if (url.pathname.endsWith("/server-intelligence/observe")) {
    const server = endpoint(body?.endpoint);
    if (!server) return json({ error: "invalid endpoint" }, 400);
    const { data, error } = await db.rpc("claim_server_intelligence_refresh", {
      p_endpoint: server, p_active: Boolean(body?.active), p_share: false,
    });
    if (error || !Array.isArray(data) || !data[0]) return json({ error: "service unavailable" }, 503);
    const claim = data[0] as Record<string, unknown>;
    if (claim.refresh_needed) EdgeRuntime.waitUntil(refresh(db, claim));
    return json(snapshot(claim));
  }

  if (url.pathname.endsWith("/server-intelligence/share")) {
    const endpoints = Array.isArray(body?.endpoints) ? body.endpoints.map(endpoint).filter(Boolean).slice(0, 20) : [];
    if (!endpoints.length) return json({ error: "invalid endpoints" }, 400);
    const claims: Record<string, unknown>[] = [];
    for (const server of endpoints) {
      const { data, error } = await db.rpc("claim_server_intelligence_refresh", {
        p_endpoint: server, p_active: false, p_share: true,
      });
      if (!error && Array.isArray(data) && data[0]) claims.push(data[0]);
    }
    EdgeRuntime.waitUntil(Promise.all(claims.filter((claim) => claim.refresh_needed).map((claim) => refresh(db, claim))));
    return json({ accepted: true, endpoints: claims.length }, 202);
  }

  if (url.pathname.endsWith("/server-intelligence/availability")) {
    const server = endpoint(body?.endpoint);
    if (!server) return json({ error: "invalid endpoint" }, 400);
    await db.from("server_schedule_cache").upsert({ endpoint: server, last_available_at: new Date().toISOString(), updated_at: new Date().toISOString() }, { onConflict: "endpoint" });
    return json({ accepted: true }, 202);
  }
  return json({ error: "not found" }, 404);
});
