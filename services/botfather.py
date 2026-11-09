"""Bots automatisch bei @BotFather anlegen – über eine Session-Manager-Session
und den telegram-mcp-Server.

Der Forwarder selbst hat keinen Zugriff auf ein Nutzerkonto, das Bots anlegen
darf. Deshalb spricht er über den MCP-Server (eigene Instanz ``telegram-mcp-
botfather``, eine dedizierte SM-Session) mit @BotFather wie ein Mensch:
``/newbot`` → Name → Benutzername → Token. Eine Session darf höchstens 20 Bots
besitzen; danach meldet BotFather das, und der Admin trägt im MCP-Adapter die
nächste Session ein.

Konfiguration (.env):
    BOTFATHER_MCP_URL      z. B. http://telegram-mcp-botfather:8765/mcp
    BOTFATHER_MCP_ACCOUNT  Account-Label im MCP (Telefonnummer ohne +), optional
                           wenn die Instanz nur eine Session hält

Der Token wird nie geloggt; er geht nur an den Deploy.
"""
import asyncio
import json
import logging
import os
import re
import time

from utils.mcp_client import McpClient, McpError

logger = logging.getLogger(__name__)

BOTFATHER = 'BotFather'
TOKEN_RE = re.compile(r'(\d{5,}:[A-Za-z0-9_-]{30,})')
USERNAME_RE = re.compile(r'[^a-z0-9_]')

# BotFather antwortet in der Regel in < 2 s; Puffer für Lastspitzen.
REPLY_TIMEOUT = 25
POLL_INTERVAL = 0.7
MAX_USERNAME_TRIES = 5
# Nach einem Fehlschlag wegen Rate-Limit so lange keinen neuen Versuch
RATE_LIMIT_COOLDOWN = 60

_cooldown_until = 0.0


class BotFatherError(Exception):
    """Dialog mit BotFather fehlgeschlagen (Text ist admin-tauglich, ohne Token)."""


class AccountExhausted(BotFatherError):
    """Die Session hat ihr Bot-Limit erreicht – nächste Session nötig."""


class RateLimited(BotFatherError):
    """BotFather bremst („too many attempts") – später erneut."""


def is_configured():
    return bool((os.getenv('BOTFATHER_MCP_URL') or '').strip())


def suggest_username(base, customer_id):
    """Gültigen Bot-Benutzernamen bauen: a-z0-9_, 5–32 Zeichen, endet auf ``bot``."""
    slug = USERNAME_RE.sub('', (base or '').lower().replace('-', '_'))
    if len(slug) < 3:
        slug = f'kunde{abs(int(customer_id)) % 100000}'
    slug = slug[:18].strip('_') or f'kunde{abs(int(customer_id)) % 100000}'
    return f'{slug}_forward_bot'


class BotFatherClient:
    def __init__(self, url=None, account=None):
        self.url = (url or os.getenv('BOTFATHER_MCP_URL') or '').strip()
        if not self.url:
            raise BotFatherError('BOTFATHER_MCP_URL nicht gesetzt')
        self.account = (account or os.getenv('BOTFATHER_MCP_ACCOUNT') or '').strip() or None
        self.mcp = McpClient(self.url)

    # ---- MCP-Primitiven -------------------------------------------------

    def _args(self, **kwargs):
        if self.account:
            kwargs['account'] = self.account
        return kwargs

    async def _history(self, limit=3):
        raw = await self.mcp.call_tool('get_history', self._args(chat_id=BOTFATHER, limit=limit))
        try:
            data = json.loads(raw)
        except ValueError:
            raise BotFatherError(f'Unerwartete Verlaufsantwort: {raw[:120]}')
        return data.get('results') or []

    async def _last_incoming_id(self):
        for rec in await self._history(limit=3):
            if not rec.get('out'):
                return int(rec.get('id') or 0)
        return 0

    async def _ask(self, text):
        """Nachricht an BotFather senden und auf die nächste Antwort warten."""
        before = await self._last_incoming_id()
        await self.mcp.call_tool('send_message', self._args(chat_id=BOTFATHER, message=text))
        deadline = time.monotonic() + REPLY_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            for rec in await self._history(limit=3):
                if rec.get('out'):
                    continue
                if int(rec.get('id') or 0) > before:
                    return rec.get('text') or ''
        raise BotFatherError('BotFather hat nicht geantwortet (Timeout)')

    # ---- Fachlogik ------------------------------------------------------

    @staticmethod
    def _check_common_errors(reply):
        low = reply.lower()
        if 'too many attempts' in low or 'try again' in low and 'second' in low:
            raise RateLimited(reply[:200])
        if 'too many bots' in low or ("that i cannot do" in low and 'bot' in low):
            raise AccountExhausted(reply[:200])

    async def create_bot(self, display_name, username_base, customer_id):
        """Neuen Bot anlegen. Gibt ``(token, bot_username)`` zurück."""
        global _cooldown_until
        if time.monotonic() < _cooldown_until:
            raise RateLimited('BotFather-Cooldown aktiv, bitte in einer Minute erneut')

        try:
            # Laufenden Dialog sauber abbrechen, dann /newbot
            await self._ask('/cancel')
            reply = await self._ask('/newbot')
            self._check_common_errors(reply)
            if 'name' not in reply.lower():
                raise BotFatherError(f'Unerwartete Antwort auf /newbot: {reply[:120]}')

            reply = await self._ask(display_name[:64])
            self._check_common_errors(reply)
            if 'username' not in reply.lower():
                raise BotFatherError(f'Unerwartete Antwort auf den Namen: {reply[:120]}')

            base = suggest_username(username_base, customer_id)
            stem = base[:-len('_forward_bot')]
            for attempt in range(MAX_USERNAME_TRIES):
                username = base if attempt == 0 else f'{stem}_{attempt + 1}_forward_bot'
                reply = await self._ask(username)
                self._check_common_errors(reply)
                match = TOKEN_RE.search(reply)
                if match:
                    logger.info(f'BotFather: Bot @{username} für Kunde {customer_id} angelegt')
                    return match.group(1), username
                low = reply.lower()
                if 'already taken' in low or 'sorry' in low or 'invalid' in low:
                    continue
                raise BotFatherError(f'Unerwartete Antwort auf den Benutzernamen: {reply[:120]}')
            raise BotFatherError('Kein freier Benutzername gefunden')
        except RateLimited:
            _cooldown_until = time.monotonic() + RATE_LIMIT_COOLDOWN
            raise
        except McpError as e:
            raise BotFatherError(f'MCP-Fehler: {e}') from e

    async def set_description(self, bot_username, text):
        """Beschreibung setzen (best effort, Fehler nur loggen)."""
        try:
            await self._ask('/setdescription')
            await self._ask(f'@{bot_username}')
            await self._ask(text[:512])
        except Exception as e:
            logger.warning(f'BotFather: Beschreibung für @{bot_username} nicht gesetzt: {e}')
