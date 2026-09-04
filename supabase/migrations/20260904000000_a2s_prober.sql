-- Real A2S measurements from the always-on prober (tools/server_prober).
--
-- Why: the shared catalogue was filled only by gamemonitoring.net, which lags
-- by minutes, misses servers that are not in its catalogue, and rates its own
-- wipe times as "medium" confidence. The prober asks the servers themselves.
-- Both sources are kept side by side on purpose: the aggregator still owns
-- wipe schedules, which A2S cannot provide.
alter table public.server_intelligence_catalog
    add column if not exists a2s_online boolean,
    add column if not exists a2s_players integer,
    add column if not exists a2s_max_players integer,
    add column if not exists a2s_query_port integer check (a2s_query_port between 1 and 65535),
    add column if not exists a2s_name text check (char_length(a2s_name) <= 240),
    add column if not exists a2s_map text check (char_length(a2s_map) <= 240),
    add column if not exists a2s_checked_at timestamptz;

-- Least-recently-probed first, so one pass rotates naturally through the
-- whole catalogue instead of hammering the same few servers.
create or replace function public.prober_queue(p_limit integer default 200)
returns table (endpoint text, query_port integer)
language sql security definer set search_path = public as $$
    select c.endpoint, c.query_port
    from public.server_intelligence_catalog c
    order by c.a2s_checked_at asc nulls first, c.updated_at desc
    limit greatest(1, least(coalesce(p_limit, 200), 1000));
$$;

-- Updates existing catalogue rows only: the catalogue is filled by real users
-- saving servers, and the prober must never invent entries of its own.
create or replace function public.prober_report(p_results jsonb)
returns integer language plpgsql security definer set search_path = public as $$
declare
    item jsonb;
    updated integer := 0;
    touched integer;
begin
    if jsonb_typeof(p_results) <> 'array' then
        raise exception 'results must be an array';
    end if;
    for item in select * from jsonb_array_elements(p_results) loop
        update public.server_intelligence_catalog set
            a2s_online = case when jsonb_typeof(item->'online') = 'boolean' then (item->>'online')::boolean else a2s_online end,
            a2s_players = coalesce(nullif(item->>'players', '')::integer, a2s_players),
            a2s_max_players = coalesce(nullif(item->>'max_players', '')::integer, a2s_max_players),
            a2s_query_port = coalesce(nullif(item->>'query_port', '')::integer, a2s_query_port),
            a2s_name = coalesce(nullif(left(item->>'name', 240), ''), a2s_name),
            a2s_map = coalesce(nullif(left(item->>'map', 240), ''), a2s_map),
            a2s_checked_at = now(),
            updated_at = now()
        where server_intelligence_catalog.endpoint = item->>'endpoint';
        get diagnostics touched = row_count;
        updated := updated + touched;
    end loop;
    return updated;
end;
$$;

-- The prober authenticates with its own secret, never with the app's
-- publishable key and never with the service-role key (that one would grant
-- full database access to a box shared with unrelated projects). The secret is
-- a 64-char random token generated on the prober host, stored here only as a
-- SHA-256 hash, and compared inside the database so it never has to be read
-- back out.
create extension if not exists pgcrypto;

create table if not exists public.prober_credentials (
    name text primary key,
    secret_hash text not null,
    created_at timestamptz not null default now(),
    last_used_at timestamptz
);
alter table public.prober_credentials enable row level security;
revoke all on table public.prober_credentials from public, anon, authenticated;

create or replace function public.verify_prober_secret(p_secret text)
returns boolean language plpgsql security definer set search_path = public, extensions as $$
declare
    stored text;
    ok boolean := false;
begin
    if p_secret is null or length(p_secret) < 32 then
        return false;
    end if;
    select secret_hash into stored from public.prober_credentials where name = 'default';
    if stored is null then
        return false;
    end if;
    ok := (encode(digest(p_secret, 'sha256'), 'hex') = stored);
    if ok then
        update public.prober_credentials set last_used_at = now() where name = 'default';
    end if;
    return ok;
end;
$$;

