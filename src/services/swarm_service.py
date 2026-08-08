import threading
import json
import websocket
import hmac
import hashlib
from typing import Callable, Optional
from ..core.config import config

class SwarmService:
    def __init__(self):
        self.supabase_ws_url = "wss://eznuyydoanefceqmqxqi.supabase.co/realtime/v1/websocket"
        self.supabase_rest_url = "https://eznuyydoanefceqmqxqi.supabase.co/rest/v1/swarm_events"
        self.supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV6bnV5eWRvYW5lZmNlcW1xeHFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYxNzAyNDgsImV4cCI6MjEwMTc0NjI0OH0.nCxZbqr3m0r242kUBY3RSpF_iwh7vRtBw_nVTxwe-tI"
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        self.on_swarm_event: Optional[Callable[[str], None]] = None
        self.is_connected = False
        self.is_enabled = False
        self._secret = b"RustAutoConnect_Swarm_Secret_v1"
        
    def _sign(self, text: str) -> str:
        return hmac.new(self._secret, text.encode('utf-8'), hashlib.sha256).hexdigest()
        
    def test_connection(self) -> bool:
        """Ping Supabase REST endpoint to verify connection."""
        import urllib.request
        try:
            req = urllib.request.Request(f"{self.supabase_rest_url}?limit=1", headers={"apikey": self.supabase_key, "Authorization": f"Bearer {self.supabase_key}"})
            with urllib.request.urlopen(req, timeout=2.0) as res:
                return res.getcode() == 200
        except Exception as e:
            from ..core.logger import app_logger
            app_logger.error(f"Swarm connection test failed: {e}")
            return False

    def start(self):
        if not self.is_enabled:
            return
        if self.ws_thread and self.ws_thread.is_alive():
            return
            
        url = f"{self.supabase_ws_url}?apikey={self.supabase_key}&vsn=1.0.0"
        
        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()
        
    def stop(self):
        if self.ws:
            self.ws.close()
            
    def _on_open(self, ws):
        self.is_connected = True
        payload = {
            "topic": "realtime:public:swarm_events",
            "event": "phx_join",
            "payload": {
                "config": {
                    "postgres_changes": [
                        {"event": "INSERT", "schema": "public", "table": "swarm_events"}
                    ]
                }
            },
            "ref": "1"
        }
        ws.send(json.dumps(payload))
        
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("event") == "INSERT" or (data.get("payload", {}).get("type") == "INSERT"):
                record = data.get("payload", {}).get("record", {})
                raw_ip = record.get("ip_port")
                if raw_ip and self.on_swarm_event and "|" in raw_ip:
                    ip_port, sig = raw_ip.rsplit("|", 1)
                    if hmac.compare_digest(self._sign(ip_port), sig):
                        self.on_swarm_event(ip_port)
        except Exception:
            pass
            
    def _on_error(self, ws, error):
        pass
        
    def _on_close(self, ws, status_code, msg):
        self.is_connected = False
        
    def broadcast_success(self, ip_port: str):
        if not self.is_enabled:
            return
            
        import urllib.request
        sig = self._sign(ip_port)
        payload = {"ip_port": f"{ip_port}|{sig}"}
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        try:
            req = urllib.request.Request(self.supabase_rest_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5) as res:
                pass
        except Exception:
            pass

swarm_service = SwarmService()
