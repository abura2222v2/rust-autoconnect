/**
 * Rust AutoConnect - Modals & Overlays Controller
 */

class ModalManager {
  constructor() {
    this.serverModal = document.getElementById('server-card-modal');
    this.telegramModal = document.getElementById('telegram-link-modal');

    this.initEvents();
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
      descElem.textContent = server.description || (window.STRINGS || {}).modal_desc_default
        || 'A classic Rust server. Weekly wipe on Fridays. Active community, a good balance between survival and PvP. Good luck and have fun!';
    }

    // Community Link Handlers
    const discordUrl = server.discord || 'https://discord.gg';
    const websiteUrl = server.website || 'https://rustafied.com';
    const rulesUrl = server.rules || 'https://rustafied.com/rules';
    const mapUrl = server.rustmaps_url || 'https://rustmaps.com';

    if (discordBtn) discordBtn.onclick = () => window.open(discordUrl, '_blank');
    if (websiteBtn) websiteBtn.onclick = () => window.open(websiteUrl, '_blank');
    if (rulesBtn) rulesBtn.onclick = () => window.open(rulesUrl, '_blank');
    if (mapBtn) mapBtn.onclick = () => window.open(mapUrl, '_blank');

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
