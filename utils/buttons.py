"""Farbige Inline-Buttons – vorwärtskompatibel.

Bot API 10.3 führt ``InlineKeyboardButton.style`` ein
(``"danger"`` = rot, ``"success"`` = grün, ``"primary"`` = blau).

Telethon 1.38.1 (aktuell in den Kunden-Containern) kennt dieses Feld noch
nicht. Damit die Bestandscontainer NICHT brechen, setzt ``styled_inline`` die
Farbe nur, wenn die installierte Telethon-Version sie unterstützt. Andernfalls
verhält sich der Helfer exakt wie ``telethon.Button.inline`` – gleiche Buttons
wie bisher, nur ohne Farbe. Nach einem geprüften Telethon-Upgrade werden die
Farben automatisch aktiv, ohne weitere Code-Änderung.
"""

import inspect
import logging

from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

logger = logging.getLogger(__name__)

# Erlaubte Stile laut Bot API 10.3
STYLE_DANGER = 'danger'    # rot
STYLE_SUCCESS = 'success'  # grün
STYLE_PRIMARY = 'primary'  # blau


def _telethon_supports_style():
    """Prüft einmalig, ob KeyboardButtonCallback ein ``style``-Feld kennt."""
    try:
        params = inspect.signature(KeyboardButtonCallback.__init__).parameters
        return 'style' in params
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
    btn = Button.inline(text, data)
    if style and _SUPPORTS_STYLE:
        try:
            btn.style = style
        except Exception:
            pass
    return btn
