import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.3";

const BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
const WEBHOOK_SECRET = Deno.env.get("TELEGRAM_WEBHOOK_SECRET") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const db = createClient(SUPABASE_URL, SERVICE_ROLE);
const headers = {
  "content-type": "application/json",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, OPTIONS",
  "access-control-allow-headers": "apikey, Authorization, Content-Type, X-Telegram-Bot-Api-Secret-Token",
};
const events = new Set(["ready", "queue", "connected", "disconnect", "reconnect", "wipe", "swarm"]);
const locales = new Set(["EN", "RU", "UK", "DE", "ES", "FR", "ZH"]);
type Locale = "EN" | "RU" | "UK" | "DE" | "ES" | "FR" | "ZH";

const words: Record<Locale, Record<string, string>> = {
  EN: { menu_notifications: "🔔 Notifications", menu_all: "✅ Enable all", menu_none: "🔕 Disable all", menu_help: "❔ Help", linked: "Telegram is linked. Use the buttons below to manage alerts.", pairing: "Send the eight-character code from Rust AutoConnect first.", invalid: "Invalid or expired code. Generate a new code in Rust AutoConnect.", settings: "Notification settings saved.", language: "Bot language updated to English.", help: "Use the menu below, or commands: /notifications, /on EVENT, /off EVENT, /all, /none, /queue NUMBER.", queue_error: "Queue threshold must be a number from 1 to 999." },
  RU: { menu_notifications: "🔔 Уведомления", menu_all: "✅ Включить все", menu_none: "🔕 Выключить все", menu_help: "❔ Помощь", linked: "Telegram привязан. Используйте кнопки ниже, чтобы настроить уведомления.", pairing: "Сначала отправьте восьмизначный код из Rust AutoConnect.", invalid: "Код неверный или истёк. Создайте новый код в Rust AutoConnect.", settings: "Настройки уведомлений сохранены.", language: "Язык бота изменён на русский.", help: "Используйте меню ниже или команды: /notifications, /on EVENT, /off EVENT, /all, /none, /queue ЧИСЛО.", queue_error: "Порог очереди должен быть числом от 1 до 999." },
  UK: { menu_notifications: "🔔 Сповіщення", menu_all: "✅ Увімкнути все", menu_none: "🔕 Вимкнути все", menu_help: "❔ Допомога", linked: "Telegram прив’язано. Використовуйте кнопки нижче для налаштування сповіщень.", pairing: "Спочатку надішліть восьмизначний код з Rust AutoConnect.", invalid: "Код неправильний або прострочений. Створіть новий код у Rust AutoConnect.", settings: "Налаштування сповіщень збережено.", language: "Мову бота змінено на українську.", help: "Використовуйте меню нижче або команди: /notifications, /on EVENT, /off EVENT, /all, /none, /queue ЧИСЛО.", queue_error: "Поріг черги має бути числом від 1 до 999." },
  DE: { menu_notifications: "🔔 Benachrichtigungen", menu_all: "✅ Alle aktivieren", menu_none: "🔕 Alle deaktivieren", menu_help: "❔ Hilfe", linked: "Telegram ist verbunden. Verwalte Benachrichtigungen über die Tasten unten.", pairing: "Sende zuerst den achtstelligen Code aus Rust AutoConnect.", invalid: "Der Code ist ungültig oder abgelaufen. Erzeuge einen neuen Code in Rust AutoConnect.", settings: "Benachrichtigungseinstellungen gespeichert.", language: "Botsprache wurde auf Deutsch geändert.", help: "Nutze das Menü oder: /notifications, /on EVENT, /off EVENT, /all, /none, /queue ZAHL.", queue_error: "Der Warteschlangenwert muss zwischen 1 und 999 liegen." },
  ES: { menu_notifications: "🔔 Notificaciones", menu_all: "✅ Activar todo", menu_none: "🔕 Desactivar todo", menu_help: "❔ Ayuda", linked: "Telegram está vinculado. Usa los botones para configurar alertas.", pairing: "Primero envía el código de ocho caracteres de Rust AutoConnect.", invalid: "El código no es válido o ha caducado. Genera uno nuevo en Rust AutoConnect.", settings: "Ajustes de notificaciones guardados.", language: "El idioma del bot se cambió a español.", help: "Usa el menú o: /notifications, /on EVENT, /off EVENT, /all, /none, /queue NÚMERO.", queue_error: "El límite de cola debe ser un número de 1 a 999." },
  FR: { menu_notifications: "🔔 Notifications", menu_all: "✅ Tout activer", menu_none: "🔕 Tout désactiver", menu_help: "❔ Aide", linked: "Telegram est lié. Utilisez les boutons pour gérer les alertes.", pairing: "Envoyez d’abord le code à huit caractères de Rust AutoConnect.", invalid: "Le code est invalide ou expiré. Générez-en un nouveau dans Rust AutoConnect.", settings: "Préférences de notification enregistrées.", language: "La langue du bot est maintenant le français.", help: "Utilisez le menu ou : /notifications, /on EVENT, /off EVENT, /all, /none, /queue NOMBRE.", queue_error: "Le seuil de file doit être un nombre de 1 à 999." },
  ZH: { menu_notifications: "🔔 通知", menu_all: "✅ 全部开启", menu_none: "🔕 全部关闭", menu_help: "❔ 帮助", linked: "Telegram 已绑定。请使用下方按钮管理通知。", pairing: "请先发送 Rust AutoConnect 中的八位配对码。", invalid: "配对码无效或已过期。请在 Rust AutoConnect 中生成新配对码。", settings: "通知设置已保存。", language: "机器人语言已切换为中文。", help: "使用下方菜单，或命令：/notifications、/on EVENT、/off EVENT、/all、/none、/queue 数字。", queue_error: "队列阈值必须是 1 到 999 的数字。" },
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers });
// Supabase can forward either the complete public path or the path after the
// function slug.  Accept both forms so Telegram webhook updates never fall
// through to a misleading 404 response.
const routeIs = (path: string, route: string) =>
  path === `/${route}` || path.endsWith(`/telegram-bot/${route}`);
