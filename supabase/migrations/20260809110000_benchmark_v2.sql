-- Apply through a reviewed Supabase migration. Do not run this from the desktop client.

create table if not exists public.benchmark_runs_v2 (
    id uuid primary key,
    installation_hash text not null,
    configuration_key text not null,
    cpu text not null,
    storage text not null,
    storage_bus text not null default 'Unknown',
    benchmark_version text not null,
    time_to_menu numeric not null check (time_to_menu >= 2 and time_to_menu <= 600),
    demo_load_time numeric not null check (demo_load_time >= 2 and demo_load_time <= 600),
    total_time numeric generated always as (time_to_menu + demo_load_time) stored,
    created_at timestamptz not null default now(),
    received_at timestamptz not null default now()
);

create index if not exists benchmark_runs_v2_configuration_idx
    on public.benchmark_runs_v2 (configuration_key, created_at desc);
create index if not exists benchmark_runs_v2_installation_idx
    on public.benchmark_runs_v2 (installation_hash, configuration_key);

alter table public.benchmark_runs_v2 enable row level security;
revoke all on public.benchmark_runs_v2 from anon, authenticated;

create or replace view public.benchmark_configuration_summary_v2
with (security_invoker = true) as
with installation_medians as (
    select
        configuration_key,
        installation_hash,
        min(cpu) as cpu,
        min(storage) as storage,
        min(storage_bus) as storage_bus,
        min(benchmark_version) as benchmark_version,
        percentile_cont(0.5) within group (order by total_time) as installation_median,
        count(*) as run_count
    from public.benchmark_runs_v2
    group by configuration_key, installation_hash
)
select
    configuration_key,
    min(cpu) as cpu,
    min(storage) as storage,
    min(storage_bus) as storage_bus,
    min(benchmark_version) as benchmark_version,
    percentile_cont(0.5) within group (order by installation_median) as median_total_time,
    min(installation_median) as min_total_time,
    max(installation_median) as max_total_time,
    count(*) as installation_count,
    sum(run_count) as run_count
from installation_medians
group by configuration_key;

revoke all on public.benchmark_configuration_summary_v2 from anon, authenticated;
