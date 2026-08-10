-- Table to link user client IDs to their Telegram Chat ID
CREATE TABLE telegram_links (
    client_id UUID PRIMARY KEY,
    link_code TEXT UNIQUE NOT NULL,
    chat_id BIGINT UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table for pending notifications
CREATE TABLE tg_notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES telegram_links(client_id) ON DELETE CASCADE,
    chat_id BIGINT,
    message TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- RLS Policies
ALTER TABLE telegram_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE tg_notifications ENABLE ROW LEVEL SECURITY;

-- Allow users to insert/update their own links if they know their client_id
CREATE POLICY "Allow public insert to telegram_links" ON telegram_links
    FOR INSERT WITH CHECK (true);
    
CREATE POLICY "Allow public update to telegram_links" ON telegram_links
    FOR UPDATE USING (true);

-- Allow public inserts for notifications
CREATE POLICY "Allow public insert to tg_notifications" ON tg_notifications
    FOR INSERT WITH CHECK (true);

-- Create a Database Webhook to trigger Edge Function when a new notification is inserted
-- Note: Replace 'https://<PROJECT_REF>.supabase.co/functions/v1/telegram-bot/notify' with actual URL
CREATE TRIGGER tg_notification_trigger
AFTER INSERT ON tg_notifications
FOR EACH ROW
EXECUTE FUNCTION supabase_functions.http_request(
  'http://localhost:54321/functions/v1/telegram-bot/notify',
  'POST',
  '{"Content-Type": "application/json"}',
  '{}',
  '1000'
);
