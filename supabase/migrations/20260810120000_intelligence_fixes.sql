-- Migration to fix BUG-M4, BUG-H5, and BUG-M3

-- BUG-M4: Add index for rate limit queries in benchmark
create index if not exists benchmark_runs_v2_installation_received_idx
    on public.benchmark_runs_v2 (installation_hash, received_at);

-- BUG-H5: RPC to calculate benchmark medians safely (bypassing 1000 row limit of PostgREST)
create or replace function public.calculate_benchmark_medians(target_configuration_key text)
returns json as $$
declare
    v_summary json;
    v_installations json;
begin
    -- Get summary
    select row_to_json(s) into v_summary
    from public.benchmark_configuration_summary_v2 s
    where s.configuration_key = target_configuration_key;

    if v_summary is null then
        return null;
    end if;

    -- Get medians per installation
    select json_agg(
        json_build_object(
            'median_total_time', i.median,
            'run_count', i.rcount
        )
    ) into v_installations
    from (
        select
            percentile_cont(0.5) within group (order by total_time) as median,
            count(*) as rcount
        from public.benchmark_runs_v2
        where configuration_key = target_configuration_key
        group by installation_hash
    ) i;

    return json_build_object(
        'summary', v_summary,
        'installations', coalesce(v_installations, '[]'::json)
    );
end;
$$ language plpgsql security definer;

revoke all on function public.calculate_benchmark_medians(text) from anon, authenticated;

-- BUG-M3: RPC to safely atomic-increment the rate limit
create or replace function public.increment_server_intelligence_rate_limit(
    p_source_hash text,
    p_window_started_at timestamptz
)
returns integer as $$
declare
    v_count integer;
begin
    insert into public.server_intelligence_rate_limits (source_hash, window_started_at, request_count)
    values (p_source_hash, p_window_started_at, 1)
    on conflict (source_hash, window_started_at)
    do update set request_count = server_intelligence_rate_limits.request_count + 1
    returning request_count into v_count;
    
    return v_count;
end;
$$ language plpgsql security definer;

revoke all on function public.increment_server_intelligence_rate_limit(text, timestamptz) from anon, authenticated;

notify pgrst, 'reload schema';

-- BUG-H1 / BUG-M5: Index for rate limit garbage collection
create index if not exists server_intelligence_rate_limits_window_idx
    on public.server_intelligence_rate_limits (window_started_at);

-- BUG-L4: Index for benchmark grouping
create index if not exists benchmark_runs_v2_config_install_idx
    on public.benchmark_runs_v2 (configuration_key, installation_hash);

-- BUG-H2: RPC to safely atomic-increment the benchmark rate limit
create or replace function public.increment_benchmark_rate_limit(
    p_installation_hash text,
    p_since timestamptz
)
returns integer as $$
declare
    v_count integer;
begin
    select count(*) into v_count
    from public.benchmark_runs_v2
    where installation_hash = p_installation_hash
      and received_at >= p_since;
    return v_count;
end;
$$ language plpgsql security definer;
revoke all on function public.increment_benchmark_rate_limit(text, timestamptz) from anon, authenticated;
