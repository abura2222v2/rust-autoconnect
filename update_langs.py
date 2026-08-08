import json
import os
import logging

logger = logging.getLogger(__name__)

langs = {
    "de.json": {
        "tab_bench": "Benchmark",
        "run_test": "Test ausführen",
        "top_30": "Globale Top 30",
        "loading_hw": "Lade Hardware-Infos...",
        "settings_title": "Einstellungen",
        "lang_lbl": "Sprache:",
        "tray_lbl": "In den Tray minimieren",
        "close_btn": "Schließen",
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
        "settings_title": "Configuración",
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
        "lb_err_conf": "Supabase no está configurado.",
        "lb_err_conn": "Error al conectar con Supabase.",
        "lb_err_empty": "Aún no hay benchmarks registrados.",
        "swarm_lbl": "Aceleración de Red (Swarm Connect)",
        "bench_copy_lbl": "Permitir copiar archivos de benchmark al juego (Bajo su riesgo)"
    },
    "fr.json": {
        "tab_bench": "Benchmark",
        "run_test": "Lancer le test",
        "top_30": "Top 30 Mondial",
        "loading_hw": "Chargement du matériel...",
        "settings_title": "Paramètres",
        "lang_lbl": "Langue :",
        "tray_lbl": "Réduire dans la barre d'état",
        "close_btn": "Fermer",
        "lb_title": "🏆 Top 30 🏆",
        "lb_rank": "Rang",
        "lb_player": "Joueur",
        "lb_time": "Temps (s)",
        "lb_cpu": "Processeur",
        "lb_disk": "Disque",
        "lb_load": "Chargement des données...",
        "lb_err_conf": "Supabase non configuré.",
        "lb_err_conn": "Échec de connexion à Supabase.",
        "lb_err_empty": "Aucun benchmark enregistré.",
        "swarm_lbl": "Accélération réseau (Swarm Connect)",
        "bench_copy_lbl": "Autoriser la copie des fichiers de benchmark (À vos risques)"
    },
    "zh.json": {
        "tab_bench": "基准测试",
        "run_test": "运行测试",
        "top_30": "全球前30名",
        "loading_hw": "加载硬件信息...",
        "settings_title": "设置",
        "lang_lbl": "语言:",
        "tray_lbl": "最小化到托盘",
        "close_btn": "关闭",
        "lb_title": "🏆 Top 30 🏆",
        "lb_rank": "排名",
        "lb_player": "玩家",
        "lb_time": "时间 (秒)",
        "lb_cpu": "处理器",
        "lb_disk": "磁盘",
        "lb_load": "加载数据中...",
        "lb_err_conf": "未配置 Supabase。",
        "lb_err_conn": "无法连接到 Supabase。",
        "lb_err_empty": "暂无基准测试记录。",
        "swarm_lbl": "网络加速 (Swarm Connect)",
        "bench_copy_lbl": "允许复制基准测试文件到游戏文件夹（风险自负）"
    }
}

base_dir = os.path.join(os.path.dirname(__file__), 'assets', 'i18n')
for filename, keys in langs.items():
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for k, v in keys.items():
                if k not in data:
                    data[k] = v
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error updating {filename}: {e}", exc_info=True)
            print(f"Error updating {filename}: {e}")

print("Translations updated successfully.")
