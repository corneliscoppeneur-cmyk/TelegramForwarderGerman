"""Menüs als HTML-Widget mit Knöpfen (Bot API 10.4) statt Inline-Buttons.

Ein Widget zeichnet native Knöpfe direkt in der Nachricht. Ein Knopf kann den
Bot nicht direkt aufrufen, aber einen Deeplink öffnen:
``https://t.me/<bot>?start=cb_<aktion>``. Der Client schickt daraufhin
``/start cb_<aktion>``; :func:`run_deeplink_action` setzt das in den bereits
vorhandenen Callback-Handler um (``CALLBACK_HANDLERS``), indem es eine
Platzhalter-Nachricht sendet und dem Handler ein Event-Objekt mit derselben
Schnittstelle wie ``events.CallbackQuery`` übergibt. So bleiben alle Abläufe
(Assistent, Übersicht, Abo, Login, Onboarding) unverändert.

Clients ohne Widget-Unterstützung sehen nur die Caption – darum steht dort
der Hinweis auf ``/menu`` (klassische Inline-Buttons).
"""
import logging
import re

from utils import widgets
from utils.i18n import t

logger = logging.getLogger(__name__)

DEEPLINK_PREFIX = 'cb_'
_DEEPLINK_RE = re.compile(r'^/start(?:@\w+)?\s+' + DEEPLINK_PREFIX + r'([A-Za-z0-9_]{1,60})\s*$')

# Aktionen, die Kunden/Admins über Widget-Knöpfe auslösen dürfen
MENU_ACTIONS = frozenset({
    'wizard_start', 'menu_rules', 'menu_help', 'menu_main', 'sub_billing',
    'login_start', 'sales',
})
# Aktionen für Fremde im Main-Bot (Onboarding)
ONBOARDING_ACTIONS = frozenset({
    'onboard_auto_create', 'onboard_create_bot', 'onboard_request',
    'onboard_selfbot', 'onboard_how', 'onboard_home',
})


def parse_deeplink(text):
    """``/start cb_<aktion>`` → ``<aktion>`` oder None."""
    match = _DEEPLINK_RE.match((text or '').strip())
    return match.group(1) if match else None


class _DeeplinkEvent:
    """Minimaler Ersatz für ``events.CallbackQuery`` für die Callback-Handler."""

    def __init__(self, client, message, sender_id, data):
        self.client = client
        self.message = message
        self.sender_id = sender_id
        self.chat_id = message.chat_id
        self.data = data.encode('utf-8')
        self.is_private = True

    async def answer(self, *args, **kwargs):
        return None

    async def get_message(self):
        return self.message

    async def get_sender(self):
        return await self.client.get_entity(self.sender_id)

    async def get_chat(self):
        return await self.message.get_chat()

    async def edit(self, *args, **kwargs):
        return await self.message.edit(*args, **kwargs)

    async def respond(self, *args, **kwargs):
        return await self.client.send_message(self.chat_id, *args, **kwargs)

    async def reply(self, *args, **kwargs):
        return await self.message.reply(*args, **kwargs)

    async def delete(self):
        return await self.message.delete()


async def run_deeplink_action(client, chat_id, sender_id, action, allowed):
    """Deeplink-Aktion über den vorhandenen Callback-Handler ausführen.

    Gibt False zurück, wenn die Aktion nicht erlaubt ist (Aufrufer zeigt dann
    sein normales Startmenü).
    """
    if action not in allowed:
        logger.info(f'Deeplink-Aktion nicht erlaubt: {action!r} von {sender_id}')
        return False
    from handlers.button.callback.callback_handlers import handle_callback
    placeholder = await client.send_message(chat_id, t('widget.menu.opening'), parse_mode='html')
    await handle_callback(_DeeplinkEvent(client, placeholder, sender_id, action))
    return True


def _button_style(btn):
    """``primary|success|danger`` aus einem Telethon-Button lesen (sonst None)."""
    style = getattr(btn, 'style', None)
    if style is None:
        return None
    for name in ('primary', 'success', 'danger'):
        if getattr(style, f'bg_{name}', False):
            return name
    return None


async def rows_to_knoepfe(rows, allowed):
    """Telethon-Button-Zeilen in Widget-Knöpfe (Label + Link) übersetzen.

    Callback-Buttons werden zu Deeplinks ``?start=cb_<aktion>`` (nur erlaubte
    Aktionen), URL-Buttons bleiben URLs. Nicht abbildbare Buttons entfallen.
    """
    result = []
    for row in rows or []:
        knoepfe = []
        for btn in row:
            btype = getattr(btn, 'type', None)
            data = getattr(btype, 'data', None)
            url = getattr(btype, 'url', None)
            link = None
            if data is not None:
                action = data.decode('utf-8', errors='ignore') if isinstance(data, (bytes, bytearray)) else str(data)
                if action in allowed:
                    link = await widgets.deeplink(f'{DEEPLINK_PREFIX}{action}')
            elif url:
                link = url
            if link:
                knoepfe.append({'label': btn.text, 'link': link, 'style': _button_style(btn)})
        if knoepfe:
            result.append(knoepfe)
    return result


async def send_menu_widget(chat_id, caption, rows, allowed, title=None):
    """Menü als Widget-Karte senden. True bei Erfolg, sonst False (Fallback nötig)."""
    knoepfe = await rows_to_knoepfe(rows, allowed)
    if not knoepfe:
        return False
    hint = t('widget.menu.hint')
    cap = f'{caption}\n\n{hint}' if caption else hint
    if len(cap) > 1024:
        cap = caption[:1024 - len(hint) - 3].rstrip() + '…\n\n' + hint
    return await widgets.send(chat_id, 'menu', caption=cap, title=title, rows=knoepfe)
