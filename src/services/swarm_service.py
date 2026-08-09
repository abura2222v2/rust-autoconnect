import threading
import json
import os
import websocket
import hmac
import hashlib
from typing import Callable, Optional
from ..core.config import config

class SwarmService:
    def __init__(self):
        self.supabase_ws_url = os.environ.get('SUPABASE_WS_URL', "wss://eznuyydoanefceqmqxqi.supabase.co/realtime/v1/websocket")
        self.supabase_key = os.environ.get('SUPABASE_KEY', "")
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        self.on_swarm_event: Optional[Callable[[str], None]] = None
        self.on_presence_update: Optional[Callable[[int], None]] = None
        
        self.is_connected = False
        self.is_enabled = False
        self._stop_event = threading.Event()
        self._reconnect_lock = threading.Lock()
        self._reconnect_pending = False
        
        self.current_room: Optional[str] = None
        self.current_ip_port: Optional[str] = None
        self.presence_keys = set()
        
        secret = os.environ.get('SWARM_SECRET', '')
        if isinstance(secret, str):
            secret = secret.encode('utf-8')
        self._secret = secret
        
        import uuid
        self.client_id = str(uuid.uuid4())

    @property
    def is_configured(self) -> bool:
        return bool(self.supabase_key and self._secret)
        
    def _sign(self, text: str) -> str:
        secret = os.environ.get('SWARM_SECRET', self._secret)
        if isinstance(secret, str):
            secret = secret.encode('utf-8')
        return hmac.new(secret, text.encode('utf-8'), hashlib.sha256).hexdigest()
        
    def test_connection(self) -> bool:
        """Ping Supabase REST endpoint to verify connection."""
        import urllib.request
        try:
            # We ping the benchmarks table to test connection since we know it exists
            test_url = "https://eznuyydoanefceqmqxqi.supabase.co/rest/v1/benchmarks?limit=1"
            req = urllib.request.Request(test_url, headers={"apikey": self.supabase_key, "Authorization": f"Bearer {self.supabase_key}"})
            with urllib.request.urlopen(req, timeout=2.0) as res:
                return res.getcode() == 200
        except Exception as e:
            from ..core.logger import app_logger
            app_logger.error(f"Swarm connection test failed: {type(e).__name__}")
            return False

    def start(self):
        if not self.is_enabled or not self.is_configured:
            if self.is_enabled and not self.is_configured:
                from ..core.logger import app_logger
                app_logger.warning("Swarm is enabled but credentials are not configured.")
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
        self._stop_event.clear()
        self.ws_thread.start()
        
    def stop(self):
        self.is_enabled = False
        self._stop_event.set()
        if self.ws:
            self.ws.close()
            
    def join_room(self, ip_port: str):
        if not self.is_enabled:
            return
            
        self.current_ip_port = ip_port
        room_name = f"realtime:room_{ip_port.replace('.', '_').replace(':', '_')}"
        self.current_room = room_name
        
        if self.is_connected and self.ws:
            self._send_join(room_name)
            
    def leave_room(self):
        if self.is_connected and self.ws and self.current_room:
            payload = {
                "topic": self.current_room,
                "event": "phx_leave",
                "payload": {},
                "ref": "leave"
            }
            try:
                self.ws.send(json.dumps(payload))
            except websocket.WebSocketException as error:
                from ..core.logger import app_logger
                app_logger.warning(f"Failed to leave swarm room: {type(error).__name__}")
        self.current_room = None
        self.current_ip_port = None
        if self.on_presence_update:
            self.on_presence_update(0)
            
    def _send_join(self, room_name: str):
        payload = {
            "topic": room_name,
            "event": "phx_join",
            "payload": {
                "config": {
                    "broadcast": { "ack": False },
                    "presence": { "key": self.client_id }
                }
            },
            "ref": "join"
        }
        try:
            self.ws.send(json.dumps(payload))
            
            # Send track event for Presence
            track_msg = {
                "topic": room_name,
                "event": "presence",
                "payload": {
                    "type": "presence",
                    "event": "track",
                    "payload": {"status": "waiting"}
                },
                "ref": "track"
            }
            self.ws.send(json.dumps(track_msg))
        except Exception as e:
            from ..core.logger import app_logger
            app_logger.error(f"Failed to join room: {type(e).__name__}")
            
    def _on_open(self, ws):
        self.is_connected = True
        with self._reconnect_lock:
            self._reconnect_pending = False
        
        # Start heartbeat loop required by Phoenix/Supabase
        def heartbeat_loop(current_ws):
            import time
            ref = 100
            while self.is_connected and self.ws:
                if self.ws is not current_ws:
                    break
                if self._stop_event.wait(25):
                    break
                if not self.is_connected or self.ws is not current_ws:
                    break
                try:
                    current_ws.send(json.dumps({
                        "topic": "phoenix",
                        "event": "heartbeat",
                        "payload": {},
                        "ref": str(ref)
                    }))
                    ref += 1
                except websocket.WebSocketException:
                    break
                        
        threading.Thread(target=heartbeat_loop, args=(ws,), daemon=True).start()
        
        if self.current_room:
            self._send_join(self.current_room)
        
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            event = data.get("event")
            
            # Handle Broadcast
            if event == "broadcast":
                payload = data.get("payload", {})
                if payload.get("event") == "server_connected":
                    raw_ip = payload.get("payload", {}).get("ip_port")
                    if raw_ip and self.on_swarm_event and "|" in raw_ip:
                        ip_port, sig = raw_ip.rsplit("|", 1)
                        if hmac.compare_digest(self._sign(ip_port), sig):
                            if ip_port == self.current_ip_port:
                                self.on_swarm_event(ip_port)
                                
            # Handle Presence
            elif event == "presence_state":
                state = data.get("payload", {})
                self.presence_keys = set(state.keys())
                if self.on_presence_update:
                    self.on_presence_update(len(self.presence_keys))
            elif event == "presence_diff":
                joins = data.get("payload", {}).get("joins", {})
                leaves = data.get("payload", {}).get("leaves", {})
                self.presence_keys.update(joins.keys())
                self.presence_keys.difference_update(leaves.keys())
                if self.on_presence_update:
                    self.on_presence_update(len(self.presence_keys))
                
        except Exception as e:
            from ..core.logger import app_logger
            app_logger.error(f"Swarm message error: {type(e).__name__}")
            
    def _on_error(self, ws, error):
        from ..core.logger import app_logger
        app_logger.warning(f"Swarm WebSocket error: {type(error).__name__}")
        
    def _on_close(self, ws, status_code, msg):
        self.is_connected = False
        if self.is_enabled and not self._stop_event.is_set():
            import time
            with self._reconnect_lock:
                if self._reconnect_pending:
                    return
                self._reconnect_pending = True
            def reconnect():
                if self._stop_event.wait(5):
                    return
                if self.is_enabled and not self.is_connected:
                    self.start()
            threading.Thread(target=reconnect, daemon=True).start()
        
    def broadcast_success(self, ip_port: str):
        if not self.is_enabled or not self.is_connected or not self.ws or not self.current_room:
            return
            
        sig = self._sign(ip_port)
        payload = {
            "topic": self.current_room,
            "event": "broadcast",
            "payload": {
                "type": "broadcast",
                "event": "server_connected",
                "payload": {"ip_port": f"{ip_port}|{sig}"}
            },
            "ref": "broadcast"
        }
        
        try:
            self.ws.send(json.dumps(payload))
        except Exception as e:
            from ..core.logger import app_logger
            app_logger.error(f"Failed to broadcast: {type(e).__name__}")

swarm_service = SwarmService()
