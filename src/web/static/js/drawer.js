/**
 * Rust AutoConnect - 144 FPS Hardware-Accelerated Activity Log Drawer
 */

class ActivityDrawerManager {
  constructor() {
    this.drawer = document.getElementById('activity-drawer');
    this.backdrop = document.getElementById('drawer-backdrop');
    this.logBody = document.getElementById('drawer-log-body');
    this.toggleBtn = document.getElementById('btn-log-drawer');
    this.closeBtn = document.getElementById('btn-close-drawer');
    this.clearBtn = document.getElementById('btn-clear-log');
    this.autoScrollCheck = document.getElementById('chk-autoscroll');

    this.isOpen = false;
    this.autoScroll = true;

    this.initEvents();
  }

  initEvents() {
    if (this.toggleBtn) {
      this.toggleBtn.addEventListener('click', () => this.toggle());
    }

    if (this.closeBtn) {
      this.closeBtn.addEventListener('click', () => this.close());
    }

    if (this.backdrop) {
      this.backdrop.addEventListener('click', () => this.close());
    }

    if (this.clearBtn) {
      this.clearBtn.addEventListener('click', () => {
        window.api.clearLogs();
        if (this.logBody) this.logBody.innerHTML = '';
      });
    }

    if (this.autoScrollCheck) {
      this.autoScrollCheck.addEventListener('change', (e) => {
        this.autoScroll = e.target.checked;
        if (this.autoScroll) this.scrollToBottom();
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });

    // Listen for WebSocket log events
    window.api.on('log', (entry) => {
      this.appendLog(entry);
    });

    window.api.on('logs_cleared', () => {
      if (this.logBody) this.logBody.innerHTML = '';
    });
  }

  toggle() {
    if (this.isOpen) {
      this.close();
    } else {
      this.open();
    }
  }

  open() {
    this.isOpen = true;
    if (this.drawer) this.drawer.classList.add('open');
    if (this.backdrop) this.backdrop.classList.add('open');
    if (this.toggleBtn) this.toggleBtn.classList.add('active');
    this.scrollToBottom();
  }

  close() {
    this.isOpen = false;
    if (this.drawer) this.drawer.classList.remove('open');
    if (this.backdrop) this.backdrop.classList.remove('open');
    if (this.toggleBtn) this.toggleBtn.classList.remove('active');
  }

  setLogs(logs) {
    if (!this.logBody) return;
    this.logBody.innerHTML = '';
    (logs || []).forEach(log => this.appendLog(log, false));
    this.scrollToBottom();
  }

  appendLog(entry, scroll = true) {
    if (!this.logBody) return;

    const div = document.createElement('div');
    div.className = 'log-entry';
    div.innerHTML = `
      <span class="log-ts">${escapeHtml(entry.timestamp)}</span>
      <span class="log-msg" style="color:${entry.color || '#D4DAE2'};">${escapeHtml(entry.message)}</span>
    `;
    this.logBody.appendChild(div);

    // Keep max 500 lines in DOM
    if (this.logBody.children.length > 500) {
      this.logBody.removeChild(this.logBody.firstElementChild);
    }

    if (scroll && this.autoScroll) {
      this.scrollToBottom();
    }
  }

  scrollToBottom() {
    if (this.logBody) {
      this.logBody.scrollTop = this.logBody.scrollHeight;
    }
  }
}

window.drawerManager = new ActivityDrawerManager();
