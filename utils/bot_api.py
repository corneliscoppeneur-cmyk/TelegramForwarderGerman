"""Direkte Aufrufe der Telegram Bot-HTTP-API (api.telegram.org).

Telethon spricht MTProto und kennt neue Bot-API-Funktionen wie ``sendWidget``
(Bot API 10.4) nicht. Für diese Fälle ruft der Bot die HTTP-API parallel zur
laufenden Telethon-Bot-Session auf – das ist erlaubt, beide nutzen denselben
``BOT_TOKEN``. Antworten der HTTP-API enthalten den Token nicht; Fehler werden
ohne Token geloggt.
"""
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

API_BASE = 'https://api.telegram.org'
DEFAULT_TIMEOUT = 15


class BotApiError(Exception):
    """Fehlerantwort der Bot-API (``ok: false``) oder Transportfehler."""

    def __init__(self, method, code, description):
        super().__init__(f'{method}: [{code}] {description}')
        self.method = method
        self.code = code
        self.description = description


async def call(method, token=None, timeout=DEFAULT_TIMEOUT, **params):
    """``POST /bot<token>/<method>`` mit JSON-Body. Gibt ``result`` zurück.

    ``None``-Werte werden weggelassen; verschachtelte Objekte (z. B.
    ``reply_markup``) gehen als JSON mit.
    """
    token = token or os.getenv('BOT_TOKEN')
    if not token:
        raise BotApiError(method, 0, 'BOT_TOKEN fehlt')

    payload = {k: v for k, v in params.items() if v is not None}
    url = f'{API_BASE}/bot{token}/{method}'
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
    except Exception as e:  # Netzwerk/Timeout – Token nicht in der Meldung
        raise BotApiError(method, 0, f'Transportfehler: {type(e).__name__}: {e}') from e

    if not isinstance(data, dict) or not data.get('ok'):
        code = data.get('error_code') if isinstance(data, dict) else None
        desc = data.get('description') if isinstance(data, dict) else str(data)[:200]
        raise BotApiError(method, code, desc)
    return data['result']


async def get_me(token=None):
    return await call('getMe', token=token)


async def send_widget(chat_id, html, caption=None, parse_mode='HTML', width=None,
                      height=None, allow_queries=False, reply_markup=None, token=None):
    """``sendWidget`` (Bot API 10.4): HTML-Widget in einen Privatchat senden.

    Grenzen laut API: HTML 1–32768 Bytes, zlib-komprimiert ≤ 4096 Bytes,
    Caption ≤ 1024 Zeichen. Clients ohne Widget-Unterstützung zeigen nur die
    Caption – darum immer eine aussagekräftige Caption mitgeben.
    """
    return await call(
        'sendWidget', token=token,
        chat_id=chat_id, html=html, caption=caption,
        parse_mode=parse_mode if caption else None,
        width=width, height=height,
        allow_queries=True if allow_queries else None,
        reply_markup=reply_markup,
    )
