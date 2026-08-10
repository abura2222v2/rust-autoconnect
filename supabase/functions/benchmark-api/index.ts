// Deploy this Edge Function only after reviewing the paired migration and secrets.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = { 
  "content-type": "application/json", 
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, GET, OPTIONS",
  "access-control-allow-headers": "apikey, Authorization, Content-Type"
};
const maxPhaseSeconds = 600;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: corsHeaders });
}

function stringValue(value: unknown, maxLength = 160): string | null {
  return typeof value === "string" && value.trim().length > 0 && value.trim().length <= maxLength
    ? value.trim().replace(/\s+/g, " ")
    : null;
}

function timing(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 2 && value <= maxPhaseSeconds
    ? value
    : null;
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

async function deriveConfigurationKey(cpu: string, storage: string, benchmarkVersion: string): Promise<string> {
  const normalized = JSON.stringify({
    benchmark_version: benchmarkVersion.trim().replace(/\s+/g, " ").toLowerCase(),
    cpu: cpu.trim().replace(/\s+/g, " ").toLowerCase(),
    storage: storage.trim().replace(/\s+/g, " ").toLowerCase(),
  });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalized));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (request) => {
  const url = new URL(request.url);
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = serverSecretKey();
  const installSalt = Deno.env.get("BENCHMARK_INSTALLATION_SALT");
  if (!supabaseUrl || !serviceRoleKey || !installSalt) return json({ error: "service unavailable" }, 503);
  const db = createClient(supabaseUrl, serviceRoleKey);

  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (request.method === "POST" && url.pathname.endsWith("/benchmark/submit")) {
    const body = await request.json().catch(() => null);
    const id = stringValue(body?.id, 64);
    const installationId = stringValue(body?.installation_id, 64);
    const submittedConfigurationKey = stringValue(body?.configuration_key, 64);
    const cpu = stringValue(body?.cpu);
    const storage = stringValue(body?.storage);
    const storageBus = stringValue(body?.storage_bus) ?? "Unknown";
    const benchmarkVersion = stringValue(body?.benchmark_version, 64);
    const timeToMenu = timing(body?.time_to_menu);
    const demoLoadTime = timing(body?.demo_load_time);
    if (!id || !installationId || !submittedConfigurationKey || !cpu || !storage || !benchmarkVersion || timeToMenu === null || demoLoadTime === null) {
      return json({ error: "invalid benchmark result" }, 400);
    }

    const configurationKey = await deriveConfigurationKey(cpu, storage, benchmarkVersion);
    if (configurationKey !== submittedConfigurationKey) return json({ error: "invalid configuration" }, 400);

    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${installSalt}:${installationId}`));
    const installationHash = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
    const windowMinute = new Date();
    windowMinute.setSeconds(0, 0); // round to minute
    const { data: count, error: rateError } = await db.rpc(
      "increment_benchmark_rate_limit",
      { p_installation_hash: installationHash, p_window_started_at: windowMinute.toISOString() }
    );
    if (rateError) return json({ error: "service unavailable" }, 503);
    if ((count ?? 0) >= 5) return json({ error: "rate limited" }, 429);

    const { error } = await db.from("benchmark_runs_v2").upsert({
      id,
      installation_hash: installationHash,
      configuration_key: configurationKey,
      cpu,
      storage,
      storage_bus: storageBus,
      benchmark_version: benchmarkVersion,
      time_to_menu: timeToMenu,
      demo_load_time: demoLoadTime,
      received_at: new Date().toISOString(),
    }, { onConflict: "id" });
    return error ? json({ error: "service unavailable" }, 503) : json({ accepted: true }, 202);
  }

  if (request.method === "GET" && url.pathname.endsWith("/benchmark/configurations")) {
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 30, 1), 100);
    const offset = Math.max(Number(url.searchParams.get("offset")) || 0, 0);
    const ascending = url.searchParams.get("sort") !== "desc";
    const query = url.searchParams.get("q")?.slice(0, 100).replace(/[,%.*()]/g, '');
    let requestBuilder = db.from("benchmark_configuration_summary_v2").select("*").order("median_total_time", { ascending }).range(offset, offset + limit - 1);
    if (query) requestBuilder = requestBuilder.or(`cpu.ilike.%${query}%,storage.ilike.%${query}%`);
    const { data, error } = await requestBuilder;
    return error ? json({ error: "service unavailable" }, 503) : json({ items: data ?? [] });
  }

  const match = url.pathname.match(/\/benchmark\/configurations\/([a-f0-9]{64})$/i);
  if (request.method === "GET" && match) {
    const key = match[1];
    const { data, error } = await db.rpc("calculate_benchmark_medians", { target_configuration_key: key });
    if (error || !data) return json({ error: "not found" }, 404);
    return json(data);
  }

  return json({ error: "not found" }, 404);
});
