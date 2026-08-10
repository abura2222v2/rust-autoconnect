import threading
import json
import websocket
from typing import Callable, Optional
from ..core.public_config import get_public_config

class SwarmService:
    def __init__(self):
        public_config = get_public_config()
        self.supabase_ws_url = public_config["SUPABASE_WS_URL"]
        self.supabase_key = public_config["SUPABASE_PUBLISHABLE_KEY"]
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        self.on_swarm_event: Optional[Callable[[str, str], None]] = None
        self.on_presence_update: Optional[Callable[[int], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None
        
        self.is_connected = False
        self.is_enabled = False
        self._stop_event = threading.Event()
        self._reconnect_lock = threading.Lock()
        self._reconnect_pending = False
        
        self.current_room: Optional[str] = None
        self.current_ip_port: Optional[str] = None
        self.presence_keys = set()
        
        import uuid
        self.client_id = str(uuid.uuid4())

    @property
    def is_configured(self) -> bool:
        return bool(self.supabase_key and self._is_public_supabase_key(self.supabase_key))

    @staticmethod
    def _is_public_supabase_key(value: str) -> bool:
        """Reject known elevated keys, including legacy JWT service-role keys."""
        if value.startswith(("sbp_", "sb_secret_")):
            return False
        if value.startswith("eyJ"):
            try:
                import base64
                payload = value.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                role = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8")).get("role")
                return role not in {"service_role", "supabase_admin"}
            except (IndexError, ValueError, UnicodeDecodeError):
                return False
            except Exception as e:
                import binascii
                if isinstance(e, binascii.Error):
                    return False
                raise
        return value.startswith("sb_publishable_")

    @property
    def configuration_status(self) -> str:
        if self.supabase_key and not self._is_public_supabase_key(self.supabase_key):
            return "invalid_key"
        if not self.supabase_key:
            return "not_configured"
        return "configured"

    def start(self):
        with self._reconnect_lock:
            if not self.is_enabled:
                self._notify_status("disabled")
                return
            if not self.is_configured:
                self._notify_status(self.configuration_status)
                if self.is_enabled:
                    from ..core.logger import app_logger
                    app_logger.warning("Swarm is enabled but credentials are not configured.")
                return
            if self.ws_thread and self.ws_thread.is_alive():
                return
                
            self._notify_status("connecting")
            url = f"{self.supabase_ws_url}?apikey={self.supabase_key}&vsn=1.0.0"
            
            ws = websocket.WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            self.ws = ws
            self.ws_thread = threading.Thread(target=ws.run_forever, daemon=True, name="swarm-websocket")
            self._stop_event.clear()
            self.ws_thread.start()
        
    def stop(self):
        with self._reconnect_lock:
            self.is_enabled = False
            self._stop_event.set()
            self._reconnect_pending = False
            ws = self.ws
            self.ws = None
            self.ws_thread = None
            self.is_connected = False
        if ws:
            ws.close()
        self._notify_status("disabled")
            
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
            
            # Presence contains only a random installation-local client id.
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
        if ws is not self.ws or self._stop_event.is_set():
            return
        self.is_connected = True
        self._notify_status("connected")
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
                except Exception:
                    break
                        
        threading.Thread(target=heartbeat_loop, args=(ws,), daemon=True).start()
        
        if self.current_room:
            self._send_join(self.current_room)
        
    def _on_message(self, ws, message):
        if ws is not self.ws or self._stop_event.is_set():
            return
        try:
            data = json.loads(message)
            event = data.get("event")
            
            # Availability reports are advisory.  AppController always performs
            # a fresh local A2S confirmation before launching Rust.
            if event == "broadcast":
                payload = data.get("payload", {})
                inner_event = payload.get("event")
                ip_port = payload.get("payload", {}).get("ip_port")
                if ip_port and self.on_swarm_event and ip_port == self.current_ip_port:
                    if inner_event in ("server_connected", "swarm_stop_spam", "swarm_connection_failed"):
                        self.on_swarm_event(inner_event, ip_port)

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
        if ws is not self.ws or self._stop_event.is_set():
            return
        from ..core.logger import app_logger
        app_logger.warning(f"Swarm WebSocket error: {type(error).__name__}")
        self._notify_status("error")
        
    def _on_close(self, ws, status_code, msg):
        if ws is not self.ws:
            return
        self.ws = None
        self.ws_thread = None
        self.is_connected = False
        if self.is_enabled:
            self._notify_status("disconnected")
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
                    with self._reconnect_lock:
                        self._reconnect_pending = False
                    self.start()
            threading.Thread(target=reconnect, daemon=True).start()

    def _notify_status(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)
        
    def broadcast_success(self, ip_port: str):
        """Broadcast an advisory availability hint to the current Swarm room.

        The event is intentionally unauthenticated and non-authoritative: a
        receiver only wakes a bounded local A2S confirmation probe.
        """
        if not self.is_enabled or not self.is_connected or not self.ws or not self.current_room:
            return
        try:
            self.ws.send(json.dumps({
                "topic": self.current_room,
                "event": "broadcast",
                "payload": {"type": "broadcast", "event": "server_connected", "payload": {"ip_port": ip_port}},
                "ref": "hint",
            }))
        except websocket.WebSocketException as error:
            from ..core.logger import app_logger
            app_logger.warning(f"Failed to report swarm hint: {type(error).__name__}")

    def broadcast_stop_spam(self, ip_port: str):
        if not self.is_enabled or not self.is_connected or not self.ws or not self.current_room:
            return
        try:
            self.ws.send(json.dumps({
                "topic": self.current_room,
                "event": "broadcast",
                "payload": {"type": "broadcast", "event": "swarm_stop_spam", "payload": {"ip_port": ip_port}},
                "ref": "stop_spam",
            }))
        except websocket.WebSocketException as error:
            from ..core.logger import app_logger
            app_logger.warning(f"Failed to report swarm stop_spam: {type(error).__name__}")
            
    def broadcast_connection_failed(self, ip_port: str):
        if not self.is_enabled or not self.is_connected or not self.ws or not self.current_room:
            return
        try:
            self.ws.send(json.dumps({
                "topic": self.current_room,
                "event": "broadcast",
                "payload": {"type": "broadcast", "event": "swarm_connection_failed", "payload": {"ip_port": ip_port}},
                "ref": "fail",
            }))
        except websocket.WebSocketException as error:
            from ..core.logger import app_logger
            app_logger.warning(f"Failed to report swarm connection_failed: {type(error).__name__}")

swarm_service = SwarmService()