const validClient = (value: unknown) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(value);
const validCode = (value: unknown) => typeof value === "string" && /^[A-Z0-9]{8}$/.test(value);

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function locale(value: unknown): Locale {
  return typeof value === "string" && locales.has(value.toUpperCase()) ? value.toUpperCase() as Locale : "EN";
}

function defaultPreferences(selectedLocale: Locale = "EN"): Record<string, boolean | number | string | number[]> {
  return { ready: true, queue: true, connected: true, disconnect: true, reconnect: true, wipe: true, swarm: true, queue_levels: [90, 60, 30, 5], locale: selectedLocale };
}

function keyboard(selectedLocale: Locale): Record<string, unknown> {
  const text = words[selectedLocale];
  return { keyboard: [[{ text: text.menu_notifications }], [{ text: text.menu_all }, { text: text.menu_none }], [{ text: text.menu_help }]], resize_keyboard: true };
}

async function send(chatId: number, text: string, selectedLocale?: Locale): Promise<boolean> {
  if (!BOT_TOKEN) return false;
  const payload: Record<string, unknown> = { chat_id: chatId, text };
  if (selectedLocale) payload.reply_markup = keyboard(selectedLocale);
  const response = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  return response.ok;
}

function notificationText(event: string, server: string, details: Record<string, unknown>, selectedLocale: Locale): string {
  const prefix: Record<Locale, Record<string, string>> = {
    EN: { queue: "Queue update", ready: "Ready to join", connected: "Connected", disconnect: "Disconnected", reconnect: "Auto-reconnect started", wipe: "Wipe signal received", swarm: "Swarm activity" },
    RU: { queue: "Очередь", ready: "Можно заходить", connected: "Подключено", disconnect: "Отключено", reconnect: "Автоподключение запущено", wipe: "Сигнал вайпа", swarm: "Активность Swarm" },
    UK: { queue: "Черга", ready: "Можна заходити", connected: "Підключено", disconnect: "Відключено", reconnect: "Автопідключення запущено", wipe: "Сигнал вайпа", swarm: "Активність Swarm" },
    DE: { queue: "Warteschlange", ready: "Bereit zum Beitreten", connected: "Verbunden", disconnect: "Getrennt", reconnect: "Auto-Wiederverbindung gestartet", wipe: "Wipe-Signal", swarm: "Swarm-Aktivität" },
    ES: { queue: "Cola", ready: "Listo para entrar", connected: "Conectado", disconnect: "Desconectado", reconnect: "Reconexión automática iniciada", wipe: "Señal de wipe", swarm: "Actividad Swarm" },
    FR: { queue: "File d’attente", ready: "Prêt à rejoindre", connected: "Connecté", disconnect: "Déconnecté", reconnect: "Reconnexion automatique lancée", wipe: "Signal de wipe", swarm: "Activité Swarm" },
    ZH: { queue: "队列更新", ready: "可以进入", connected: "已连接", disconnect: "已断开", reconnect: "已开始自动重连", wipe: "收到重置信号", swarm: "Swarm 活动" },
  };
  const title = prefix[selectedLocale][event] ?? prefix.EN.swarm;
  if (event === "queue") return `${title}: ${details.position ?? "?"} — ${server}.`;
  if (event === "disconnect") return `${title}: ${server} — ${String(details.reason ?? "?").slice(0, 160)}.`;
  return `${title}: ${server}.`;
}

