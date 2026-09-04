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
function queryPort(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const candidate = typeof value === "number" ? value : Number(value);
  return Number.isInteger(candidate) && candidate >= 1 && candidate <= 65535 ? candidate : null;
}
function endpointWithPort(address: string, port: number | null): string | null {
  if (!port) return null;
  const separator = address.lastIndexOf(":");
  return separator > 0 ? `${address.slice(0, separator)}:${port}` : null;
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
function asText(value: unknown, limit = 2_000): string | null {
  return typeof value === "string" && value.trim() ? value.trim().slice(0, limit) : null;
}
function asUrl(value: unknown): string | null {
  const candidate = asText(value, 2_000);
  if (!candidate) return null;
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}
function asLinks(value: unknown): string[] {
  const values = Array.isArray(value) ? value : [value];
  return [...new Set(values.map(asUrl).filter((item): item is string => item !== null))].slice(0, 12);
}
function descriptionLinks(value: unknown): string[] {
  const text = asText(value) ?? "";
  return asLinks(text.match(/https?:\/\/[^\s<>()]+/g) ?? []);
}
function descriptionImage(value: unknown): string | null {
  const text = asText(value) ?? "";
  const match = text.match(/!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/);
  return asUrl(match?.[1]);
}
function normalizeCandidateUrl(raw: string): string | null {
  let candidate = raw.trim().replace(/[),.;]+$/, "");
  if (!candidate) return null;
  const hasScheme = /^https?:\/\//i.test(candidate);
  if (!hasScheme) {
    // Require something domain-shaped (word.tld[/path]) before promoting a
    // bare word into a URL - "Rules: NoRaiding" must not become
    // https://noraiding, which the WHATWG URL parser would otherwise accept
    // as a single-label host.
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+(\/\S*)?$/i.test(candidate)) return null;
    candidate = `https://${candidate}`;
  }
  return asUrl(candidate);
}
// Server operators almost always write their community links as plain text
// lines in the description ("Discord: discord.gg/x", "Full Rules:
// example.com/rules") without an http(s):// scheme - descriptionLinks() above
// only ever caught scheme-prefixed URLs, so labelled bare-domain mentions
// (the common case) were silently dropped. Verified against a real, live
// server description (2026-09-04).
function communityLinksFromText(text: string): { discord: string | null; rules: string | null; website: string | null } {
  const lines = text.split(/\r?\n/);
  let discord: string | null = null;
  let rules: string | null = null;
  let website: string | null = null;
  for (const line of lines) {
    const discordMatch = line.match(/^\s*discord\s*:?\s*(.+)$/i);
    if (discordMatch && !discord) discord = normalizeCandidateUrl(discordMatch[1]);
    const rulesMatch = line.match(/^\s*(?:full\s+)?rules?\s*:?\s*(.+)$/i);
    if (rulesMatch && !rules) rules = normalizeCandidateUrl(rulesMatch[1]);
    const siteMatch = line.match(/^\s*(?:web\s*site|website|site|web)\s*:?\s*(.+)$/i);
    if (siteMatch && !website) website = normalizeCandidateUrl(siteMatch[1]);
  }
  // A bare discord.gg/discord.com mention is unambiguous even without a label.
  if (!discord) {
    const bare = text.match(/\b(?:https?:\/\/)?(?:www\.)?(discord\.(?:gg|com\/invite)\/[A-Za-z0-9-]+)/i);
    if (bare) discord = normalizeCandidateUrl(bare[1]);
  }
  if (!website && rules) {
    try {
      const url = new URL(rules);
      website = `${url.protocol}//${url.host}`;
    } catch { /* leave null */ }
  }
  return { discord, rules, website };
}
function providerValue(payload: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) if (payload[key] !== undefined && payload[key] !== null) return payload[key];
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
function snapshot(row: Record<string, unknown>, refreshNeeded = false): Record<string, unknown> {
  const checkedAt = typeof row.provider_checked_at === "string" ? row.provider_checked_at : null;
  const providerFresh = checkedAt !== null && Date.now() - new Date(checkedAt).getTime() <= 125_000;
  // A real A2S probe from the always-on prober beats the aggregator whenever
  // it is recent: it answers "is this server up right now" in seconds rather
  // than minutes, and it covers servers the aggregator has never heard of.
  // The aggregator still owns wipe schedules, which A2S cannot provide.
  const a2sCheckedAt = typeof row.a2s_checked_at === "string" ? row.a2s_checked_at : null;
  const a2sFresh = a2sCheckedAt !== null
    && Date.now() - new Date(a2sCheckedAt).getTime() <= 180_000
    && typeof row.a2s_online === "boolean";
  const fresh = a2sFresh || providerFresh;
  const gameMonitoringId = providerId(row.gamemonitoring_server_id);
  const refreshState = refreshNeeded || (!fresh && typeof row.refresh_lease_until === "string" && new Date(String(row.refresh_lease_until)).getTime() > Date.now())
    ? "refreshing"
    : (checkedAt || a2sCheckedAt) ? (fresh ? "ready" : "stale")
    : row.last_provider_error ? "unavailable" : "no_data";
  // Self-heals rows that were refreshed before community-link parsing
  // existed (or before it learned to read bare, unlabelled domains) - no
  // need to wait for their next provider refresh cycle.
  const needsLiveParse = !row.provider_discord_url || !row.provider_website_url || !row.provider_rules_url;
  const liveCommunity = needsLiveParse
    ? communityLinksFromText(typeof row.provider_description === "string" ? row.provider_description : "")
    : { discord: null, rules: null, website: null };
  return {
    wipe_at: row.wipe_at ? Math.floor(new Date(String(row.wipe_at)).getTime() / 1000) : null,
    source: a2sFresh ? "a2s" : (row.source ?? ""), confidence: row.confidence ?? "unknown",
    online: a2sFresh
      ? row.a2s_online as boolean
      : (typeof row.provider_online === "boolean" ? row.provider_online : null),
    players: a2sFresh ? asInteger(row.a2s_players) : asInteger(row.provider_players),
    max_players: a2sFresh ? asInteger(row.a2s_max_players) : asInteger(row.provider_max_players),
    checked_at: a2sFresh ? a2sCheckedAt : checkedAt, fresh,
    status: refreshState, query_port: asInteger(row.a2s_query_port) ?? asInteger(row.query_port),
    server_id: gameMonitoringId,
    // The live probe knows the current name and map; the aggregator's copy is
    // the fallback for servers it has not been asked about recently.
    name: asText(row.a2s_name) || asText(row.provider_name),
    map: asText(row.a2s_map) || asText(row.provider_map),
    seed: asInteger(row.provider_seed), map_size: asInteger(row.provider_map_size),
    map_revision: asInteger(row.provider_map_revision), version: asText(row.provider_version, 120),
    fps: asInteger(row.provider_fps), entity_count: asInteger(row.provider_entity_count),
    country: asText(row.provider_country, 120), city: asText(row.provider_city, 120), description: asText(row.provider_description),
    links: asLinks(row.provider_links), last_wipe: row.provider_last_wipe
      ? Math.floor(new Date(String(row.provider_last_wipe)).getTime() / 1000) : null,
    pve: asBoolean(row.provider_pve), map_url: asUrl(row.provider_map_url), banner_url: asUrl(row.provider_banner_url),
    server_url: gameMonitoringId ? `https://gamemonitoring.net/rust/servers/${gameMonitoringId}` : null,
    // Real per-server community links, parsed from the operator's own
    // listing - never guessed, empty when genuinely not found.
    discord: asUrl(row.provider_discord_url) ?? liveCommunity.discord,
    website: asUrl(row.provider_website_url) ?? liveCommunity.website,
    rules: asUrl(row.provider_rules_url) ?? liveCommunity.rules,
    // Real per-seed map viewer from the official RustMaps.com API - empty
    // when the seed/size is unknown or RustMaps has no cached result yet.
    rustmaps_url: asUrl(row.rustmaps_url),
    rustmaps_image_url: asUrl(row.rustmaps_image_url),
  };
}
async function provider(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${providerBase}${path}`, {
    ...init, headers: { "accept": "application/json", "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) throw new Error(`provider_${response.status}`);
  return await response.json();
}
let cachedRustmapsKey: string | null | undefined;
async function getRustmapsApiKey(db: ReturnType<typeof createClient>): Promise<string | null> {
  if (cachedRustmapsKey !== undefined) return cachedRustmapsKey;
  const { data } = await db.from("app_secrets").select("value").eq("name", "rustmaps_api_key").maybeSingle();
  cachedRustmapsKey = (data && typeof data.value === "string" && data.value) || null;
  return cachedRustmapsKey;
}
// Best-effort only: many servers' seed/size are never known at all (the
// aggregator's own A2S rules() query can be blocked, same as ours), so a
// RustMaps miss must never affect the gamemonitoring refresh it rides
// alongside - errors here are swallowed on purpose.
async function refreshRustmaps(db: ReturnType<typeof createClient>, endpoint: string, seed: number, size: number): Promise<void> {
  try {
    const key = await getRustmapsApiKey(db);
    if (!key) return;
    const response = await fetch(`https://rustmaps.com/api/v2/maps/${seed}/${size}?staging=false`, {
      headers: { "X-API-Key": key },
    });
    if (!response.ok) return;
    const map = await response.json();
    const id = typeof map?.id === "string" ? map.id : null;
    if (!id) return;
    await db.from("server_intelligence_catalog").update({
      rustmaps_id: id,
      rustmaps_url: asUrl(map.url) ?? `https://rustmaps.com/map/${id}`,
      rustmaps_image_url: asUrl(map.imageUrl),
      rustmaps_checked_at: new Date().toISOString(),
    }).eq("endpoint", endpoint);
  } catch {
    /* best-effort enrichment only */
  }
}
async function refresh(db: ReturnType<typeof createClient>, claim: Record<string, unknown>): Promise<void> {
  const address = String(claim.endpoint);
  const query = endpointWithPort(address, queryPort(claim.query_port));
  let serverId = providerId(claim.gamemonitoring_server_id);
  try {
    if (!serverId) {
      const registered = await provider("/servers", {
        method: "POST", body: JSON.stringify({ connect: address, ...(query ? { query } : {}), steam_app_id: 252490 }),
      });
      serverId = providerId(registered);
      if (!serverId) {
        await db.from("server_intelligence_catalog").update({
          registration_retry_at: new Date(Date.now() + 5 * 60_000).toISOString(),
          refresh_lease_until: null, last_provider_error: "registration_id_missing", updated_at: new Date().toISOString(),
        }).eq("endpoint", address);
        return;
      }
    }
    const payload = providerRecord(await provider(`/servers/${serverId}`));
    const checkedAt = new Date().toISOString();
    const description = providerValue(payload, "description");
    const community = communityLinksFromText(asText(description) ?? "");
    const explicitWebsite = asUrl(providerValue(payload, "website", "url"));
    const seed = asInteger(providerValue(payload, "seed", "map_seed"));
    const mapSize = asInteger(providerValue(payload, "worldsize", "map_size", "size"));
    await db.from("server_intelligence_catalog").update({
      gamemonitoring_server_id: serverId,
      provider_online: asBoolean(payload.status ?? payload.online),
      provider_players: asInteger(providerValue(payload, "numplayers", "players", "player_count")),
      provider_max_players: asInteger(providerValue(payload, "maxplayers", "max_players", "max_player_count")),
      wipe_at: asDate(payload.next_wipe), source: "gamemonitoring", confidence: payload.next_wipe ? "medium" : "unknown",
      provider_name: asText(providerValue(payload, "name", "servername"), 240),
      provider_map: asText(providerValue(payload, "map", "map_name"), 240),
      provider_seed: seed,
      provider_map_size: mapSize,
      provider_map_revision: asInteger(providerValue(payload, "map_revision", "maprevision", "revision")),
      provider_version: asText(providerValue(payload, "version", "game_version"), 120),
      provider_fps: asInteger(providerValue(payload, "fps", "average_fps", "avgfps")),
      provider_entity_count: asInteger(providerValue(payload, "entities_count", "entity_count", "entities")),
      provider_country: asText(providerValue(payload, "country", "country_name"), 120),
      provider_city: asText(providerValue(payload, "city", "city_name"), 120),
      provider_description: asText(description),
      provider_links: asLinks([
        ...(Array.isArray(providerValue(payload, "links")) ? providerValue(payload, "links") as unknown[] : []),
        providerValue(payload, "website", "url"),
        ...descriptionLinks(description),
      ]),
      provider_discord_url: community.discord,
      provider_website_url: explicitWebsite ?? community.website,
      provider_rules_url: community.rules,
      provider_last_wipe: asDate(providerValue(payload, "last_wipe", "lastwipe")),
      provider_pve: asBoolean(providerValue(payload, "pve", "is_pve")),
      provider_map_url: asUrl(providerValue(payload, "map_url", "map_image", "map_image_url")),
      provider_banner_url: asUrl(providerValue(payload, "headerimage", "header_image", "banner"))
        ?? descriptionImage(description),
      provider_checked_at: checkedAt, refresh_lease_until: null, registration_retry_at: "-infinity",
      last_provider_error: "", updated_at: checkedAt,
    }).eq("endpoint", address);
    if (seed && mapSize) {
      const { data: existing } = await db.from("server_intelligence_catalog")
        .select("rustmaps_id, rustmaps_checked_at").eq("endpoint", address).maybeSingle();
      const staleAfterMs = 24 * 60 * 60_000;
      const needsLookup = !existing?.rustmaps_id
        || !existing?.rustmaps_checked_at
        || Date.now() - new Date(String(existing.rustmaps_checked_at)).getTime() > staleAfterMs;
      if (needsLookup) EdgeRuntime.waitUntil(refreshRustmaps(db, address, seed, mapSize));
    }
  } catch (error) {
    const retry = !serverId ? { registration_retry_at: new Date(Date.now() + 5 * 60_000).toISOString() } : {};
    await db.from("server_intelligence_catalog").update({
      refresh_lease_until: null, last_provider_error: error instanceof Error ? error.message.slice(0, 120) : "provider_error",
      updated_at: new Date().toISOString(), ...retry,
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

  // The always-on prober speaks through its own shared secret, which only it
  // and this function hold - the app's publishable key must never be enough
  // to write measurements. Its routes are handled before the per-minute
  // guard below, which is sized for interactive clients, not for a process
  // that reports on hundreds of servers at once.
  if (url.pathname.endsWith("/server-intelligence/probe-queue")
      || url.pathname.endsWith("/server-intelligence/probe-report")) {
    // Verified inside the database: the secret is stored only as a hash, so
    // it never has to be read back out of storage to be checked.
    const presented = request.headers.get("x-prober-secret") ?? "";
    const { data: allowed, error: secretError } = await db.rpc("verify_prober_secret", { p_secret: presented });
    if (secretError) return json({ error: "service unavailable" }, 503);
    if (allowed !== true) return json({ error: "unauthorized" }, 401);
    if (url.pathname.endsWith("/server-intelligence/probe-queue")) {
      const limit = asInteger(body?.limit) ?? 200;
      const { data, error } = await db.rpc("prober_queue", { p_limit: limit });
      if (error) return json({ error: "service unavailable" }, 503);
      return json({ endpoints: Array.isArray(data) ? data : [] });
    }
    const results = Array.isArray(body?.results) ? body.results.slice(0, 100) : [];
    const clean = results.filter((item: unknown) =>
      item && typeof item === "object" && endpoint((item as Record<string, unknown>).endpoint));
    if (!clean.length) return json({ updated: 0 });
    const { data, error } = await db.rpc("prober_report", { p_results: clean });
    if (error) return json({ error: "service unavailable" }, 503);
    return json({ updated: Number(data) || 0 });
  }

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
      p_endpoint: server, p_query_port: queryPort(body?.query_port), p_active: Boolean(body?.active), p_share: false,
    });
    if (error || !Array.isArray(data) || !data[0]) return json({ error: "service unavailable" }, 503);
    const claim = data[0] as Record<string, unknown>;
    if (claim.refresh_needed) EdgeRuntime.waitUntil(refresh(db, claim));
    return json(snapshot(claim, Boolean(claim.refresh_needed)));
  }

  if (url.pathname.endsWith("/server-intelligence/share")) {
    const endpoints = Array.isArray(body?.endpoints)
      ? body.endpoints.map((item) => {
        const value = typeof item === "string" ? { endpoint: item } : item as Record<string, unknown>;
        const server = endpoint(value?.endpoint);
        return server ? { endpoint: server, queryPort: queryPort(value?.query_port) } : null;
      }).filter((item): item is { endpoint: string; queryPort: number | null } => item !== null).slice(0, 20) : [];
    if (!endpoints.length) return json({ error: "invalid endpoints" }, 400);
    const claims: Record<string, unknown>[] = [];
    for (const server of endpoints) {
      const { data, error } = await db.rpc("claim_server_intelligence_refresh", {
        p_endpoint: server.endpoint, p_query_port: server.queryPort, p_active: false, p_share: true,
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
