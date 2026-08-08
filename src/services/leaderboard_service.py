import urllib.request
import json

class LeaderboardService:
    def __init__(self):
        self.url = "https://eznuyydoanefceqmqxqi.supabase.co/rest/v1/benchmarks"
        self.key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV6bnV5eWRvYW5lZmNlcW1xeHFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYxNzAyNDgsImV4cCI6MjEwMTc0NjI0OH0.nCxZbqr3m0r242kUBY3RSpF_iwh7vRtBw_nVTxwe-tI"

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
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode('utf-8'))
                
                # Filter out dummy test rows
                data = [r for r in data if r.get('username') != 'TestUser']
                
                # Deduplicate by client_id (UUID format username) - keep only the best (fastest) score
                user_best = {}
                deduped_data = []
                import re
                uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
                
                for row in data:
                    uname = row.get('username', '')
                    if uuid_pattern.match(uname):
                        if uname not in user_best or row.get('total_time', 999.0) < user_best[uname].get('total_time', 999.0):
                            user_best[uname] = row
                    else:
                        deduped_data.append(row)
                
                deduped_data.extend(user_best.values())
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
            del_url = f"{self.url}?username=eq.{name}"
            del_req = urllib.request.Request(del_url, method="DELETE")
            del_req.add_header("apikey", self.key)
            del_req.add_header("Authorization", f"Bearer {self.key}")
            try:
                urllib.request.urlopen(del_req, timeout=5)
            except:
                pass # Ignore if no previous scores or network issue
                
            req = urllib.request.Request(self.url, data=json.dumps(payload).encode('utf-8'), method="POST")
            req.add_header("apikey", self.key)
            req.add_header("Authorization", f"Bearer {self.key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.getcode() in [200, 201]
        except Exception:
            return False

leaderboard_service = LeaderboardService()
