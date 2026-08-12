-- Telegram is an Edge Function integration. Desktop clients never receive
-- direct INSERT/UPDATE access to these tables.  This migration also supports
-- projects where the earlier experimental Telegram migration was never run.
create table if not exists public.telegram_links (
    client_id uuid primary key,
    link_code text unique,
    chat_id bigint unique,
    created_at timestamptz not null default now()
);
alter table public.telegram_links add column if not exists link_expires_at timestamptz;
alter table public.telegram_links add column if not exists notification_token_hash text;
alter table public.telegram_links add column if not exists preferences jsonb not null default '{}'::jsonb;
alter table public.telegram_links alter column link_code drop not null;
alter table public.telegram_links enable row level security;

revoke all on public.telegram_links from anon, authenticated;

create table if not exists public.telegram_queue_state (
    client_id uuid not null references public.telegram_links(client_id) on delete cascade,
    server text not null check (char_length(server) <= 253),
    last_position integer not null check (last_position >= 0),
    updated_at timestamptz not null default now(),
    primary key (client_id, server)
);
alter table public.telegram_queue_state enable row level security;
revoke all on public.telegram_queue_state from anon, authenticated;

-- Remove policies/trigger only if the retired experimental table exists.
do $$
begin
    if to_regclass('public.tg_notifications') is not null then
        execute 'drop policy if exists "Allow public insert to tg_notifications" on public.tg_notifications';
        execute 'revoke all on public.tg_notifications from anon, authenticated';
        execute 'drop trigger if exists tg_notification_trigger on public.tg_notifications';
    end if;
end $$;
notify pgrst, 'reload schema';
