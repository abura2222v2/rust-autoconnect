# Shared server intelligence

This optional service prevents every desktop client from querying an external
schedule provider for the same Rust server.

## Deployment

1. Apply `supabase/migrations/20260809_server_intelligence.sql` with the
   project migration workflow.
2. Deploy `supabase/functions/server-intelligence`.
3. Set the public function base URL in `SERVER_INTELLIGENCE_URL`, for example
   `https://<project-ref>.supabase.co/functions/v1`.

The desktop executable receives only the public URL and a publishable/anon
key. It never receives a service-role key, personal access token, or provider
token.

## Data model and privacy

- `server_schedule_cache` holds one record per endpoint: next wipe time,
  source/confidence, and last locally-confirmed availability.
- An opt-in report carries only the endpoint. It is rate-limited using a
  daily salted hash derived inside the Edge Function; the rate-limit record is
  deleted after two days.
- No Player.log contents, Steam ID, account name, machine identifier, or Rust
  process data is uploaded.

## Schedule sources

There is no universal, authoritative next-wipe field for every Rust server.
Add a provider only through a server-side worker that writes validated results
to `server_schedule_cache`; never place a provider token or scrape logic in
the client. Each value must include a source and confidence level. A missing
schedule leaves the client in normal low-load monitoring, then it can react to
a locally observed server outage or availability signal.
