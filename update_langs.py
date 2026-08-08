import json
import os

langs = {
    "de.json": {
        "tab_bench": "Benchmark",
        "run_test": "Test ausf\u00fchren",
        "top_30": "Globale Top 30",
        "loading_hw": "Lade Hardware-Infos...",
        "settings_title": "Einstellungen",
        "lang_lbl": "Sprache:",
        "tray_lbl": "In den Tray minimieren",
        "close_btn": "Schlie\u00dfen",
        "lb_title": "🏆 Top 30 🏆",
        "lb_rank": "Rang",
        "lb_player": "Spieler",
        "lb_time": "Zeit (s)",
        "lb_cpu": "Prozessor",
        "lb_disk": "Festplatte",
        "lb_load": "Lade Daten...",
        "lb_err_conf": "Supabase nicht konfiguriert.",
        "lb_err_conn": "Verbindung zu Supabase fehlgeschlagen.",
        "lb_err_empty": "Noch keine Benchmarks aufgezeichnet.",
        "swarm_lbl": "Netzwerkbeschleunigung (Swarm Connect)",
        "bench_copy_lbl": "Erlaube das Kopieren von Benchmark-Dateien ins Spiel (Auf eigene Gefahr)"
    },
    "es.json": {
        "tab_bench": "Benchmark",
        "run_test": "Ejecutar prueba",
        "top_30": "Top 30 Global",
        "loading_hw": "Cargando info. de hardware...",
        "settings_title": "Configuraci\u00f3n",
        "lang_lbl": "Idioma:",
        "tray_lbl": "Minimizar a la bandeja",
        "close_btn": "Cerrar",
        "lb_title": "🏆 Top 30 🏆",
        "lb_rank": "Rango",
        "lb_player": "Jugador",
        "lb_time": "Tiempo (s)",
        "lb_cpu": "Procesador",
        "lb_disk": "Disco",
        "lb_load": "Cargando datos...",
        "lb_err_conf": "Supabase no est\u00e1 configurado.",
        "lb_err_conn": "Error al conectar con Supabase.",
        "lb_err_empty": "A\u00fan no hay benchmarks registrados.",
        "swarm_lbl": "Aceleraci\u00f3n de Red (Swarm Connect)",
        "bench_copy_lbl": "Permitir copiar archivos de benchmark al juego (Bajo su riesgo)"
    },
    "fr.json": {
        "tab_bench": "Benchmark",
        "run_test": "Lancer le test",
        "top_30": "Top 30 Mondial",
        "loading_hw": "Chargement du mat\u00e9riel...",
        "settings_title": "Param\u00e8tres",
        "lang_lbl": "Langue :",
        "tray_lbl": "R\u00e9duire dans la barre d'\u00e9tat",
        "close_btn": "Fermer",
        "lb_title": "🏆 Top 30 🏆",
        "lb_rank": "Rang",
        "lb_player": "Joueur",
        "lb_time": "Temps (s)",
        "lb_cpu": "Processeur",
        "lb_disk": "Disque",
        "lb_load": "Chargement des donn\u00e9es...",
        "lb_err_conf": "Supabase non configur\u00e9.",
        "lb_err_conn": "\u00c9chec de connexion \u00e0 Supabase.",
        "lb_err_empty": "Aucun benchmark enregistr\u00e9.",
        "swarm_lbl": "Acc\u00e9l\u00e9ration r\u00e9seau (Swarm Connect)",
        "bench_copy_lbl": "Autoriser la copie des fichiers de benchmark (\u00c0 vos risques)"
    },
    "zh.json": {
        "tab_bench": "\u57fa\u51c6\u6d4b\u8bd5",
        "run_test": "\u8fd0\u884c\u6d4b\u8bd5",
        "top_30": "\u5168\u7403\u524d30\u540d",
        "loading_hw": "\u52a0\u8f7d\u786c\u4ef6\u4fe1\u606f...",
        "settings_title": "\u8bbe\u7f6e",
        "lang_lbl": "\u8bed\u8a00:",
        "tray_lbl": "\u6700\u5c0f\u5316\u5230\u6258\u76d8",
        "close_btn": "\u5173\u95ed",
        "lb_title": "🏆 Top 30 🏆",
        "lb_rank": "\u6392\u540d",
        "lb_player": "\u73a9\u5bb6",
        "lb_time": "\u65f6\u95f4 (\u79d2)",
        "lb_cpu": "\u5904\u7406\u5668",
        "lb_disk": "\u78c1\u76d8",
        "lb_load": "\u52a0\u8f7d\u6570\u636e\u4e2d...",
        "lb_err_conf": "\u672a\u914d\u7f6e Supabase\u3002",
        "lb_err_conn": "\u65e0\u6cd5\u8fde\u63a5\u5230 Supabase\u3002",
        "lb_err_empty": "\u6682\u65e0\u57fa\u51c6\u6d4b\u8bd5\u8bb0\u5f55\u3002",
        "swarm_lbl": "\u7f51\u7edc\u52a0\u901f (Swarm Connect)",
        "bench_copy_lbl": "\u5141\u8bb8\u590d\u5236\u57fa\u51c6\u6d4b\u8bd5\u6587\u4ef6\u5230\u6e38\u620f\u6587\u4ef6\u5939\uff08\u98ce\u9669\u81ea\u8d1f\uff09"
    }
}

base_dir = r"c:\Users\abura\Desktop\autoconnect rust\assets\i18n"
for filename, keys in langs.items():
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k, v in keys.items():
            if k not in data:
                data[k] = v
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
print("Translations updated successfully.")
