"""HTML-Widgets (Bot API 10.4) rendern und senden.

Vorlagen liegen in ``widgets/<name>.html`` (Jinja2, Autoescape). Ein Widget ist
ein einzelnes HTML-Dokument ohne externe Ressourcen; Telegram zeichnet es in
der Chat-Optik (CSS-Variablen ``--tg-theme-*``). Grenzen: 32768 Bytes HTML und
4096 Bytes nach zlib-Kompression (Stufe 9).

``send`` liefert ``False``, wenn das Widget nicht gesendet werden konnte –
der Aufrufer schickt dann seine bisherige Textnachricht als Fallback.
"""
import logging
import zlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils import bot_api
from utils.i18n import t

logger = logging.getLogger(__name__)

WIDGET_DIR = Path(__file__).parent.parent / 'widgets'
MAX_HTML_BYTES = 32768
MAX_ZLIB_BYTES = 4096

_env = Environment(
    loader=FileSystemLoader(str(WIDGET_DIR)),
    autoescape=select_autoescape(['html']),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals['t'] = t

_bot_username = None


class WidgetTooLarge(ValueError):
    pass


def render(name, **ctx):
    """Vorlage rendern und Größenlimits prüfen."""
    html = _env.get_template(f'{name}.html').render(**ctx)
    raw = html.encode('utf-8')
    if len(raw) > MAX_HTML_BYTES:
        raise WidgetTooLarge(f'{name}: {len(raw)} Bytes HTML (max {MAX_HTML_BYTES})')
    packed = len(zlib.compress(raw, 9))
    if packed > MAX_ZLIB_BYTES:
        raise WidgetTooLarge(f'{name}: {packed} Bytes komprimiert (max {MAX_ZLIB_BYTES})')
    return html


async def bot_username():
    """Bot-Nutzername (ohne @) für Deeplinks, einmalig per getMe geholt."""
    global _bot_username
    if _bot_username is None:
        me = await bot_api.get_me()
        _bot_username = me.get('username')
    return _bot_username


async def deeplink(start_param):
    """``https://t.me/<bot>?start=<param>`` – öffnet den Bot-Chat mit Parameter."""
    username = await bot_username()
    return f'https://t.me/{username}?start={start_param}' if username else None


async def send(chat_id, name, caption=None, **ctx):
    """Widget senden. True bei Erfolg, False wenn der Aufrufer den Text-Fallback schicken soll."""
    try:
        html = render(name, **ctx)
        await bot_api.send_widget(chat_id, html, caption=caption)
        return True
    except Exception as e:
        logger.warning(f'Widget {name!r} nicht gesendet, Text-Fallback: {e}')
        return False
