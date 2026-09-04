/**
 * Rust AutoConnect - Modals & Overlays Controller
 */

// Real server descriptions almost always open with a `![name](url)` banner
// image line meant for a different renderer than this plain-text panel - it
// never displays as a picture here, only as literal markdown noise, and it
// duplicates the server name already shown as the modal title.
function cleanServerDescription(text) {
  if (!text) return text;
  return text
    .replace(/^!\[[^\]]*\]\([^)]*\)\s*/, '')
    .replace(/\r\n/g, '\n')
    // Some operators type a literal backslash-t/backslash-n as a visual
    // bullet marker for a different renderer (e.g. Discord); left as-is here
    // it prints as the two raw characters instead of any spacing.
    .replace(/\\t/g, ' ')
    .replace(/\\n/g, '\n')
    .trim();
}

class ModalManager {
  constructor() {
    this.serverModal = document.getElementById('server-card-modal');
    this.telegramModal = document.getElementById('telegram-link-modal');
    this.serverWipeRow = document.getElementById('m-server-wipe-countdown');
    this.serverWipeLabel = this.serverWipeRow ? this.serverWipeRow.querySelector('span') : null;
    this.serverWipeAt = null;
    setInterval(() => this.tickServerWipe(), 1000);

    this.initEvents();
  }

