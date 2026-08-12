# Shared server intelligence

This optional service prevents every desktop client from querying GameMonitoring
for the same Rust server. It is a cache and a scheduling hint: local A2S still
decides whether the application launches Steam, and `Player.log` confirms entry.

## Deployment

1. Apply `supabase/migrations/20260812140000_gamemonitoring_catalog.sql` with the
   project migration workflow.
2. Deploy `supabase/functions/server-intelligence`.
3. Set the public function base URL in `SERVER_INTELLIGENCE_URL`, for example
   `https://<project-ref>.supabase.co/functions/v1`.

The desktop executable receives only the public URL and a publishable/anon
key. It never receives a service-role key, personal access token, or provider
token.

## Data model and privacy

- `server_intelligence_catalog` holds one canonical `IP:PORT` endpoint, its
  GameMonitoring ID, cached online/player data, next-wipe hint and a refresh
  lease. A lease means many clients produce at most one provider request.
- An active Connect/armed endpoint is refreshed at most once per minute.
  Opted-in saved endpoints are refreshed at most once per ten minutes.
- An unknown endpoint is registered through the documented GameMonitoring
  `POST /servers` only for an active Connect or an opted-in saved server. If a
  provider ID is not returned, retry is delayed for 30 days.
- Opting in sends only saved server addresses. No Player.log contents, Steam
  ID, account name, machine identifier, Rust process data, or player lists are
  uploaded.

## Schedule sources

GameMonitoring's documented `GET /servers/:server_id` is used once an endpoint
has an ID. It provides public `status`, player counts, and `next_wipe` when the
provider has one. The app never requests player names. There is no universal,
authoritative next-wipe field for every Rust server, so a missing or stale value
leaves normal low-load monitoring in place. The client can react to locally
observed outages or a Swarm signal, but neither external signal launches Steam
on its own.
