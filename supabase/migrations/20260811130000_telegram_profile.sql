-- Human-friendly Telegram identity for the linked installation only.
-- The table remains inaccessible to anon/authenticated clients; Edge Function
-- service-role code is the sole reader and writer.
alter table public.telegram_links
    add column if not exists telegram_username text,
    add column if not exists telegram_display_name text;
