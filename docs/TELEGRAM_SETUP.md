# Telegram setup

The desktop app contains no Telegram bot token and never writes directly to
Supabase tables.

1. Apply `supabase/migrations/20260811120000_secure_telegram_bot.sql` through
   the Supabase SQL editor or your migration workflow.
2. Deploy `supabase/functions/telegram-bot`.
3. In Supabase Edge Function Secrets, set `TELEGRAM_BOT_TOKEN` and a new random
   `TELEGRAM_WEBHOOK_SECRET`. Do not put either value in source code or the
   desktop application's public configuration.
4. Configure Telegram's webhook to the deployed
   `/functions/v1/telegram-bot/webhook` URL and use the same secret as
   `secret_token`.
5. In the app, select **Link Telegram Bot**, then send the displayed eight
   character code to the bot within ten minutes.

The bot accepts `/notifications`, `/on EVENT`, `/off EVENT`, `/all`, `/none`,
and `/queue NUMBER`. Events are `ready`, `queue`, `connected`, `disconnect`,
`reconnect`, `wipe`, and `swarm`.
