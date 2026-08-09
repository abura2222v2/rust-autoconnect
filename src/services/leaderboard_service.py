import urllib.request
import json
import os
from concurrent.futures import ThreadPoolExecutor

class LeaderboardService:
    def __init__(self):
        self.url = "https://eznuyydoanefceqmqxqi.supabase.co/rest/v1/benchmarks"
        self._executor = ThreadPoolExecutor(max_workers=4)

    @property
    def key(self) -> str:
        return os.environ.get('SUPABASE_KEY', '')

    def _http_request(self, req, timeout: int = 5):
        def _do_request():
            with urllib.request.urlopen(req, timeout=timeout) as res:
                code = res.getcode() if hasattr(res, 'getcode') else res.status
                return code, res.read()
        return self._executor.submit(_do_request).result()

    def fetch_leaderboard(self, limit: int = 500, offset: int = 0, search_query: str = "", sort_order: str = "asc") -> list:
        try:
            url = f"{self.url}?select=*&order=total_time.{sort_order}&limit={limit}&offset={offset}"
            if search_query:
                # Add basic search filter using Supabase ilike
                import urllib.parse as uparse
                sq = uparse.quote(f"%{search_query}%")
                url += f"&or=(username.ilike.{sq},cpu.ilike.{sq},disk.ilike.{sq})"
                
            req = urllib.request.Request(url)
            req.add_header("apikey", self.key)
            req.add_header("Authorization", f"Bearer {self.key}")
            
            _, body = self._http_request(req, timeout=5)
            data = json.loads(body.decode('utf-8'))
            
            # Filter out dummy test rows
            data = [r for r in data if r.get('username') != 'TestUser']
            
            # Deduplicate by client_id (UUID format username) - keep only the best (fastest) score
            user_best = {}
            import re
            uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
            
            for row in data:
                uname = row.get('username', '')
                if uuid_pattern.match(uname):
                    if uname not in user_best or row.get('total_time', 999.0) < user_best[uname].get('total_time', 999.0):
                        user_best[uname] = row
            
            deduped_data = list(user_best.values())
            return deduped_data
        except Exception as e:
            print(e)
            return []

    def submit_score(self, name: str, cpu: str, disk: str, time_seconds: float, cpu_id: str = "", disk_serial: str = "") -> bool:
        try:
            cpu_model = f"{cpu} [{cpu_id}]" if cpu_id and cpu_id != cpu else cpu
            disk_model = f"{disk} [{disk_serial}]" if disk_serial and disk_serial != disk else disk
            
            payload = {
                "username": name,  # Now used as client_id
                "cpu": cpu_model,
                "disk": disk_model,
                "total_time": time_seconds
            }
            
            # Delete previous scores for this client_id
            safe_name = urllib.parse.quote(name)
            del_url = f"{self.url}?username=eq.{safe_name}"
            del_req = urllib.request.Request(del_url, method="DELETE")
            del_req.add_header("apikey", self.key)
            del_req.add_header("Authorization", f"Bearer {self.key}")
            try:
                self._http_request(del_req, timeout=5)
            except Exception:
                pass # Ignore if no previous scores or network issue
                
            req = urllib.request.Request(self.url, data=json.dumps(payload).encode('utf-8'), method="POST")
            req.add_header("apikey", self.key)
            req.add_header("Authorization", f"Bearer {self.key}")
            req.add_header("Content-Type", "application/json")
            
            status_code, _ = self._http_request(req, timeout=5)
            return status_code in [200, 201]
        except Exception:
            return False

leaderboard_service = LeaderboardService()
