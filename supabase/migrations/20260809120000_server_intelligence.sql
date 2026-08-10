-- Shared, privacy-minimised cache for server schedules and availability.
-- Apply through Supabase migrations; never from the desktop application.

create table if not exists public.server_schedule_cache (
    endpoint text primary key check (endpoint ~ '^[A-Za-z0-9.-]{1,253}:[0-9]{1,5}$'),
    wipe_at timestamptz,
    source text not null default '' check (char_length(source) <= 64),
    confidence text not null default 'unknown' check (confidence in ('unknown', 'low', 'medium', 'high')),
    provider_checked_at timestamptz,
    last_available_at timestamptz,
    updated_at timestamptz not null default now()
);

alter table public.server_schedule_cache enable row level security;
revoke all on public.server_schedule_cache from anon, authenticated;

create index if not exists server_schedule_cache_wipe_at_idx
    on public.server_schedule_cache (wipe_at);

-- The Edge Function accesses Supabase through PostgREST, whose exposed schema
-- is `public`. RLS plus revoked grants keep this internal rate-limit table
-- inaccessible to desktop clients; only the Function's server-side key can
-- bypass those protections.
create table if not exists public.server_intelligence_rate_limits (
    source_hash text not null,
    window_started_at timestamptz not null,
    request_count integer not null default 0 check (request_count >= 0),
    primary key (source_hash, window_started_at)
);
alter table public.server_intelligence_rate_limits enable row level security;
revoke all on public.server_intelligence_rate_limits from anon, authenticated;

-- Refresh PostgREST immediately so the deployed Edge Function can see the
-- newly-created public tables without waiting for the schema-cache interval.
notify pgrst, 'reload schema';
