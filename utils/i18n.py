"""
Internationalisierung (i18n) für TelegramForwarder.

Lädt Übersetzungen aus ``lang/<code>.json`` und liefert sie über die Funktion
``t(key, **kwargs)`` aus.

Designentscheidungen (siehe docs/i18n.md):
  - Die Sprache wird global über die Umgebungsvariable ``LANGUAGE`` gewählt.
  - Standardsprache ist Deutsch (``de``), wenn ``LANGUAGE`` nicht gesetzt ist.
  - Fallback-Kette pro Schlüssel: aktive Sprache -> ``zh`` (Quellsprache) -> Schlüsselname.
  - Platzhalter werden über ``str.format(**kwargs)`` eingesetzt.

Dieses Modul ist bewusst eigenständig (eigener ``load_dotenv``-Aufruf) und ohne
Abhängigkeit zu projektinternen Modulen, um Importzyklen zu vermeiden.
"""

import os
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# .env laden, falls noch nicht geschehen (idempotent)
load_dotenv()

# Verzeichnis mit den Sprachdateien (lang/de.json, lang/en.json, lang/zh.json)
LANG_DIR = Path(__file__).parent.parent / "lang"

# Standardsprache, falls LANGUAGE nicht gesetzt ist
DEFAULT_LANGUAGE = "de"
# Fallback-Sprache (Quellsprache des Upstream-Projekts) für fehlende Schlüssel
FALLBACK_LANGUAGE = "zh"

# Cache: { sprachcode: { schlüssel: text } }
_translations = {}
# Aktive Sprache (wird beim ersten Zugriff ermittelt)
_active_language = None


def get_language():
    """Aktive Sprache ermitteln (gecacht). Liest LANGUAGE aus der Umgebung."""
    global _active_language
    if _active_language is None:
        lang = os.getenv("LANGUAGE")
        _active_language = (lang or DEFAULT_LANGUAGE).strip().lower()
    return _active_language


def set_language(lang):
    """Aktive Sprache zur Laufzeit setzen (v. a. für Tests/Reload nützlich)."""
    global _active_language
    _active_language = (lang or DEFAULT_LANGUAGE).strip().lower()
    return _active_language


def _load_language(lang):
    """Sprachdatei laden und cachen. Gibt ein (ggf. leeres) Dict zurück."""
    if lang in _translations:
        return _translations[lang]

    path = LANG_DIR / f"{lang}.json"
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning("i18n: Sprachdatei nicht gefunden: %s", path)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("i18n: Fehler beim Laden der Sprachdatei %s: %s", path, e)

    _translations[lang] = data
    return data


def reload():
    """Cache leeren (Sprachdateien werden beim nächsten Zugriff neu geladen)."""
    global _translations, _active_language
    _translations = {}
    _active_language = None


def t(key, **kwargs):
    """Übersetzten Text für ``key`` in der aktiven Sprache zurückgeben.

    Fallback-Kette: aktive Sprache -> ``zh`` -> ``key`` selbst.
    Platzhalter werden via ``str.format(**kwargs)`` ersetzt.
    """
    lang = get_language()

    text = _load_language(lang).get(key)
    if text is None and lang != FALLBACK_LANGUAGE:
        text = _load_language(FALLBACK_LANGUAGE).get(key)

    if text is None:
        logger.warning("i18n: fehlender Übersetzungsschlüssel: %s", key)
        return key

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError) as e:
            logger.error("i18n: Format-Fehler für Schlüssel '%s': %s", key, e)
            return text

    return text
