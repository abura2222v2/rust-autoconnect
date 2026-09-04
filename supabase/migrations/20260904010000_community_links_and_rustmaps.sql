-- Real per-server community links (Discord/website/rules), parsed from the
-- provider's own description text - not guessed, not hardcoded. Servers
-- commonly write these as plain lines ("Discord: discord.gg/x", "Full Rules:
-- example.com/rules") without a URL scheme, which the previous link-scraping
-- regex (https?://... only) silently missed entirely.
alter table public.server_intelligence_catalog
    add column if not exists provider_discord_url text check (char_length(provider_discord_url) <= 512),
    add column if not exists provider_website_url text check (char_length(provider_website_url) <= 512),
    add column if not exists provider_rules_url text check (char_length(provider_rules_url) <= 512);

-- Real per-seed map viewer data from the official RustMaps.com API, keyed off
-- the seed/size the aggregator already reports. Best-effort: many servers'
-- seed/size are never known (the aggregator's own A2S rules() query can be
-- blocked too), so this stays empty rather than pointing at a generic page.
alter table public.server_intelligence_catalog
    add column if not exists rustmaps_id text check (char_length(rustmaps_id) <= 64),
    add column if not exists rustmaps_url text check (char_length(rustmaps_url) <= 512),
    add column if not exists rustmaps_image_url text check (char_length(rustmaps_image_url) <= 512),
    add column if not exists rustmaps_checked_at timestamptz;

-- Small store for server-only outbound credentials (like the RustMaps API
-- key) that the edge function presents to third parties. Distinct from
-- prober_credentials, which verifies an INBOUND caller by hash and never
-- needs to read a secret back out - this one is read back by design, so RLS
-- plus revoking anon/authenticated/public is the only protection, same as
-- every other service-role-only table here.
--
-- The actual key value is never checked into this repo - it was inserted
-- directly against the live database. Set it (or rotate it) with:
--   insert into public.app_secrets (name, value) values ('rustmaps_api_key', '<key>')
--   on conflict (name) do update set value = excluded.value, updated_at = now();
create table if not exists public.app_secrets (
    name text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);
alter table public.app_secrets enable row level security;
revoke all on table public.app_secrets from public, anon, authenticated;
notify pgrst, 'reload schema';
