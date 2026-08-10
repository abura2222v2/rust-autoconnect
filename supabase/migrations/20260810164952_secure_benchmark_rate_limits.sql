-- BUG-C2: Secure the rate limits table
alter table public.benchmark_rate_limits enable row level security;
revoke all on public.benchmark_rate_limits from anon, authenticated;