  // This server's own posted wipe schedule, distinct from the official
  // force-wipe countdown (app.js) which is the same for every server.
  tickServerWipe() {
    if (!this.serverWipeRow || !this.serverWipeLabel) return;
    if (!this.serverWipeAt) {
      this.serverWipeRow.style.display = 'none';
      return;
    }
    this.serverWipeRow.style.display = '';
    const s = window.STRINGS || {};
    const remainingMs = this.serverWipeAt.getTime() - Date.now();
    if (remainingMs <= 0) {
      this.serverWipeLabel.textContent = s.server_wipe_now || 'Server wipe: expected any time now';
      return;
    }
    const totalSeconds = Math.floor(remainingMs / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const parts = [];
    if (days > 0) parts.push((s.wipe_days_suffix || '{days}d').replace('{days}', days));
    parts.push((s.wipe_hours_suffix || '{hours}h').replace('{hours}', hours));
    parts.push((s.wipe_minutes_suffix || '{minutes}m').replace('{minutes}', minutes));
    this.serverWipeLabel.textContent = (s.server_wipe_countdown_label || "Server's own wipe (estimated): {parts}")
      .replace('{parts}', parts.join(' '));
  }

  initEvents() {
    // Backdrop click dismisses modal
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
          this.closeAll();
        }
      });
    });

    // Close button dismisses modal
    document.querySelectorAll('.modal-close-btn').forEach(btn => {
      btn.addEventListener('click', () => this.closeAll());
    });

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.closeAll();
      }
    });
  }

  closeAll() {
    if (this.serverModal) this.serverModal.classList.remove('open');
    if (this.telegramModal) this.telegramModal.classList.remove('open');
  }

  // ==========================================
  // SERVER CARD MODAL
  // ==========================================
  showServerCard(server) {
    if (!this.serverModal) return;

    const titleElem = document.getElementById('m-server-title');
    const ipElem = document.getElementById('m-server-ip');
    const playersVal = document.getElementById('m-players-val');
    const mapVal = document.getElementById('m-map-val');
    const sizeVal = document.getElementById('m-size-val');
    const descElem = document.getElementById('m-server-desc');
    const discordBtn = document.getElementById('m-btn-discord');
    const websiteBtn = document.getElementById('m-btn-website');
    const rulesBtn = document.getElementById('m-btn-rules');
    const mapBtn = document.getElementById('m-btn-map');
    const connectBtn = document.getElementById('m-btn-connect');
    const copyBtn = document.getElementById('m-btn-copy-ip');

    if (titleElem) titleElem.textContent = server.name || server.ip;
    if (ipElem) ipElem.textContent = server.ip;
    if (playersVal) playersVal.textContent = `${server.players || 97}/${server.max_players || 150}`;
    if (mapVal) mapVal.textContent = server.map_name || 'Procedural Map';
    if (sizeVal) {
      const raw = server.map_size || 4000;
      sizeVal.textContent = (typeof raw === 'number' && raw > 100) ? `${(raw / 1000).toFixed(1)} km` : raw;
    }
    if (descElem) {
      descElem.textContent = cleanServerDescription(server.description) || (window.STRINGS || {}).modal_desc_default
        || 'A classic Rust server. Weekly wipe on Fridays. Active community, a good balance between survival and PvP. Good luck and have fun!';
    }

    this.serverWipeAt = server.wipe_at ? new Date(server.wipe_at * 1000) : null;
    this.tickServerWipe();

    // Community links are real, per-server data (or empty) - never a
    // guessed placeholder that would point at an unrelated server's page.
    // Hide a button entirely when we genuinely don't have that link.
    // .btn-link/.btn-icon both set display:flex at the same specificity as
    // the [hidden] user-agent rule, so toggling the `hidden` property alone
    // would silently lose that tie - set the inline style directly instead.
    const setLinkButton = (btn, url) => {
      if (!btn) return;
      btn.style.display = url ? '' : 'none';
      btn.onclick = url ? () => window.open(url, '_blank') : null;
    };
    setLinkButton(discordBtn, server.discord);
    setLinkButton(websiteBtn, server.website);
    setLinkButton(rulesBtn, server.rules);
    setLinkButton(mapBtn, server.rustmaps_url);

    if (copyBtn) {
      copyBtn.onclick = () => {
        navigator.clipboard.writeText(server.ip);
        copyBtn.style.color = 'var(--success)';
        setTimeout(() => { copyBtn.style.color = ''; }, 1200);
      };
    }

    if (connectBtn) {
      connectBtn.onclick = () => {
        this.closeAll();
        window.api.connect(server.ip);
      };
    }

    this.serverModal.classList.add('open');
  }

  // ==========================================
  // TELEGRAM PAIRING MODAL
  // ==========================================
  showTelegramModal(code, isLinked = false, displayName = '') {
    if (!this.telegramModal) return;

    const codeBox = document.getElementById('tg-pairing-code');
    const copyBtn = document.getElementById('tg-copy-btn');
    const statusText = document.getElementById('tg-modal-status');
    const unlinkBtn = document.getElementById('tg-unlink-btn');

    const s = window.STRINGS || {};

    if (codeBox) {
      if (isLinked) {
        const formattedName = displayName || s.tg_badge_connected || 'Connected';
        codeBox.textContent = formattedName;
        codeBox.style.color = 'var(--success)';
        codeBox.style.fontSize = '20px';
      } else {
        codeBox.textContent = code || '------';
        codeBox.style.color = 'var(--accent)';
        codeBox.style.fontSize = '24px';
      }
    }

    if (statusText) {
      statusText.textContent = isLinked
        ? (s.tg_status_linked_modal || 'Linked to Telegram account: {display_name}').replace('{display_name}', displayName || s.tg_user_fallback || 'User')
        : (s.tg_modal_status_default || 'Send this code to the Telegram bot to link your account:');
    }

    if (unlinkBtn) {
      unlinkBtn.style.display = isLinked ? 'inline-flex' : 'none';
      unlinkBtn.onclick = async () => {
        await window.api.unlinkTelegram();
        this.closeAll();
      };
    }

    if (copyBtn) {
      copyBtn.style.display = isLinked ? 'none' : 'inline-flex';
      copyBtn.onclick = () => {
        if (code) {
          navigator.clipboard.writeText(code);
          copyBtn.textContent = s.tg_copy_done || 'Copied!';
          setTimeout(() => { copyBtn.textContent = s.tg_copy_btn || 'Copy code'; }, 1400);
        }
      };
    }

    this.telegramModal.classList.add('open');
  }
}

window.modalManager = new ModalManager();
