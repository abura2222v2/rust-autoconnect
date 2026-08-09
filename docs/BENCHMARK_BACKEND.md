# Benchmark Backend

The desktop client stores benchmark runs locally first. It sends an anonymous
copy only when the leaderboard setting is enabled and `BENCHMARK_API_URL` is
configured. The client must never contain a Supabase service-role key.

## Data model

- A configuration is the normalized CPU model, Rust installation storage model,
  and benchmark version.
- An installation is represented by a random local UUID. The Edge Function
  hashes it with a server-only salt before database storage.
- The public score is the median of per-installation medians. It is not the
  average of all raw runs.
- CPU and storage model are public. Serial numbers, drive letters, paths, and
  user names are not uploaded.

## Deployment boundary

Review and apply `supabase/migrations/20260809_benchmark_v2.sql`, set the
server-only function secrets, then deploy `supabase/functions/benchmark-api`.
Do not run those operations from the desktop application or with a client key.