async function handleCommand(chatId: number, text: string): Promise<void> {
  const rawCommand = text.trim().toLowerCase();
  const { data: link } = await db.from("telegram_links").select("client_id,preferences").eq("chat_id", chatId).maybeSingle();
  if (!link) {
    await send(chatId, words.EN.pairing);
    return;
  }
  const selectedLocale = locale(link.preferences?.locale);
  const labels = words[selectedLocale];
  const menuCommands: Record<string, string> = {
    [labels.menu_notifications.toLowerCase()]: "/notifications",
    [labels.menu_all.toLowerCase()]: "/all",
    [labels.menu_none.toLowerCase()]: "/none",
    [labels.menu_help.toLowerCase()]: "/help",
  };
  const command = menuCommands[rawCommand] ?? rawCommand;
  const preferences = { ...defaultPreferences(selectedLocale), ...(link.preferences ?? {}) };
  // Older paired clients may still send /queue NUMBER.  Queue levels are now
  // fixed per connection, so do not present a setting that is no longer used.
  const help = labels.help.replace(/,?\s*\/queue\s+\S+[.]?/, "");
  if (command === "/notifications") {
    const enabled = [...events].filter((event) => preferences[event] !== false).join(", ");
    await send(chatId, `${labels.menu_notifications}: ${enabled}.\n${help}`, selectedLocale);
    return;
  }
  if (command === "/help" || command === "/start") {
    await send(chatId, help, selectedLocale);
    return;
  }
  if (command.startsWith("/queue")) {
    await send(chatId, "Queue alerts use the fixed levels: 90, 60, 30, and 5.", selectedLocale);
    return;
  }
  if (command === "/all" || command === "/none") {
    for (const event of events) preferences[event] = command === "/all";
  } else {
    const match = /^\/(on|off)\s+(ready|queue|connected|disconnect|reconnect|wipe|swarm)$/.exec(command);
    if (!match) {
      await send(chatId, help, selectedLocale); return;
    }
    preferences[match[2]] = match[1] === "on";
  }
  await db.from("telegram_links").update({ preferences }).eq("client_id", link.client_id);
  await send(chatId, labels.settings, selectedLocale);
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers });
  if (request.method !== "POST" || !BOT_TOKEN || !SUPABASE_URL || !SERVICE_ROLE) return json({ error: "not configured" }, 503);
  const path = new URL(request.url).pathname;
  const body = await request.json().catch(() => null);

  if (routeIs(path, "webhook")) {
    if (!WEBHOOK_SECRET || request.headers.get("x-telegram-bot-api-secret-token") !== WEBHOOK_SECRET) return json({ error: "unauthorized" }, 401);
    const text = body?.message?.text;
    const chatId = body?.message?.chat?.id;
    if (typeof text !== "string" || !Number.isSafeInteger(chatId)) return json({ accepted: true });
    const code = text.trim().toUpperCase();
    if (validCode(code)) {
      const { data: link } = await db.from("telegram_links").select("client_id,preferences").eq("link_code", code).gt("link_expires_at", new Date().toISOString()).maybeSingle();
      const selectedLocale = locale(link?.preferences?.locale);
      if (!link) await send(chatId, words.EN.invalid);
      else {
        const username = typeof body?.message?.from?.username === "string" ? body.message.from.username.slice(0, 64) : null;
        const firstName = typeof body?.message?.from?.first_name === "string" ? body.message.from.first_name.slice(0, 80) : null;
        const displayName = username ? `@${username}` : firstName;
        await db.from("telegram_links").update({
          chat_id: chatId, link_code: null, link_expires_at: null, preferences: defaultPreferences(selectedLocale),
          telegram_username: username, telegram_display_name: displayName,
        }).eq("client_id", link.client_id);
        await send(chatId, words[selectedLocale].linked, selectedLocale);
      }
    } else await handleCommand(chatId, text);
    return json({ accepted: true });
  }

  if (routeIs(path, "link")) {
    if (!validClient(body?.client_id) || !validCode(body?.code)) return json({ error: "invalid link request" }, 400);
    const selectedLocale = locale(body?.locale);
    const notificationToken = crypto.randomUUID().replaceAll("-", "") + crypto.randomUUID().replaceAll("-", "");
    const expires = new Date(Date.now() + 10 * 60_000).toISOString();
    const { error } = await db.from("telegram_links").upsert({
      client_id: body.client_id, link_code: body.code, link_expires_at: expires,
      notification_token_hash: await sha256(notificationToken), chat_id: null, preferences: defaultPreferences(selectedLocale),
    }, { onConflict: "client_id" });
    return error ? json({ error: "service unavailable" }, 503) : json({ accepted: true, notification_token: notificationToken });
  }

  if (routeIs(path, "notify")) {
    if (!validClient(body?.client_id) || typeof body?.notification_token !== "string" || !events.has(body?.event) || typeof body?.server !== "string") return json({ error: "invalid notification" }, 400);
    const { data: link } = await db.from("telegram_links").select("chat_id,notification_token_hash,preferences").eq("client_id", body.client_id).maybeSingle();
    if (!link || !link.chat_id || link.notification_token_hash !== await sha256(body.notification_token)) return json({ accepted: false }, 403);
    const selectedLocale = locale(link.preferences?.locale);
    const preferences = { ...defaultPreferences(selectedLocale), ...(link.preferences ?? {}) };
    if (preferences[body.event] === false) return json({ accepted: true });
    const details = body.details && typeof body.details === "object" ? body.details as Record<string, unknown> : {};
    if (body.event === "queue") {
      const position = Number(details.position);
      const level = Number(details.level);
      const queueSessionId = typeof details.queue_session_id === "string" ? details.queue_session_id : "";
      if (!Number.isFinite(position) || ![90, 60, 30, 5].includes(level) || !/^[a-f0-9]{32}$/i.test(queueSessionId)) return json({ accepted: true });
      const { data: prior } = await db.from("telegram_queue_state").select("queue_session_id,sent_levels").eq("client_id", body.client_id).eq("server", body.server).maybeSingle();
      const sent = prior?.queue_session_id === queueSessionId && Array.isArray(prior.sent_levels)
        ? prior.sent_levels.filter((value: unknown) => Number.isInteger(value)) : [];
      if (sent.includes(level)) return json({ accepted: true });
      sent.push(level);
      const { error: queueError } = await db.from("telegram_queue_state").upsert({
        client_id: body.client_id, server: body.server, last_position: position,
        queue_session_id: queueSessionId, sent_levels: sent, updated_at: new Date().toISOString(),
      }, { onConflict: "client_id,server" });
      if (queueError) return json({ error: "service unavailable" }, 503);
    }
    const sent = await send(link.chat_id, notificationText(body.event, body.server.slice(0, 253), details, selectedLocale));
    return json({ accepted: sent }, sent ? 202 : 503);
  }

  if (routeIs(path, "status")) {
    if (!validClient(body?.client_id) || typeof body?.notification_token !== "string") return json({ error: "invalid status request" }, 400);
    const { data: link } = await db.from("telegram_links").select("chat_id,notification_token_hash,telegram_display_name").eq("client_id", body.client_id).maybeSingle();
    if (!link || link.notification_token_hash !== await sha256(body.notification_token)) return json({ accepted: false }, 403);
    return json({ linked: Boolean(link.chat_id), display_name: link.telegram_display_name ?? null });
  }

  if (routeIs(path, "unlink")) {
    if (!validClient(body?.client_id) || typeof body?.notification_token !== "string") return json({ error: "invalid unlink request" }, 400);
    const { data: link } = await db.from("telegram_links").select("notification_token_hash").eq("client_id", body.client_id).maybeSingle();
    if (!link || link.notification_token_hash !== await sha256(body.notification_token)) return json({ accepted: false }, 403);
    const { error } = await db.from("telegram_links").update({
      chat_id: null, link_code: null, link_expires_at: null, notification_token_hash: null,
      telegram_username: null, telegram_display_name: null,
    }).eq("client_id", body.client_id);
    return error ? json({ error: "service unavailable" }, 503) : json({ accepted: true });
  }

  if (routeIs(path, "locale")) {
    if (!validClient(body?.client_id) || typeof body?.notification_token !== "string") return json({ error: "invalid locale request" }, 400);
    const { data: link } = await db.from("telegram_links").select("chat_id,notification_token_hash,preferences").eq("client_id", body.client_id).maybeSingle();
    if (!link || link.notification_token_hash !== await sha256(body.notification_token)) return json({ accepted: false }, 403);
    const selectedLocale = locale(body?.locale);
    const preferences = { ...defaultPreferences(selectedLocale), ...(link.preferences ?? {}), locale: selectedLocale };
    const { error } = await db.from("telegram_links").update({ preferences }).eq("client_id", body.client_id);
    if (error) return json({ error: "service unavailable" }, 503);
    if (link.chat_id) await send(link.chat_id, words[selectedLocale].language, selectedLocale);
    return json({ accepted: true });
  }
  return json({ error: "not found" }, 404);
});
