// Deploy this Edge Function only after reviewing the paired migration and secrets.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = { "content-type": "application/json", "access-control-allow-origin": "*" };
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
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const installSalt = Deno.env.get("BENCHMARK_INSTALLATION_SALT");
  if (!supabaseUrl || !serviceRoleKey || !installSalt) return json({ error: "service unavailable" }, 503);
  const db = createClient(supabaseUrl, serviceRoleKey);

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
    const since = new Date(Date.now() - 60_000).toISOString();
    const { count, error: rateError } = await db
      .from("benchmark_runs_v2")
      .select("id", { count: "exact", head: true })
      .eq("installation_hash", installationHash)
      .gte("received_at", since);
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
    }, { onConflict: "id" });
    return error ? json({ error: "service unavailable" }, 503) : json({ accepted: true }, 202);
  }

  if (request.method === "GET" && url.pathname.endsWith("/benchmark/configurations")) {
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 30, 1), 100);
    const offset = Math.max(Number(url.searchParams.get("offset")) || 0, 0);
    const ascending = url.searchParams.get("sort") !== "desc";
    const query = url.searchParams.get("q")?.slice(0, 100);
    let requestBuilder = db.from("benchmark_configuration_summary_v2").select("*").order("median_total_time", { ascending }).range(offset, offset + limit - 1);
    if (query) requestBuilder = requestBuilder.or(`cpu.ilike.%${query}%,storage.ilike.%${query}%`);
    const { data, error } = await requestBuilder;
    return error ? json({ error: "service unavailable" }, 503) : json({ items: data ?? [] });
  }

  const match = url.pathname.match(/\/benchmark\/configurations\/([a-f0-9]{64})$/i);
  if (request.method === "GET" && match) {
    const key = match[1];
    const { data: summary, error: summaryError } = await db.from("benchmark_configuration_summary_v2").select("*").eq("configuration_key", key).maybeSingle();
    if (summaryError || !summary) return json({ error: "not found" }, 404);
    const { data: installations, error: detailError } = await db
      .from("benchmark_runs_v2")
      .select("installation_hash,total_time")
      .eq("configuration_key", key);
    if (detailError) return json({ error: "service unavailable" }, 503);
    const grouped = new Map<string, number[]>();
    for (const run of installations ?? []) grouped.set(run.installation_hash, [...(grouped.get(run.installation_hash) ?? []), Number(run.total_time)]);
    const items = [...grouped.values()].map((times) => ({
      median_total_time: times.sort((a, b) => a - b)[Math.floor(times.length / 2)],
      run_count: times.length,
    }));
    return json({ summary, installations: items });
  }

  return json({ error: "not found" }, 404);
});
