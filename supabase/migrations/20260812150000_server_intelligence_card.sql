-- Store GameMonitoring's public server card separately from the Rust connect
-- endpoint. Query ports are provider-only and never replace the Steam URL.
alter table public.server_intelligence_catalog
    add column if not exists query_port integer check (query_port between 1 and 65535),
    add column if not exists provider_name text check (char_length(provider_name) <= 240),
    add column if not exists provider_map text check (char_length(provider_map) <= 240),
    add column if not exists provider_seed integer,
    add column if not exists provider_map_size integer,
    add column if not exists provider_map_revision integer,
    add column if not exists provider_version text check (char_length(provider_version) <= 120),
    add column if not exists provider_fps integer,
    add column if not exists provider_entity_count integer,
    add column if not exists provider_country text check (char_length(provider_country) <= 120),
    add column if not exists provider_city text check (char_length(provider_city) <= 120),
    add column if not exists provider_description text check (char_length(provider_description) <= 2000),
    add column if not exists provider_links jsonb not null default '[]'::jsonb,
    add column if not exists provider_last_wipe timestamptz,
    add column if not exists provider_pve boolean,
    add column if not exists provider_map_url text check (char_length(provider_map_url) <= 2000),
    add column if not exists provider_banner_url text check (char_length(provider_banner_url) <= 2000);

drop function if exists public.claim_server_intelligence_refresh(text, boolean, boolean);
create function public.claim_server_intelligence_refresh(
    p_endpoint text, p_query_port integer default null, p_active boolean default false, p_share boolean default false
) returns table (
    endpoint text, query_port integer, gamemonitoring_server_id bigint, refresh_needed boolean,
    provider_online boolean, provider_players integer, provider_max_players integer,
    wipe_at timestamptz, source text, confidence text, provider_checked_at timestamptz,
    refresh_lease_until timestamptz, last_provider_error text,
    provider_name text, provider_map text, provider_seed integer, provider_map_size integer,
    provider_map_revision integer, provider_version text, provider_fps integer,
    provider_entity_count integer, provider_country text, provider_city text, provider_description text,
    provider_links jsonb, provider_last_wipe timestamptz, provider_pve boolean, provider_map_url text, provider_banner_url text
) language plpgsql security definer set search_path = public as $$
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
    set query_port = coalesce(p_query_port, query_port),
        active_until = case when p_active then greatest(coalesce(active_until, now()), now() + interval '2 minutes') else active_until end,
        shared_until = case when p_share then greatest(coalesce(shared_until, now()), now() + interval '6 minutes') else shared_until end,
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
    return next;
end;
$$;
revoke all on function public.claim_server_intelligence_refresh(text, integer, boolean, boolean) from public, anon, authenticated;
grant execute on function public.claim_server_intelligence_refresh(text, integer, boolean, boolean) to service_role;
notify pgrst, 'reload schema';
