import json
import os
from pathlib import Path

class I18nManager:
    LANG_MAP = {
        "RU": "RU - Русский",
        "EN": "EN - English",
        "ES": "ES - Español",
        "FR": "FR - Français",
        "DE": "DE - Deutsch",
        "ZH": "ZH - 中文"
    }

    def __init__(self):
        self.lang = "RU"
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
        text = self.translations.get(self.lang, {}).get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except Exception:
                pass
        return text

i18n = I18nManager()
