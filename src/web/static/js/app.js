/**
 * Rust AutoConnect - Main Reactive Application Controller
 */

function showToast(message) {
  const container = document.getElementById('toast-container');
  if (!container || !message) return;
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast-visible'));
  setTimeout(() => {
    el.classList.remove('toast-visible');
    setTimeout(() => el.remove(), 250);
  }, 2500);
}
window.showToast = showToast;

class AppController {
  constructor() {
    this.currentTab = 'servers';
    this.state = null;
    window.STRINGS = {};

    this.initElements();
    this.initNavigation();
    this.initToolbar();
    this.initBenchmark();
    this.initSettings();
    this.initStatusBar();
    this.initWebSocketListeners();
  }

  initElements() {
    this.ipInput = document.getElementById('ip-input');
    this.connectBtn = document.getElementById('btn-connect-main');
    this.searchInput = document.getElementById('search-input');
    this.filterBtn = document.getElementById('btn-filter-toggle');
    this.navItems = document.querySelectorAll('.nav-item');
    this.viewSections = document.querySelectorAll('.view-section');

    // Bottom Status Elements
    this.rustDot = document.getElementById('rust-status-dot');
    this.rustLabel = document.getElementById('rust-status-label');
    this.armedDot = document.getElementById('armed-status-dot');
    this.armedLabel = document.getElementById('armed-status-label');
    this.disarmBtn = document.getElementById('btn-disarm-footer');

    // Wipe Countdown (shown in the server card modal, next to "Открыть карту")
    this.wipeCountdownLabel = document.querySelector('#m-wipe-countdown span');
    this.nextForceWipeAt = null;
    setInterval(() => this.tickWipeCountdown(), 1000);

    // The countdown is a Smart Mode feature. Smart Mode isn't reachable yet,
    // so clicking it explains why instead of doing nothing silently.
    const wipeCountdownEl = document.getElementById('m-wipe-countdown');
    if (wipeCountdownEl) {
      wipeCountdownEl.addEventListener('click', () => {
        const smartModeOn = !!(this.state && this.state.settings && this.state.settings.smart_mode);
        if (smartModeOn) return;
        const strings = window.STRINGS || {};
        showToast(strings.smart_mode_unavailable || 'Функция недоступна в обычном режиме');
      });
    }
  }

  tickWipeCountdown() {
    if (!this.wipeCountdownLabel || !this.nextForceWipeAt) return;
    const s = window.STRINGS || {};
    const remainingMs = this.nextForceWipeAt.getTime() - Date.now();
    if (remainingMs <= 0) {
      this.wipeCountdownLabel.textContent = s.wipe_now || 'Wipe: happening now';
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
    this.wipeCountdownLabel.textContent = (s.wipe_countdown_label || 'Wipe in: {parts}').replace('{parts}', parts.join(' '));
  }

  initNavigation() {
    this.navItems.forEach(item => {
      item.addEventListener('click', () => {
        const tab = item.dataset.tab;
        this.showTab(tab);
      });
    });
  }

  showTab(tab) {
    this.currentTab = tab;

    this.navItems.forEach(n => {
      if (n.dataset.tab === tab) n.classList.add('active');
      else n.classList.remove('active');
    });

    this.viewSections.forEach(v => {
      if (v.id === `view-${tab}`) v.classList.add('active');
      else v.classList.remove('active');
    });

    if (tab === 'bench') {
      this.refreshBenchmarkData();
    }
  }

  // ==========================================
  // TOOLBAR CONTROLS
  // ==========================================
  initToolbar() {
    if (this.connectBtn && this.ipInput) {
      const handleConnect = () => {
        if (this.isConnecting) {
          window.api.stopConnecting();
          return;
        }
        const val = this.ipInput.value.trim();
        if (val) {
          window.api.connect(val);
        }
      };

      this.connectBtn.addEventListener('click', handleConnect);
      this.ipInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleConnect();
      });
    }

    if (this.searchInput) {
      this.searchInput.addEventListener('input', (e) => {
        window.tableManager.setSearch(e.target.value);
      });
    }

