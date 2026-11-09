"""Farbige Inline-Buttons – vorwärts- und rückwärtskompatibel.

Bot API 10.3 führt ``InlineKeyboardButton.style`` ein
(``"danger"`` = rot, ``"success"`` = grün, ``"primary"`` = blau).

Telethon >= 1.45 (Layer 229) bietet dafür ``Button.inline(text, data, style=…)``
und ``Button.url(text, url, style=…)``. Ältere Telethon-Versionen (z. B. 1.38 in
noch nicht neu gebauten Kunden-Containern) kennen den Parameter nicht. Damit
Bestandscontainer NICHT brechen, setzt ``styled_inline`` die Farbe nur, wenn
die installierte Telethon-Version sie unterstützt. Andernfalls verhält sich der
Helfer exakt wie ``telethon.Button.inline``.
"""

import inspect
import logging

from telethon import Button

logger = logging.getLogger(__name__)

# Erlaubte Stile laut Bot API 10.3
STYLE_DANGER = 'danger'    # rot
STYLE_SUCCESS = 'success'  # grün
STYLE_PRIMARY = 'primary'  # blau


def _telethon_supports_style():
    """Prüft einmalig, ob ``Button.inline`` einen ``style``-Parameter kennt."""
    try:
        return 'style' in inspect.signature(Button.inline).parameters
    except Exception:
        return False


_SUPPORTS_STYLE = _telethon_supports_style()


def supports_style():
    """True, wenn die laufende Telethon-Version farbige Buttons kann."""
    return _SUPPORTS_STYLE


def styled_inline(text, data, style=None):
    """Inline-Callback-Button, optional farbig.

    Args:
        text: Beschriftung.
        data: Callback-Daten.
        style: ``STYLE_DANGER`` | ``STYLE_SUCCESS`` | ``STYLE_PRIMARY`` oder None.

    Die Farbe wird nur gesetzt, wenn Telethon sie unterstützt (sonst identisch
    zu ``Button.inline``).
    """
    if style and _SUPPORTS_STYLE:
        try:
            return Button.inline(text, data, style=style)
        except Exception as e:
            logger.debug(f'Button-Style {style!r} nicht gesetzt: {e}')
    return Button.inline(text, data)


def styled_url(text, url, style=None):
    """URL-Button, optional farbig (gleiche Regeln wie ``styled_inline``)."""
    if style and _SUPPORTS_STYLE:
        try:
            return Button.url(text, url, style=style)
        except Exception as e:
            logger.debug(f'Button-Style {style!r} nicht gesetzt: {e}')
    return Button.url(text, url)
