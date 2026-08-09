import customtkinter as ctk
import os
import sys
from src.app import AppController

# Load .env file for secrets without needing python-dotenv
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))
    
env_path = os.path.join(base_path, '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip() and not line.startswith('#') and '=' in line:
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = AppController()
    app.mainloop()

if __name__ == "__main__":
    main()
