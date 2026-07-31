"""
i18n.py — Internationalization (i18n) Core Manager for ZerynBot V2.
Loads all JSON locale files from locales/ at startup into memory for O(1) lookup.

Supported languages: vi, en, zh, es, pt, fr
Default language: vi
"""
import os
import json
import logging
from typing import Dict

logger = logging.getLogger("i18n")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
DEFAULT_LANG = "vi"


class I18nManager:
    """Singleton manager that loads all locale JSON files into RAM on startup."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.translations: Dict[str, dict] = {}
            cls._instance.available_languages: Dict[str, str] = {}
            cls._instance._load()
        return cls._instance

    def _load(self):
        """Scan locales/ and load all *.json files into RAM."""
        self.translations.clear()
        self.available_languages.clear()

        os.makedirs(LOCALES_DIR, exist_ok=True)

        for filename in sorted(os.listdir(LOCALES_DIR)):
            if not filename.endswith(".json"):
                continue
            lang_code = filename[:-5].lower()
            path = os.path.join(LOCALES_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.translations[lang_code] = data
                name = data.get("lang.name", lang_code.upper())
                flag = data.get("lang.flag", "")
                self.available_languages[lang_code] = f"{flag} {name}".strip()
                logger.info(f"[i18n] Loaded locale: '{lang_code}' — {flag} {name}")
            except Exception as e:
                logger.error(f"[i18n] Failed to load '{filename}': {e}")

    def reload(self):
        """Hot-reload all locales without restarting the process."""
        self._load()
        logger.info("[i18n] Reloaded all locales.")

    def get_supported_languages(self) -> Dict[str, str]:
        """Return {lang_code: 'flag name'} — e.g. {'vi': '🇻🇳 Tiếng Việt'}."""
        return self.available_languages

    def translate(self, lang: str, key: str, default: str = None, **kwargs) -> str:
        """
        Translate a key for the given language.
        Fallback chain: requested lang → DEFAULT_LANG (vi) → default param → key name.
        """
        lang = (lang or DEFAULT_LANG).lower()

        # Primary lookup
        value = self.translations.get(lang, {}).get(key)

        # Fallback to default language
        if value is None:
            value = self.translations.get(DEFAULT_LANG, {}).get(key)

        # Final fallback
        if value is None:
            value = default if default is not None else key

        # Format string placeholders
        if kwargs:
            try:
                return value.format(**kwargs)
            except Exception as e:
                logger.warning(f"[i18n] Format error key='{key}' lang='{lang}': {e}")

        return value


# ── Singleton instance ──────────────────────────────────────────────────────────
i18n = I18nManager()


def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """
    Translation helper for explicit lang code.
    Used in Jinja2 templates (Flask Dashboard).

    Example:
        {{ t('dashboard.home', lang=current_ui_lang) }}
    """
    return i18n.translate(lang, key, **kwargs)


def tr(guild_settings_or_lang, key: str, **kwargs) -> str:
    """
    Translation helper for Discord Bot.
    Accepts a guild_settings dict (reads 'language' key) OR a lang code string.

    Examples:
        settings = await async_get_guild_settings(guild_id)
        await ctx.send(tr(settings, "music.skipped"))

        await ctx.send(tr("en", "music.now_playing", title="Lofi Girl"))
    """
    if isinstance(guild_settings_or_lang, dict):
        lang = guild_settings_or_lang.get("language", DEFAULT_LANG)
    elif isinstance(guild_settings_or_lang, str):
        lang = guild_settings_or_lang
    else:
        lang = DEFAULT_LANG
    return i18n.translate(lang, key, **kwargs)
