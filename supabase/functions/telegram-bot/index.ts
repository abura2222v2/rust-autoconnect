import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.39.3'

const TELEGRAM_BOT_TOKEN = Deno.env.get('TELEGRAM_BOT_TOKEN') || ""
const SUPABASE_URL = Deno.env.get('SUPABASE_URL') || ""
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || ""

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

serve(async (req) => {
  try {
    const url = new URL(req.url)
    
    // 1. Handle incoming messages from Telegram (Webhook)
    if (url.pathname === '/telegram-bot/webhook') {
      const body = await req.json()
      if (body.message && body.message.text) {
        const text = body.message.text.trim()
        const chatId = body.message.chat.id
        
        // If the user sends a 4-digit code (e.g. 4815)
        if (/^\d{4}$/.test(text)) {
          // Link this chatId to the client ID in Supabase
          const { error } = await supabase
            .from('telegram_links')
            .update({ chat_id: chatId })
            .eq('link_code', text)
            
          let replyText = "Success! Your Telegram is now linked to Rust AutoConnect."
          if (error) replyText = "Invalid or expired code. Please try again from the app."
          
          await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: chatId, text: replyText })
          })
        }
      }
      return new Response("OK", { status: 200 })
    }
    
    // 2. Handle DB Triggers (when app inserts a notification)
    if (url.pathname === '/telegram-bot/notify') {
      const payload = await req.json()
      // Expected payload from Database Webhook on INSERT to tg_notifications
      const record = payload.record
      if (record && record.chat_id && record.message) {
        await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: record.chat_id, text: record.message })
        })
      }
      return new Response("Notification Sent", { status: 200 })
    }

    return new Response("Not Found", { status: 404 })
  } catch (err) {
    return new Response(String(err), { status: 500 })
  }
})
