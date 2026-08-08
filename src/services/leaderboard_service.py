import urllib.request
import json

class LeaderboardService:
    def __init__(self):
        self.url = "https://eznuyydoanefceqmqxqi.supabase.co/rest/v1/benchmarks"
        self.key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV6bnV5eWRvYW5lZmNlcW1xeHFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYxNzAyNDgsImV4cCI6MjEwMTc0NjI0OH0.nCxZbqr3m0r242kUBY3RSpF_iwh7vRtBw_nVTxwe-tI"

    def fetch_leaderboard(self, limit: int = 30, offset: int = 0, search_query: str = "") -> list:
        try:
            url = f"{self.url}?select=*&order=time_seconds.asc&limit={limit}&offset={offset}"
            if search_query:
                # Add basic search filter using Supabase ilike
                import urllib.parse
                sq = urllib.parse.quote(f"%{search_query}%")
                url += f"&or=(player_name.ilike.{sq},cpu_model.ilike.{sq},disk_model.ilike.{sq})"
                
            req = urllib.request.Request(url)
            req.add_header("apikey", self.key)
            req.add_header("Authorization", f"Bearer {self.key}")
            with urllib.request.urlopen(req, timeout=5) as res:
                return json.loads(res.read().decode('utf-8'))
        except Exception as e:
            print(e)
            return []

    def submit_score(self, name: str, cpu: str, disk: str, time_seconds: float, cpu_id: str = "", disk_serial: str = "") -> bool:
        try:
            payload = {
                "player_name": name,
                "cpu_model": f"{cpu} [{cpu_id}]" if cpu_id else cpu,
                "disk_model": f"{disk} [{disk_serial}]" if disk_serial else disk,
                "time_seconds": time_seconds
            }
            req = urllib.request.Request(self.url, data=json.dumps(payload).encode('utf-8'), method="POST")
            req.add_header("apikey", self.key)
            req.add_header("Authorization", f"Bearer {self.key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.getcode() in [200, 201]
        except Exception:
            return False

leaderboard_service = LeaderboardService()
