from dataclasses import dataclass
from pathlib import Path
import os

@dataclass(frozen=True)
class AppConfig:
    STEAM_APP_ID: int = 252490
    POLL_INTERVAL: float = 3.0
    A2S_TIMEOUT: float = 0.6
    BENCHMARK_VERSION: str = "rust-load-v1"
    PORT_OFFSETS: tuple = (0, 15, 2, 3, 1, 5, 10, 123)
    DISCONNECT_KEYWORDS: tuple = (
        "Disconnected", "Connection Attempt Failed", 
        "Rejected", "Kicked", "User Cancelled", "Server Closed"
    )
    
    @property
    def appdata_dir(self) -> Path:
        return Path(os.environ.get("APPDATA", "")) / "RustAutoConnect"
        
    @property
    def data_file(self) -> Path:
        return self.appdata_dir / "data.json"
        
    @property
    def rust_log_path(self) -> Path:
        return Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "Facepunch Studios LTD" / "Rust" / "Player.log"

config = AppConfig()
