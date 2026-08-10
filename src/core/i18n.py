import json
import locale
import os
from pathlib import Path


def detect_os_language() -> str:
    """Detect the OS language and return a matching language code (defaulting to EN)."""
    try:
        if os.name == "nt":
            try:
                import ctypes
                lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF
                # 0x19: Russian, 0x09: English, 0x0a: Spanish, 0x0c: French, 0x07: German, 0x04: Chinese, 0x22: Ukrainian
                mapping = {0x19: "RU", 0x09: "EN", 0x0A: "ES", 0x0C: "FR", 0x07: "DE", 0x04: "ZH", 0x22: "UK"}
                if lang_id in mapping:
                    return mapping[lang_id]
            except Exception:
                pass

        lang_env = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
        if lang_env:
            code = lang_env.split("_")[0].upper()
            if code in I18nManager.LANG_MAP:
                return code

        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0]
        if loc:
            loc_str = str(loc).upper()
            if "RU" in loc_str or "RUSSIAN" in loc_str:
                return "RU"
            if "UK" in loc_str or "UKRAINIAN" in loc_str:
                return "UK"
            if "ES" in loc_str or "SPANISH" in loc_str:
                return "ES"
            if "FR" in loc_str or "FRENCH" in loc_str:
                return "FR"
            if "DE" in loc_str or "GERMAN" in loc_str:
                return "DE"
            if "ZH" in loc_str or "CHINESE" in loc_str:
                return "ZH"
            if "EN" in loc_str or "ENGLISH" in loc_str:
                return "EN"
    except Exception:
        pass
    return "EN"


class I18nManager:
    LANG_MAP = {
        "RU": "RU - Русский",
        "UK": "UK - Українська",
        "EN": "EN - English",
        "ES": "ES - Español",
        "FR": "FR - Français",
        "DE": "DE - Deutsch",
        "ZH": "ZH - 中文"
    }

    def __init__(self):
        self.lang = detect_os_language()
        self.translations = {}
        self._load_translations()

    def _load_translations(self):
        base_dir = Path(__file__).parent.parent.parent / "assets" / "i18n"
        for lang_code in self.LANG_MAP.keys():
            file_path = base_dir / f"{lang_code.lower()}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations[lang_code] = json.load(f)
            else:
                self.translations[lang_code] = {}

    def set_lang(self, lang_code: str):
        if lang_code in self.LANG_MAP:
            self.lang = lang_code

    def t(self, key: str, **kwargs) -> str:
        text = self.translations.get(self.lang, {}).get(key)
        if text is None:
            text = self.translations.get("EN", {}).get(key, key)
        
        try:
            return text.format(**kwargs)
        except Exception:
            pass
        return text

i18n = I18nManager()

def _(key: str, **kwargs) -> str:
    return i18n.t(key, **kwargs)

