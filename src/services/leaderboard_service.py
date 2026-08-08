import urllib.request
import json

class LeaderboardService:
    def __init__(self):
        self.url = "https://eznuyydoanefceqmqxqi.supabase.co/rest/v1/benchmarks"
        self.key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV6bnV5eWRvYW5lZmNlcW1xeHFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYxNzAyNDgsImV4cCI6MjEwMTc0NjI0OH0.nCxZbqr3m0r242kUBY3RSpF_iwh7vRtBw_nVTxwe-tI"

    def fetch_top_30(self) -> list:
        try:
            req = urllib.request.Request(f"{self.url}?select=*&order=time_seconds.asc&limit=30")
            req.add_header("apikey", self.key)
            req.add_header("Authorization", f"Bearer {self.key}")
            with urllib.request.urlopen(req, timeout=5) as res:
                return json.loads(res.read().decode('utf-8'))
        except Exception:
            return []

    def submit_score(self, name: str, cpu: str, disk: str, time_seconds: float) -> bool:
        try:
            payload = {
                "player_name": name,
                "cpu_model": cpu,
                "disk_model": disk,
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
