import customtkinter as ctk
from src.app import AppController

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = AppController()
    app.mainloop()

if __name__ == "__main__":
    main()
