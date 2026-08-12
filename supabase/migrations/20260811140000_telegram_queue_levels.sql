-- Queue alerts are emitted at fixed low-noise levels per connection session.
alter table public.telegram_queue_state
    add column if not exists queue_session_id text,
    add column if not exists sent_levels jsonb not null default '[]'::jsonb;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'telegram_queue_state_session_id_check'
          and conrelid = 'public.telegram_queue_state'::regclass
    ) then
        alter table public.telegram_queue_state
            add constraint telegram_queue_state_session_id_check
            check (queue_session_id is null or queue_session_id ~ '^[0-9a-f]{32}$') not valid;
    end if;
end;
$$;

notify pgrst, 'reload schema';
