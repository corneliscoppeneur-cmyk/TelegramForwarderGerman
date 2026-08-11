"""Auswahlliste für Kanäle und Gruppen.

Liest die Chats des angemeldeten Telegram-Kontos (``user_client``) und baut
daraus eine blätterbare Button-Liste. Wird vom Einrichtungs-Assistenten für
„Woher?“ und „Wohin?“ benutzt.

Die Chatliste wird kurz zwischengespeichert, damit Blättern nicht bei jedem
Klick erneut alle Dialoge von Telegram lädt.
"""

import logging
import time
from html import escape

from telethon import Button

from handlers.button.menu import shorten
from utils.common import get_main_module
from utils.i18n import t

logger = logging.getLogger(__name__)

# Sekunden, die die geladene Chatliste wiederverwendet wird
CACHE_TTL = 300

# Einträge pro Seite
CHATS_PER_PAGE = 8

_cache = {'ts': 0.0, 'items': []}


async def load_chats(force=False):
    """Kanäle und Gruppen des Kontos laden (mit kurzem Zwischenspeicher).

    Returns:
        Liste von Dicts: ``{'id': int, 'name': str, 'entity': <telethon entity>}``
    """
    now = time.time()
    if not force and _cache['items'] and (now - _cache['ts']) < CACHE_TTL:
        return _cache['items']

    main = await get_main_module()
    user_client = main.user_client

    items = []
    async for dialog in user_client.iter_dialogs():
        # Privatchats mit einzelnen Personen sind als Quelle/Ziel unüblich
        if dialog.is_user:
            continue
        entity = dialog.entity
        if entity is None:
            continue
        items.append({
            'id': entity.id,
            'name': dialog.name or t('menu.unknown_chat'),
            'entity': entity,
        })

    _cache['items'] = items
    _cache['ts'] = now
    logger.info(f'Chatliste geladen: {len(items)} Kanäle/Gruppen')
    return items


async def find_chat(chat_id):
    """Eintrag zu einer Chat-ID suchen; lädt bei Bedarf neu."""
    chat_id = int(chat_id)
    for item in await load_chats():
        if item['id'] == chat_id:
            return item
    for item in await load_chats(force=True):
        if item['id'] == chat_id:
            return item
    return None


def filter_chats(items, query):
    """Chats nach Namensbestandteil filtern (Groß-/Kleinschreibung egal)."""
    if not query:
        return items
    query = query.strip().lower()
    return [i for i in items if query in (i['name'] or '').lower()]


# Callback-Präfixe des Einrichtungs-Assistenten – Standard für build_picker
WIZARD_PREFIXES = {'sel': 'wz_sel', 'page': 'wz_page', 'search': 'wz_search', 'link': 'wz_link'}


def build_picker(items, page, role, header_text, query=None,
                 prefixes=None, cancel_data='menu_main'):
    """Auswahlliste aufbauen.

    Args:
        items: gefilterte Chatliste
        page: Seitenzahl ab 0
        role: Kontext-Token in den Callback-Daten. Beim Assistenten ``'s'``/``'t'``,
            beim Bearbeiten ``'<rule_id>:s'`` bzw. ``'<rule_id>:t'``.
        header_text: fertiger Text über der Liste
        query: aktiver Suchbegriff (nur zur Anzeige)
        prefixes: Callback-Präfixe (``sel``/``page``/``search``/``link``);
            Standard sind die des Assistenten.
        cancel_data: Callback-Daten des Abbrechen-Knopfs.

    Returns:
        (text, buttons)
    """
    p = prefixes or WIZARD_PREFIXES
    total = len(items)

    if total == 0:
        text = t('wizard.no_chats_found', query=escape(query or ''))
        buttons = [
            [Button.inline(t('wizard.btn.search_again'), f'{p["search"]}:{role}')],
            [Button.inline(t('wizard.btn.paste_link'), f'{p["link"]}:{role}')],
            [Button.inline(t('menu.btn.cancel'), cancel_data)],
        ]
        return text, buttons

    total_pages = (total + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    buttons = []
    for item in items[page * CHATS_PER_PAGE:(page + 1) * CHATS_PER_PAGE]:
        buttons.append([
            Button.inline(shorten(item['name'], 28), f'{p["sel"]}:{role}:{item["id"]}')
        ])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(Button.inline(t('common.page.prev'), f'{p["page"]}:{role}:{page - 1}'))
        nav.append(Button.inline(f'{page + 1}/{total_pages}', 'noop'))
        if page < total_pages - 1:
            nav.append(Button.inline(t('common.page.next'), f'{p["page"]}:{role}:{page + 1}'))
        buttons.append(nav)

    buttons.append([
        Button.inline(t('wizard.btn.search'), f'{p["search"]}:{role}'),
        Button.inline(t('wizard.btn.paste_link'), f'{p["link"]}:{role}'),
    ])
    buttons.append([Button.inline(t('menu.btn.cancel'), cancel_data)])

    if query:
        text = header_text + '\n\n' + t('wizard.search_active', query=escape(query))
    else:
        text = header_text

    return text, buttons
