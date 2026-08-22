/**
 * Rust AutoConnect - Server Table & Excel-style Resizer Engine
 */

class ServerTableManager {
  constructor() {
    this.servers = [];
    this.filterMode = 'all'; // 'all' | 'favorites'
    this.searchQuery = '';
    this.colWidths = {
      star: 36,
      name: 280,
      addr: 180,
      players: 84,
      local: 64,
      action: 116,
    };
    this.minWidths = {
      star: 32,
      name: 140,
      addr: 130,
      players: 60,
      local: 50,
      action: 90,
    };

    this.tableBody = document.getElementById('table-body');
    this.tablePanel = document.getElementById('table-panel');
    this.ghostLine = document.getElementById('ghost-guide-line');
    this.ghostBadge = document.getElementById('ghost-guide-badge');
    this.contextMenu = document.getElementById('context-menu');

    this._activeContextMenuServer = null;
    this._dragState = null;

    this.initResizers();
    this.initContextMenu();
  }

  setServers(servers) {
    this.servers = servers || [];
    this.render();
  }

  setColumnWidths(widths) {
    if (!widths) return;
    this.colWidths = { ...this.colWidths, ...widths };
    for (const [col, w] of Object.entries(this.colWidths)) {
      document.documentElement.style.setProperty(`--col-${col}`, `${w}px`);
    }
  }

  setFilter(mode) {
    this.filterMode = mode;
    this.render();
  }

  setSearch(query) {
    this.searchQuery = (query || '').toLowerCase().trim();
    this.render();
  }

