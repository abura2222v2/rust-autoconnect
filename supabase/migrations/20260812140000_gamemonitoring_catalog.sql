-- Shared provider cache. Desktop clients only invoke the Edge Function; all
-- provider traffic and registration are kept server-side.
create table if not exists public.server_intelligence_catalog (
    endpoint text primary key check (endpoint ~ '^[A-Za-z0-9.-]{1,253}:[0-9]{1,5}$'),
    gamemonitoring_server_id bigint,
    provider_online boolean,
    provider_players integer check (provider_players is null or provider_players >= 0),
    provider_max_players integer check (provider_max_players is null or provider_max_players >= 0),
    wipe_at timestamptz,
    source text not null default '' check (char_length(source) <= 64),
    confidence text not null default 'unknown' check (confidence in ('unknown', 'low', 'medium', 'high')),
    provider_checked_at timestamptz,
    active_until timestamptz,
    shared_until timestamptz,
    refresh_lease_until timestamptz,
    registration_retry_at timestamptz not null default '-infinity'::timestamptz,
    last_provider_error text not null default '' check (char_length(last_provider_error) <= 120),
    updated_at timestamptz not null default now()
);
alter table public.server_intelligence_catalog enable row level security;
revoke all on public.server_intelligence_catalog from anon, authenticated;
create index if not exists server_intelligence_catalog_refresh_idx
    on public.server_intelligence_catalog (active_until, shared_until, provider_checked_at);

-- Atomically mark interest and lease at most one provider refresh per endpoint.
create or replace function public.claim_server_intelligence_refresh(
    p_endpoint text, p_active boolean default false, p_share boolean default false
) returns table (
    endpoint text, gamemonitoring_server_id bigint, refresh_needed boolean,
    provider_online boolean, provider_players integer, provider_max_players integer,
    wipe_at timestamptz, source text, confidence text, provider_checked_at timestamptz
) language plpgsql security definer set search_path = public as $$
declare
    item public.server_intelligence_catalog%rowtype;
    refresh_after interval;
    registration_due boolean;
begin
    insert into public.server_intelligence_catalog(endpoint)
    values (p_endpoint) on conflict (endpoint) do nothing;

    update public.server_intelligence_catalog
    set active_until = case when p_active then greatest(coalesce(active_until, now()), now() + interval '2 minutes') else active_until end,
        shared_until = case when p_share then greatest(coalesce(shared_until, now()), now() + interval '11 minutes') else shared_until end,
        updated_at = now()
    where server_intelligence_catalog.endpoint = p_endpoint;

    select * into item from public.server_intelligence_catalog
    where server_intelligence_catalog.endpoint = p_endpoint for update;

    refresh_after := case
        when item.active_until is not null and item.active_until > now() then interval '1 minute'
        when item.shared_until is not null and item.shared_until > now() then interval '10 minutes'
        else interval '100 years'
    end;
    registration_due := item.gamemonitoring_server_id is null and item.registration_retry_at <= now();

    if (item.refresh_lease_until is null or item.refresh_lease_until < now())
       and (registration_due or item.provider_checked_at is null or item.provider_checked_at <= now() - refresh_after) then
        update public.server_intelligence_catalog
        set refresh_lease_until = now() + interval '30 seconds', updated_at = now()
        where server_intelligence_catalog.endpoint = p_endpoint;
        refresh_needed := true;
    else
        refresh_needed := false;
    end if;

    endpoint := item.endpoint;
    gamemonitoring_server_id := item.gamemonitoring_server_id;
    provider_online := item.provider_online;
    provider_players := item.provider_players;
    provider_max_players := item.provider_max_players;
    wipe_at := item.wipe_at;
    source := item.source;
    confidence := item.confidence;
    provider_checked_at := item.provider_checked_at;
    return next;
end;
$$;
revoke all on function public.claim_server_intelligence_refresh(text, boolean, boolean) from public, anon, authenticated;
grant execute on function public.claim_server_intelligence_refresh(text, boolean, boolean) to service_role;
notify pgrst, 'reload schema';
