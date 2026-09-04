/**
 * Rust AutoConnect - API & WebSocket Bridge
 */

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
}
window.escapeHtml = escapeHtml;

class ApiService {
  constructor() {
    this.ws = null;
    this.listeners = new Map();
    this.isConnected = false;
    this._reconnectTimer = null;
  }

  initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.isConnected = true;
      console.log('[WS] Connected to Rust AutoConnect Backend');
      this.emit('connected', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type) {
          this.emit(payload.type, payload.data);
        }
      } catch (err) {
        console.error('[WS] Parse error:', err);
      }
    };

    this.ws.onclose = () => {
      this.isConnected = false;
      console.warn('[WS] Disconnected. Reconnecting in 2s...');
      this.emit('disconnected', {});
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = setTimeout(() => this.initWebSocket(), 2000);
    };

    this.ws.onerror = (err) => {
      console.error('[WS] Error:', err);
      this.ws.close();
    };
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
  }

  emit(event, data) {
    if (this.listeners.has(event)) {
      for (const cb of this.listeners.get(event)) {
        try {
          cb(data);
        } catch (e) {
          console.error(`Error in listener for ${event}:`, e);
        }
      }
    }
  }

  async get(endpoint) {
    const res = await fetch(endpoint, {
      headers: { 'X-AutoConnect-Token': window.__AC_SESSION_TOKEN__ || '' },
    });
    return await res.json();
  }

  async post(endpoint, body = {}) {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-AutoConnect-Token': window.__AC_SESSION_TOKEN__ || '',
      },
      body: JSON.stringify(body),
    });
    return await res.json();
  }

  // Specific API calls
  async getState() { return await this.get('/api/state'); }
  async connect(ip) { return await this.post('/api/connect', { ip }); }
  async stopConnecting() { return await this.post('/api/stop_connecting'); }
  async toggleArmed(ip, name) { return await this.post('/api/toggle_armed', { ip, name }); }
  async disarm() { return await this.post('/api/disarm'); }
  async toggleFavorite(ip, name) { return await this.post('/api/toggle_favorite', { ip, name }); }
  async removeServer(ip) { return await this.post('/api/remove_server', { ip }); }
  async saveColumnWidths(widths) { return await this.post('/api/col_widths', { widths }); }
  async setLanguage(lang) { return await this.post('/api/language', { lang }); }
  async updateSetting(key, value) { return await this.post('/api/setting', { key, value }); }
  async getBenchmarkInfo() { return await this.get('/api/benchmark_info'); }
  async runBenchmark() { return await this.post('/api/run_benchmark'); }
  async stopBenchmark() { return await this.post('/api/stop_benchmark'); }
  async getLeaderboard() { return await this.get('/api/leaderboard'); }
  async getTelegramLink() { return await this.post('/api/telegram_link'); }
  async unlinkTelegram() { return await this.post('/api/telegram_unlink'); }
  async getLogs() { return await this.get('/api/logs'); }
  async clearLogs() { return await this.post('/api/clear_logs'); }
}

window.api = new ApiService();
