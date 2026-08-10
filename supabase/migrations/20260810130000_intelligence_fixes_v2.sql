-- BUG-C4: Secure RPCs by revoking EXECUTE from PUBLIC
revoke execute on function public.calculate_benchmark_medians(text) from public;
revoke execute on function public.increment_server_intelligence_rate_limit(text, timestamptz) from public;

-- BUG-C3: Create atomic rate limit table for benchmarks
create table if not exists public.benchmark_rate_limits (
    installation_hash text not null,
    window_started_at timestamptz not null,
    request_count integer not null default 1,
    primary key (installation_hash, window_started_at)
);

-- Index for GC
create index if not exists benchmark_rate_limits_window_idx
    on public.benchmark_rate_limits (window_started_at);

-- BUG-C2: Secure the rate limits table
alter table public.benchmark_rate_limits enable row level security;
revoke all on public.benchmark_rate_limits from anon, authenticated;

-- BUG-C3: Rewrite increment_benchmark_rate_limit to use the atomic table
drop function if exists public.increment_benchmark_rate_limit(text, timestamptz);

create or replace function public.increment_benchmark_rate_limit(
    p_installation_hash text,
    p_window_started_at timestamptz
)
returns integer as $$
declare
    v_count integer;
begin
    insert into public.benchmark_rate_limits (installation_hash, window_started_at, request_count)
    values (p_installation_hash, p_window_started_at, 1)
    on conflict (installation_hash, window_started_at)
    do update set request_count = benchmark_rate_limits.request_count + 1
    returning request_count into v_count;
    
    return v_count;
end;
$$ language plpgsql security definer;

-- Secure the new RPC
revoke execute on function public.increment_benchmark_rate_limit(text, timestamptz) from public;
revoke all on function public.increment_benchmark_rate_limit(text, timestamptz) from anon, authenticated;

-- Ensure schema reload
notify pgrst, 'reload schema';
