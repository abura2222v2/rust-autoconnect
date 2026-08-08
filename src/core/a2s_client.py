import socket
import a2s
from typing import Tuple

class A2SClient:
    def __init__(self, timeout=0.6, offsets=(0, 15, 3, 1, 123)):
        self.timeout = timeout
        self.offsets = offsets

    def check_server_alive(self, ip: str, base_port: int) -> Tuple[bool, str, int, int]:
        """
        Returns (is_alive, name, max_players, actual_query_port)
        Fixes BUG-06: returns actual query port.
        Fixes BUG-07: ignores BrokenMessageError.
        """
        for offset in self.offsets:
            query_port = base_port + offset
            address = (ip, query_port)
            try:
                info = a2s.info(address, timeout=self.timeout)
                return True, info.server_name, info.max_players, query_port
            except a2s.exceptions.BrokenMessageError:
                # BUG-07: Treat broken messages as offline
                continue
            except Exception:
                continue
        return False, "", 0, base_port

a2s_client = A2SClient()