  render() {
    if (!this.tableBody) return;

    let list = this.servers.slice();

    // Apply Search Filter
    if (this.searchQuery) {
      list = list.filter(s =>
        (s.name && s.name.toLowerCase().includes(this.searchQuery)) ||
        (s.ip && s.ip.toLowerCase().includes(this.searchQuery))
      );
    }

    // Apply Favorites Filter
    if (this.filterMode === 'favorites') {
      list = list.filter(s => s.is_favorite);
    }

    // Sort: Favorites first, then newest
    list.sort((a, b) => {
      if (a.is_favorite !== b.is_favorite) {
        return a.is_favorite ? -1 : 1;
      }
      return (b.added_at || 0) - (a.added_at || 0);
    });

    if (list.length === 0) {
      this.tableBody.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:180px; color:var(--muted); gap:8px;">
          <svg class="icon" viewBox="0 0 24 24" style="width:32px; height:32px; opacity:0.4;"><use href="#icon-filter"></use></svg>
          <div>${(window.STRINGS || {}).no_servers_found || 'No servers found'}</div>
        </div>
      `;
      return;
    }

    this.tableBody.innerHTML = list.map(s => this.renderRowHtml(s)).join('');
    this.bindRowEvents();
  }

  renderRowHtml(s) {
    const starIcon = s.is_favorite ? 'icon-star-filled' : 'icon-star-outline';
    const starClass = s.is_favorite ? 'favorited' : '';
    const armIcon = s.is_armed ? 'icon-shield-armed' : 'icon-shield';
    const armClass = s.is_armed ? 'armed' : '';
    const safeName = escapeHtml(s.name || s.ip);
    const safeIp = escapeHtml(s.ip);
    const strings = window.STRINGS || {};
    const statusTitles = {
      online: strings.status_online || 'Online',
      offline: strings.status_offline || 'Offline',
      checking: strings.status_checking || 'Checking...',
    };
    const statusClass = s.status || 'checking';
    const statusTitle = statusTitles[statusClass] || statusTitles.checking;

    return `
      <div class="table-row" data-ip="${safeIp}" data-name="${safeName}">
        <!-- 1. Star Favorite -->
        <div class="td-cell td-star">
          <button class="btn-star ${starClass}" title="${strings.btn_favorite_title || 'Add to favorites'}" data-action="favorite">
            <svg class="icon" viewBox="0 0 24 24"><use href="#${starIcon}"></use></svg>
          </button>
        </div>

        <div class="td-divider"></div>

        <!-- 2. Server Name -->
        <div class="td-cell td-name" title="${safeName}">
          ${safeName}
        </div>

        <div class="td-divider"></div>

        <!-- 3. Address -->
        <div class="td-cell td-addr" title="${safeIp}">
          <span>${safeIp}</span>
          <button class="btn-copy-mini" title="${strings.ctx_copy || 'Copy address'}" data-action="copy">
            <svg class="icon" viewBox="0 0 24 24"><use href="#icon-copy"></use></svg>
          </button>
        </div>

        <div class="td-divider"></div>

        <!-- 4. Players Count -->
        <div class="td-cell td-players">
          ${s.players || 97}/${s.max_players || 150}
        </div>

        <div class="td-divider"></div>

        <!-- 5. Local Status Dot -->
        <div class="td-cell td-local">
          <div class="status-dot ${statusClass}" title="${statusTitle}"></div>
        </div>

        <div class="td-divider"></div>

        <!-- 6. Actions (AutoArm, Delete, Connect) -->
        <div class="td-cell td-action">
          <button class="btn-row-action ${armClass}" title="${s.is_armed ? (strings.btn_autoarm_on_title || 'AutoConnect: on') : (strings.btn_autoarm_off_title || 'Arm AutoConnect')}" data-action="autoarm">
            <svg class="icon" viewBox="0 0 24 24"><use href="#${armIcon}"></use></svg>
          </button>
          <button class="btn-row-action" title="${strings.btn_delete_title || 'Delete server'}" data-action="delete">
            <svg class="icon" viewBox="0 0 24 24"><use href="#icon-trash"></use></svg>
          </button>
          <button class="btn-row-action connect" title="${strings.ctx_connect || 'Connect'}" data-action="connect">
            <svg class="icon" viewBox="0 0 24 24"><use href="#icon-play"></use></svg>
          </button>
        </div>
      </div>
    `;
  }

  bindRowEvents() {
    const rows = this.tableBody.querySelectorAll('.table-row');
    rows.forEach(row => {
      const ip = row.dataset.ip;
      const name = row.dataset.name;
      const serverObj = this.servers.find(s => s.ip === ip) || { ip, name };

      // Row click opens Server Details Card
      row.addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (btn) return; // Handled by button action
        window.modalManager.showServerCard(serverObj);
      });

      // Right-Click Context Menu
      row.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        this.openContextMenu(e.pageX, e.pageY, serverObj);
      });

      // Row Button Actions
      const favBtn = row.querySelector('[data-action="favorite"]');
      if (favBtn) {
        favBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          window.api.toggleFavorite(ip, name);
        });
      }

      const copyBtn = row.querySelector('[data-action="copy"]');
      if (copyBtn) {
        copyBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          navigator.clipboard.writeText(ip);
          copyBtn.style.color = 'var(--success)';
          setTimeout(() => { copyBtn.style.color = ''; }, 1200);
        });
      }

      const armBtn = row.querySelector('[data-action="autoarm"]');
      if (armBtn) {
        armBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          window.api.toggleArmed(ip, name);
        });
      }

      const delBtn = row.querySelector('[data-action="delete"]');
      if (delBtn) {
        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const msg = ((window.STRINGS || {}).confirm_delete_server || 'Remove server {name} from the list?').replace('{name}', name || ip);
          if (confirm(msg)) {
            window.api.removeServer(ip);
          }
        });
      }

      const connBtn = row.querySelector('[data-action="connect"]');
      if (connBtn) {
        connBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          window.api.connect(ip);
        });
      }
    });
  }

  // ==========================================
  // EXCEL-STYLE COLUMN RESIZING (Zero-Lag Ghost Guide)
  // ==========================================
  initResizers() {
    const dividers = document.querySelectorAll('.col-divider');

    dividers.forEach(div => {
      const colKey = div.dataset.col;

      div.addEventListener('mousedown', (e) => {
        e.preventDefault();
        this._dragState = {
          colKey,
          startX: e.pageX,
          initialWidth: this.colWidths[colKey] || 100,
          currentWidth: this.colWidths[colKey] || 100,
        };

        const panelRect = this.tablePanel.getBoundingClientRect();
        const localX = e.pageX - panelRect.left;

        if (this.ghostLine && this.ghostBadge) {
          this.ghostLine.style.left = `${localX}px`;
          this.ghostLine.style.display = 'block';

          this.ghostBadge.textContent = `${this._dragState.initialWidth} px`;
          this.ghostBadge.style.left = `${Math.min(localX + 8, panelRect.width - 70)}px`;
          this.ghostBadge.style.display = 'block';
        }

        div.classList.add('dragging');
      });

      // Double click for Auto-Fit
      div.addEventListener('dblclick', () => {
        this.autoFitColumn(colKey);
      });
    });

    window.addEventListener('mousemove', (e) => {
      if (!this._dragState) return;

      const delta = e.pageX - this._dragState.startX;
      const minW = this.minWidths[this._dragState.colKey] || 40;
      const newW = Math.max(minW, this._dragState.initialWidth + delta);
      this._dragState.currentWidth = newW;

      const panelRect = this.tablePanel.getBoundingClientRect();
      const localX = e.pageX - panelRect.left;

      if (this.ghostLine && this.ghostBadge) {
        this.ghostLine.style.left = `${localX}px`;
        this.ghostBadge.textContent = `${newW} px`;
        this.ghostBadge.style.left = `${Math.min(localX + 8, panelRect.width - 70)}px`;
      }
    });

    window.addEventListener('mouseup', () => {
      if (!this._dragState) return;

      const colKey = this._dragState.colKey;
      const finalW = this._dragState.currentWidth;

      this.colWidths[colKey] = finalW;
      document.documentElement.style.setProperty(`--col-${colKey}`, `${finalW}px`);

      if (this.ghostLine) this.ghostLine.style.display = 'none';
      if (this.ghostBadge) this.ghostBadge.style.display = 'none';

      const draggingDivider = document.querySelector('.col-divider.dragging');
      if (draggingDivider) draggingDivider.classList.remove('dragging');

      this._dragState = null;
      window.api.saveColumnWidths(this.colWidths);
    });
  }

  autoFitColumn(colKey) {
    if (colKey === 'name') {
      let maxLen = 14;
      this.servers.forEach(s => {
        if (s.name && s.name.length > maxLen) maxLen = s.name.length;
      });
      const idealW = Math.min(450, Math.max(this.minWidths.name, Math.round(maxLen * 7.6) + 36));
      this.colWidths.name = idealW;
    } else if (colKey === 'addr') {
      this.colWidths.addr = 180;
    } else if (colKey === 'players') {
      this.colWidths.players = 84;
    } else if (colKey === 'local') {
      this.colWidths.local = 64;
    } else if (colKey === 'action') {
      this.colWidths.action = 116;
    } else if (colKey === 'star') {
      this.colWidths.star = 36;
    }

    document.documentElement.style.setProperty(`--col-${colKey}`, `${this.colWidths[colKey]}px`);
    window.api.saveColumnWidths(this.colWidths);
  }

  // ==========================================
  // RIGHT-CLICK CONTEXT MENU
  // ==========================================
  initContextMenu() {
    if (!this.contextMenu) return;

    window.addEventListener('click', () => {
      this.closeContextMenu();
    });

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.closeContextMenu();
    });

    const connectItem = document.getElementById('ctx-connect');
    if (connectItem) {
      connectItem.addEventListener('click', () => {
        if (this._activeContextMenuServer) {
          window.api.connect(this._activeContextMenuServer.ip);
        }
      });
    }

    const armItem = document.getElementById('ctx-autoarm');
    if (armItem) {
      armItem.addEventListener('click', () => {
        if (this._activeContextMenuServer) {
          window.api.toggleArmed(this._activeContextMenuServer.ip, this._activeContextMenuServer.name);
        }
      });
    }

    const copyItem = document.getElementById('ctx-copy');
    if (copyItem) {
      copyItem.addEventListener('click', () => {
        if (this._activeContextMenuServer) {
          navigator.clipboard.writeText(this._activeContextMenuServer.ip);
        }
      });
    }

    const detailsItem = document.getElementById('ctx-details');
    if (detailsItem) {
      detailsItem.addEventListener('click', () => {
        if (this._activeContextMenuServer) {
          window.modalManager.showServerCard(this._activeContextMenuServer);
        }
      });
    }

    const deleteItem = document.getElementById('ctx-delete');
    if (deleteItem) {
      deleteItem.addEventListener('click', () => {
        if (this._activeContextMenuServer) {
          const name = this._activeContextMenuServer.name || this._activeContextMenuServer.ip;
          const msg = ((window.STRINGS || {}).confirm_delete_server_ctx || 'Delete server {name}?').replace('{name}', name);
          if (confirm(msg)) {
            window.api.removeServer(this._activeContextMenuServer.ip);
          }
        }
      });
    }
  }

  openContextMenu(x, y, server) {
    if (!this.contextMenu) return;
    this._activeContextMenuServer = server;

    const armItem = document.getElementById('ctx-autoarm');
    if (armItem) {
      const s = window.STRINGS || {};
      const label = server.is_armed ? (s.ctx_autoarm_disarm || 'Disarm AutoConnect') : (s.ctx_autoarm_arm || 'Arm AutoConnect');
      const icon = server.is_armed ? 'icon-shield' : 'icon-shield-armed';
      armItem.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><use href="#${icon}"></use></svg> <span>${escapeHtml(label)}</span>`;
    }

    this.contextMenu.style.left = `${Math.min(x, window.innerWidth - 200)}px`;
    this.contextMenu.style.top = `${Math.min(y, window.innerHeight - 190)}px`;
    this.contextMenu.classList.add('open');
  }

  closeContextMenu() {
    if (this.contextMenu) {
      this.contextMenu.classList.remove('open');
      this._activeContextMenuServer = null;
    }
  }
}

window.tableManager = new ServerTableManager();
