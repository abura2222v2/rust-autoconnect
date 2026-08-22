/**
 * Rust AutoConnect - Main Reactive Application Controller
 */

class AppController {
  constructor() {
    this.currentTab = 'servers';
    this.state = null;

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
  }

  tickWipeCountdown() {
    if (!this.wipeCountdownLabel || !this.nextForceWipeAt) return;
    const remainingMs = this.nextForceWipeAt.getTime() - Date.now();
    if (remainingMs <= 0) {
      this.wipeCountdownLabel.textContent = 'Вайп: идёт сейчас';
      return;
    }
    const totalSeconds = Math.floor(remainingMs / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const parts = [];
    if (days > 0) parts.push(`${days}д`);
    parts.push(`${hours}ч`, `${minutes}м`);
    this.wipeCountdownLabel.textContent = `Вайп через: ${parts.join(' ')}`;
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
        runBtn.textContent = 'Тестирование...';
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
          runBtn.textContent = 'Запустить тест';
        }
        this.refreshBenchmarkData();
      }
    });
  }

  async refreshBenchmarkData() {
    const info = await window.api.getBenchmarkInfo();
    const cpuElem = document.getElementById('spec-cpu');
    const ramElem = document.getElementById('spec-ram');
    const diskElem = document.getElementById('spec-disk');
    const countElem = document.getElementById('bench-run-count');

    if (cpuElem) cpuElem.textContent = info.cpu || 'Unknown CPU';
    if (ramElem) ramElem.textContent = info.ram || 'Unknown RAM';
    if (diskElem) diskElem.textContent = info.disk || 'Unknown Storage';
    if (countElem) countElem.textContent = `Локальных тестов: ${info.run_count || 0}`;

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

  applyState(state) {
    this.state = state;

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
    this.isConnecting = ['Connecting', 'Launching', 'Queueing'].includes(state.session_status);
    if (this.connectBtn) {
      const label = this.connectBtn.querySelector('span');
      if (this.isConnecting) {
        if (label) label.textContent = 'ОТМЕНА';
        this.connectBtn.classList.add('connecting');
      } else {
        if (label) label.textContent = 'ПОДКЛЮЧИТЬСЯ';
        this.connectBtn.classList.remove('connecting');
      }
    }

    // Apply Armed Status
    if (this.armedDot && this.armedLabel && this.disarmBtn) {
      if (state.armed_server) {
        this.armedDot.style.backgroundColor = 'var(--success)';
        this.armedDot.style.boxShadow = '0 0 8px var(--success)';
        this.armedLabel.textContent = `Автоподключение: включено (${state.armed_server})`;
        this.disarmBtn.disabled = false;
      } else {
        this.armedDot.style.backgroundColor = 'var(--muted)';
        this.armedDot.style.boxShadow = 'none';
        this.armedLabel.textContent = 'Автоподключение: выключено';
        this.disarmBtn.disabled = true;
      }
    }

    // Apply Telegram Status & User Name
    this.renderTelegramStatus(state);
  }

  renderTelegramStatus(state) {
    const tgStatusElem = document.getElementById('tg-settings-status');
    const tgBtn = document.getElementById('btn-open-tg-modal');
    const tgBadge = document.getElementById('tg-status-badge');

    if (!state || !state.telegram) {
      if (tgBadge) {
        tgBadge.style.display = 'none';
      }
      if (tgStatusElem) {
        tgStatusElem.textContent = 'Получать пуш-уведомления об окончании очереди и вайпах на телефон';
      }
      if (tgBtn) {
        tgBtn.textContent = 'Привязать бота';
      }
      return;
    }

    const { is_linked, display_name, link_code } = state.telegram;

    if (is_linked) {
      const name = display_name || 'Привязан';
      if (tgStatusElem) tgStatusElem.textContent = `Привязан к аккаунту: ${name}`;
      if (tgBtn) tgBtn.textContent = 'Управление';
      if (tgBadge) {
        tgBadge.textContent = display_name || 'Подключен';
        tgBadge.className = 'tg-status-badge';
        tgBadge.style.display = 'inline-flex';
      }
    } else if (link_code) {
      if (tgStatusElem) tgStatusElem.textContent = `Код привязки: ${link_code}`;
      if (tgBtn) tgBtn.textContent = 'Показать код';
      if (tgBadge) {
        tgBadge.style.display = 'none';
      }
    } else {
      if (tgStatusElem) tgStatusElem.textContent = 'Получать пуш-уведомления об окончании очереди и вайпах на телефон';
      if (tgBtn) tgBtn.textContent = 'Привязать бота';
      if (tgBadge) {
        tgBadge.style.display = 'none';
      }
    }
  }


  updateRustStatus(status) {
    if (!this.rustDot || !this.rustLabel) return;

    this.rustDot.classList.remove('running', 'starting');
    if (status === 'running') {
      this.rustDot.classList.add('running');
      this.rustLabel.textContent = 'Rust: запущен';
      this.rustLabel.style.color = 'var(--text)';
    } else if (status === 'starting') {
      this.rustDot.classList.add('starting');
      this.rustLabel.textContent = 'Rust: запуск...';
      this.rustLabel.style.color = 'var(--warning)';
    } else {
      this.rustLabel.textContent = 'Rust: не запущен';
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