    if (this.filterBtn) {
      let isFav = false;
      this.filterBtn.addEventListener('click', () => {
        isFav = !isFav;
        this.filterBtn.classList.toggle('active', isFav);
        window.tableManager.setFilter(isFav ? 'favorites' : 'all');
      });
    }
  }

  // ==========================================
  // HARDWARE BENCHMARK & RANKING
  // ==========================================
  initBenchmark() {
    const runBtn = document.getElementById('btn-run-benchmark');
    if (runBtn) {
      runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        runBtn.textContent = (window.STRINGS || {}).bench_testing || 'Testing...';
        await window.api.runBenchmark();
      });
    }

    window.api.on('benchmark_status', (data) => {
      const runBtn = document.getElementById('btn-run-benchmark');
      const progressElem = document.getElementById('bench-progress-bar');
      if (data.status === 'running') {
        if (progressElem) progressElem.style.width = `${data.progress || 30}%`;
      } else if (data.status === 'completed') {
        if (progressElem) progressElem.style.width = '100%';
        if (runBtn) {
          runBtn.disabled = false;
          runBtn.textContent = (window.STRINGS || {}).btn_run_benchmark || 'Run test';
        }
        this.refreshBenchmarkData();
      }
    });
  }

  async refreshBenchmarkData() {
    const info = await window.api.getBenchmarkInfo();
    const s = window.STRINGS || {};
    const cpuElem = document.getElementById('spec-cpu');
    const ramElem = document.getElementById('spec-ram');
    const diskElem = document.getElementById('spec-disk');
    const countElem = document.getElementById('bench-run-count');

    if (cpuElem) cpuElem.textContent = info.cpu || 'Unknown CPU';
    if (ramElem) ramElem.textContent = info.ram || 'Unknown RAM';
    if (diskElem) diskElem.textContent = info.disk || 'Unknown Storage';
    if (countElem) countElem.textContent = (s.bench_run_count || 'Local runs: {count}').replace('{count}', info.run_count || 0);

    const leaderboard = await window.api.getLeaderboard();
    const rankTableBody = document.getElementById('leaderboard-tbody');
    if (rankTableBody && Array.isArray(leaderboard)) {
      rankTableBody.innerHTML = leaderboard.map((row, idx) => `
        <tr>
          <td><span class="rank-badge">#${idx + 1}</span></td>
          <td>
            <div style="font-weight:700;">${row.cpu || 'Unknown'}</div>
            <div style="font-size:11px; color:var(--muted);">${row.storage || 'Storage'}</div>
          </td>
          <td style="color:var(--accent); font-weight:700; text-align:right;">${row.total_time ? row.total_time.toFixed(2) + 's' : '-'}</td>
          <td style="color:var(--muted); text-align:right;">${row.run_count || 1}</td>
        </tr>
      `).join('');
    }
  }

  // ==========================================
  // SETTINGS PANEL
  // ==========================================
  initSettings() {
    const langSelect = document.getElementById('select-lang');
    if (langSelect) {
      langSelect.addEventListener('change', (e) => {
        window.api.setLanguage(e.target.value);
      });
    }

    const trayToggle = document.getElementById('chk-tray');
    if (trayToggle) {
      trayToggle.addEventListener('change', (e) => {
        window.api.updateSetting('minimize_to_tray', e.target.checked);
      });
    }

    const swarmToggle = document.getElementById('chk-swarm');
    if (swarmToggle) {
      swarmToggle.addEventListener('change', (e) => {
        window.api.updateSetting('swarm_enabled', e.target.checked);
      });
    }

    const shareToggle = document.getElementById('chk-share-servers');
    if (shareToggle) {
      shareToggle.addEventListener('change', (e) => {
        window.api.updateSetting('share_saved_servers', e.target.checked);
      });
    }

    const smartModeToggle = document.getElementById('chk-smart-mode');
    if (smartModeToggle) {
      smartModeToggle.addEventListener('change', async (e) => {
        const wantsOn = e.target.checked;
        if (!wantsOn) {
          window.api.updateSetting('smart_mode', false);
          return;
        }
        // Smart mode isn't ready yet: reject the toggle and snap it back off.
        e.target.checked = false;
        const res = await window.api.updateSetting('smart_mode', true);
        const strings = window.STRINGS || {};
        showToast(
          (res && res.error === 'smart_mode_unavailable' && strings.smart_mode_unavailable)
          || strings.smart_mode_unavailable
          || 'Функция недоступна в обычном режиме'
        );
      });
    }

    const tgLinkBtn = document.getElementById('btn-open-tg-modal');
    if (tgLinkBtn) {
      tgLinkBtn.addEventListener('click', async () => {
        const state = this.state || {};
        const isLinked = !!(state.telegram && state.telegram.is_linked);
        const displayName = (state.telegram && state.telegram.display_name) || '';
        if (isLinked) {
          window.modalManager.showTelegramModal(
            (state.telegram && state.telegram.link_code) || null,
            true,
            displayName
          );
        } else {
          const res = await window.api.getTelegramLink();
          window.modalManager.showTelegramModal(
            res && res.code ? res.code : (state.telegram && state.telegram.link_code),
            false,
            displayName
          );
        }
      });
    }
  }

  // ==========================================
  // BOTTOM STATUS BAR
  // ==========================================
  initStatusBar() {
    if (this.disarmBtn) {
      this.disarmBtn.addEventListener('click', () => {
        window.api.disarm();
      });
    }
  }

  applyTranslations(strings) {
    if (!strings) return;
    window.STRINGS = strings;
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const text = strings[el.dataset.i18n];
      if (text !== undefined) el.textContent = text;
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      const text = strings[el.dataset.i18nPlaceholder];
      if (text !== undefined) el.placeholder = text;
    });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => {
      const text = strings[el.dataset.i18nTitle];
      if (text !== undefined) el.title = text;
    });
  }

  applyState(state) {
    this.state = state;
    this.applyTranslations(state.strings);

    // Apply Servers & Widths
    if (state.servers) {
      window.tableManager.setServers(state.servers);
    }
    if (state.col_widths) {
      window.tableManager.setColumnWidths(state.col_widths);
    }

    // Apply Settings
    if (state.settings) {
      const tray = document.getElementById('chk-tray');
      if (tray) tray.checked = !!state.settings.minimize_to_tray;

      const swarm = document.getElementById('chk-swarm');
      if (swarm) swarm.checked = !!state.settings.swarm_enabled;

      const share = document.getElementById('chk-share-servers');
      if (share) share.checked = !!state.settings.share_saved_servers;

      const smartMode = document.getElementById('chk-smart-mode');
      if (smartMode) smartMode.checked = !!state.settings.smart_mode;
    }

    if (state.lang) {
      const langSel = document.getElementById('select-lang');
      if (langSel) langSel.value = state.lang;
    }

    // Apply Rust Status (3-State Dot)
    this.updateRustStatus(state.rust_status);

    // Apply Wipe Countdown (next official force-wipe, ticks locally every second)
    if (state.next_force_wipe_at) {
      this.nextForceWipeAt = new Date(state.next_force_wipe_at);
      this.tickWipeCountdown();
    }

    // Apply Connect Button State (smart-connect session in progress?)
    const s = window.STRINGS || {};
    this.isConnecting = ['Connecting', 'Launching', 'Queueing'].includes(state.session_status);
    if (this.connectBtn) {
      const label = this.connectBtn.querySelector('span');
      if (this.isConnecting) {
        if (label) label.textContent = s.btn_cancel || 'CANCEL';
        this.connectBtn.classList.add('connecting');
      } else {
        if (label) label.textContent = s.btn_connect || 'CONNECT';
        this.connectBtn.classList.remove('connecting');
      }
    }

    // Apply Armed Status
    if (this.armedDot && this.armedLabel && this.disarmBtn) {
      if (state.armed_server) {
        this.armedDot.style.backgroundColor = 'var(--success)';
        this.armedDot.style.boxShadow = '0 0 8px var(--success)';
        this.armedLabel.textContent = (s.armed_status_on || 'AutoConnect: on ({server})').replace('{server}', state.armed_server);
        this.disarmBtn.disabled = false;
      } else {
        this.armedDot.style.backgroundColor = 'var(--muted)';
        this.armedDot.style.boxShadow = 'none';
        this.armedLabel.textContent = s.armed_status_off || 'AutoConnect: off';
        this.disarmBtn.disabled = true;
      }
    }

    // Apply Telegram Status & User Name
    this.renderTelegramStatus(state);
  }

  renderTelegramStatus(state) {
    const s = window.STRINGS || {};
    const tgStatusElem = document.getElementById('tg-settings-status');
    const tgBtn = document.getElementById('btn-open-tg-modal');
    const tgBadge = document.getElementById('tg-status-badge');

    if (!state || !state.telegram) {
      if (tgBadge) {
        tgBadge.style.display = 'none';
      }
      if (tgStatusElem) {
        tgStatusElem.textContent = s.tg_status_default || 'Get push notifications for queue slots and wipes on your phone';
      }
      if (tgBtn) {
        tgBtn.textContent = s.btn_tg_link || 'Link bot';
      }
      return;
    }

    const { is_linked, display_name, link_code } = state.telegram;

    if (is_linked) {
      const name = display_name || s.tg_linked_default_name || 'Linked';
      if (tgStatusElem) tgStatusElem.textContent = (s.tg_status_linked || 'Linked to account: {name}').replace('{name}', name);
      if (tgBtn) tgBtn.textContent = s.btn_tg_manage || 'Manage';
      if (tgBadge) {
        tgBadge.textContent = display_name || s.tg_badge_connected || 'Connected';
        tgBadge.className = 'tg-status-badge';
        tgBadge.style.display = 'inline-flex';
      }
    } else if (link_code) {
      if (tgStatusElem) tgStatusElem.textContent = (s.tg_status_code || 'Link code: {link_code}').replace('{link_code}', link_code);
      if (tgBtn) tgBtn.textContent = s.btn_tg_show_code || 'Show code';
      if (tgBadge) {
        tgBadge.style.display = 'none';
      }
    } else {
      if (tgStatusElem) tgStatusElem.textContent = s.tg_status_default || 'Get push notifications for queue slots and wipes on your phone';
      if (tgBtn) tgBtn.textContent = s.btn_tg_link || 'Link bot';
      if (tgBadge) {
        tgBadge.style.display = 'none';
      }
    }
  }


  updateRustStatus(status) {
    if (!this.rustDot || !this.rustLabel) return;
    const s = window.STRINGS || {};

    this.rustDot.classList.remove('running', 'starting');
    if (status === 'running') {
      this.rustDot.classList.add('running');
      this.rustLabel.textContent = s.rust_status_running || 'Rust: running';
      this.rustLabel.style.color = 'var(--text)';
    } else if (status === 'starting') {
      this.rustDot.classList.add('starting');
      this.rustLabel.textContent = s.rust_status_starting || 'Rust: starting...';
      this.rustLabel.style.color = 'var(--warning)';
    } else {
      this.rustLabel.textContent = s.rust_status_stopped || 'Rust: not running';
      this.rustLabel.style.color = 'var(--muted)';
    }
  }

  initWebSocketListeners() {
    window.api.on('init_state', (state) => {
      this.applyState(state);
    });

    window.api.on('state_updated', (state) => {
      this.applyState(state);
    });

    window.api.on('rust_status_changed', (data) => {
      this.updateRustStatus(data.status);
    });
  }

  async start() {
    window.api.initWebSocket();
    try {
      const state = await window.api.getState();
      this.applyState(state);

      const logs = await window.api.getLogs();
      window.drawerManager.setLogs(logs);
    } catch (e) {
      console.warn('Initial fetch waiting for server...', e);
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.app = new AppController();
  window.app.start();
});
