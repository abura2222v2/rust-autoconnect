import os
import json

base_dir = os.path.join(os.path.dirname(__file__), 'assets', 'i18n')

# We'll map missing English keys to their Russian equivalents. 
# For other languages, we just inject the English string as a fallback so it's not a raw key.
translations = {
    "ru": {
        "nav_home": "Главная",
        "nav_bench": "Бенчмарк",
        "nav_settings": "Настройки",
        "settings_title": "Настройки",
        "lang_lbl": "Язык (Language):",
        "tray_lbl": "Сворачивать в трей при закрытии",
        "swarm_lbl": "Включить Swarm Connect (P2P)",
        "close_btn": "Закрыть",
        "tab_home": "Главная",
        "tab_bench": "Бенчмарк",
        "run_test": "Запустить Тест",
        "lb_title": "Мировой Топ",
        "lb_load": "Загрузка...",
        "lb_err_empty": "Нет результатов.",
        "lb_rank": "Ранг",
        "lb_player": "Игрок",
        "lb_time": "Время",
        "lb_cpu": "Процессор",
        "lb_search": "Поиск по игроку / CPU / Диску..."
    },
    "en": {
        "nav_home": "Home",
        "nav_bench": "Benchmark",
        "nav_settings": "Settings",
        "settings_title": "Settings",
        "lang_lbl": "Language:",
        "tray_lbl": "Minimize to Tray on Close",
        "swarm_lbl": "Enable Swarm Connect (P2P)",
        "close_btn": "Close",
        "tab_home": "Home",
        "tab_bench": "Benchmark",
        "run_test": "Run Test",
        "lb_title": "Global Leaderboard",
        "lb_load": "Loading...",
        "lb_err_empty": "No results.",
        "lb_rank": "Rank",
        "lb_player": "Player",
        "lb_time": "Time",
        "lb_cpu": "CPU",
        "lb_search": "Search Player / CPU / Disk..."
    }
}

for file in os.listdir(base_dir):
    if not file.endswith('.json'):
        continue
        
    path = os.path.join(base_dir, file)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    lang = file.split('.')[0]
    
    # Use localized translations if we have them, else fallback to EN
    dict_to_apply = translations.get(lang, translations["en"])
    
    for k, v in dict_to_apply.items():
        if k not in data:
            data[k] = v
            
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

print("Translation patch complete!")
