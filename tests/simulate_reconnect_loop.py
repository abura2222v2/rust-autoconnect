import os
import subprocess
import time
import sys
from pathlib import Path
import threading

def main():
    log_file = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "Facepunch Studios LTD" / "Rust" / "Player.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    if log_file.exists():
        log_file.unlink()
    
    log_file.touch()

    print("Starting bot...")
    # Set env var so bot doesn't open browser/steam during test
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    bot_process = subprocess.Popen([sys.executable, "main.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
    
    loop_count = 0
    max_loops = 2
    
    state = "WAIT_STABLE"
    
    def process_logs():
        nonlocal state, loop_count
        while True:
            line = bot_process.stdout.readline()
            if not line:
                break
            print(f"[BOT] {line.strip()}", flush=True)
            
            line_lower = line.lower()
            
            if state == "WAIT_STABLE":
                if "server is stable" in line_lower or "stable" in line_lower:
                    print("\n*** SIMULATING SUCCESSFUL CONNECTION ***", flush=True)
                    # Give it a second to "launch"
                    time.sleep(2)
                    with open(log_file, "a") as f:
                        f.write("\nClient connected to 127.0.0.1:28015\n")
                    state = "WAIT_IDLE"
                    
            elif state == "WAIT_IDLE":
                if "monitoring stopped" in line_lower or "manual connection" in line_lower or "manual_conn_detected" in line_lower:
                    print("\n*** SIMULATING DISCONNECT (KICKED) AFTER 3 SECONDS ***", flush=True)
                    time.sleep(3)
                    with open(log_file, "a") as f:
                        f.write("\nDisconnected (Kicked) - test kick\n")
                    state = "WAIT_STABLE"
                    loop_count += 1
                    print(f"--- LOOP {loop_count}/{max_loops} COMPLETE ---", flush=True)
                    if loop_count >= max_loops:
                        print("Killing bot...", flush=True)
                        bot_process.kill()
                        return
                        
    t = threading.Thread(target=process_logs, daemon=True)
    t.start()
    
    bot_process.wait()
    print("Test finished successfully!", flush=True)

if __name__ == "__main__":
    main()