-- Two changes to the claim function the client reads through:
--   1. it now returns the prober's a2s_* fields, or they would sit in the
--      table unseen;
--   2. #variable_conflict use_column fixes a real runtime failure. The OUT
--      parameter "endpoint" collided with the column of the same name in
--      "insert ... on conflict (endpoint)", so every call raised
--      "column reference endpoint is ambiguous" - the catalogue stayed empty
--      and each /observe silently answered "no_data".
create or replace function public.claim_server_intelligence_refresh(
    p_endpoint text, p_query_port integer default null, p_active boolean default false, p_share boolean default false
) returns table (
    endpoint text, query_port integer, gamemonitoring_server_id bigint, refresh_needed boolean,
    provider_online boolean, provider_players integer, provider_max_players integer,
    wipe_at timestamptz, source text, confidence text, provider_checked_at timestamptz,
    refresh_lease_until timestamptz, last_provider_error text,
    provider_name text, provider_map text, provider_seed integer, provider_map_size integer,
    provider_map_revision integer, provider_version text, provider_fps integer,
    provider_entity_count integer, provider_country text, provider_city text, provider_description text,
    provider_links jsonb, provider_last_wipe timestamptz, provider_pve boolean, provider_map_url text, provider_banner_url text,
    a2s_online boolean, a2s_players integer, a2s_max_players integer, a2s_query_port integer,
    a2s_name text, a2s_map text, a2s_checked_at timestamptz
) language plpgsql security definer set search_path = public as $$
#variable_conflict use_column
declare
    item public.server_intelligence_catalog%rowtype;
    refresh_after interval;
    registration_due boolean;
begin
    if p_query_port is not null and (p_query_port < 1 or p_query_port > 65535) then
        raise exception 'invalid query port';
    end if;
    insert into public.server_intelligence_catalog(endpoint, query_port)
    values (p_endpoint, p_query_port) on conflict (endpoint) do nothing;
    update public.server_intelligence_catalog
    set query_port = coalesce(p_query_port, server_intelligence_catalog.query_port),
        active_until = case when p_active then greatest(coalesce(server_intelligence_catalog.active_until, now()), now() + interval '2 minutes') else server_intelligence_catalog.active_until end,
        shared_until = case when p_share then greatest(coalesce(server_intelligence_catalog.shared_until, now()), now() + interval '6 minutes') else server_intelligence_catalog.shared_until end,
        updated_at = now()
    where server_intelligence_catalog.endpoint = p_endpoint;
    select * into item from public.server_intelligence_catalog where server_intelligence_catalog.endpoint = p_endpoint for update;
    refresh_after := case
        when item.active_until is not null and item.active_until > now() then interval '1 minute'
        when item.shared_until is not null and item.shared_until > now() then interval '5 minutes'
        else interval '100 years'
    end;
    registration_due := item.gamemonitoring_server_id is null and item.registration_retry_at <= now();
    if (item.refresh_lease_until is null or item.refresh_lease_until < now())
       and (registration_due or (item.gamemonitoring_server_id is not null and (item.provider_checked_at is null or item.provider_checked_at <= now() - refresh_after))) then
        update public.server_intelligence_catalog set refresh_lease_until = now() + interval '30 seconds', updated_at = now()
        where server_intelligence_catalog.endpoint = p_endpoint;
        refresh_needed := true;
    else
        refresh_needed := false;
    end if;
    endpoint := item.endpoint; query_port := item.query_port; gamemonitoring_server_id := item.gamemonitoring_server_id;
    provider_online := item.provider_online; provider_players := item.provider_players; provider_max_players := item.provider_max_players;
    wipe_at := item.wipe_at; source := item.source; confidence := item.confidence; provider_checked_at := item.provider_checked_at;
    refresh_lease_until := item.refresh_lease_until; last_provider_error := item.last_provider_error;
    provider_name := item.provider_name; provider_map := item.provider_map; provider_seed := item.provider_seed; provider_map_size := item.provider_map_size;
    provider_map_revision := item.provider_map_revision; provider_version := item.provider_version; provider_fps := item.provider_fps;
    provider_entity_count := item.provider_entity_count; provider_country := item.provider_country; provider_city := item.provider_city; provider_description := item.provider_description;
    provider_links := item.provider_links; provider_last_wipe := item.provider_last_wipe; provider_pve := item.provider_pve; provider_map_url := item.provider_map_url; provider_banner_url := item.provider_banner_url;
    a2s_online := item.a2s_online; a2s_players := item.a2s_players; a2s_max_players := item.a2s_max_players;
    a2s_query_port := item.a2s_query_port; a2s_name := item.a2s_name; a2s_map := item.a2s_map; a2s_checked_at := item.a2s_checked_at;
    return next;
end;
$$;

revoke all on function public.prober_queue(integer) from public, anon, authenticated;
revoke all on function public.prober_report(jsonb) from public, anon, authenticated;
revoke all on function public.verify_prober_secret(text) from public, anon, authenticated;
revoke all on function public.claim_server_intelligence_refresh(text, integer, boolean, boolean) from public, anon, authenticated;
grant execute on function public.prober_queue(integer) to service_role;
grant execute on function public.prober_report(jsonb) to service_role;
grant execute on function public.verify_prober_secret(text) to service_role;
grant execute on function public.claim_server_intelligence_refresh(text, integer, boolean, boolean) to service_role;
notify pgrst, 'reload schema';
