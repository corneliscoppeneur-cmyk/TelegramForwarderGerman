"""Einrichtungs-Assistent „Neue Weiterleitung“.

Vier Schritte, komplett über Buttons:
  1. Woher kommen die Nachrichten?
  2. Wohin sollen sie?
  3. Was soll ankommen?
  4. Zusammenfassung

Der Zwischenstand liegt in einem einfachen Modul-Dict (kurzlebig, pro Nutzer).
Für Freitext-Eingaben (Suche, Link) wird der vorhandene ``state_manager``
benutzt; ausgewertet wird sie in ``handlers/prompt_handlers.py``.
"""

import logging
import traceback
from html import escape

from telethon import Button

from enums.enums import AddMode, ForwardMode
from handlers.button.chat_picker import build_picker, filter_chats, find_chat, load_chats
from managers.state_manager import state_manager
from models.db_operations import create_forward_rule
from utils.i18n import t

logger = logging.getLogger(__name__)

# Zwischenstand je Nutzer: {'s': chat_id, 't': chat_id, 'qs': suchbegriff, 'qt': suchbegriff}
_sessions = {}


def get_session_data(user_id):
    """Zwischenstand des Assistenten für einen Nutzer holen (legt ihn bei Bedarf an)."""
    return _sessions.setdefault(int(user_id), {})


def reset_session(user_id):
    _sessions.pop(int(user_id), None)


async def _selected(store, role):
    """Gewählten Chat einer Rolle auflösen.

    Bevorzugt die im Zwischenstand abgelegte Entität (z. B. über Link gewählt),
    sonst wird in der geladenen Chatliste gesucht.

    Returns:
        Dict ``{'id', 'name', 'entity'}`` oder None.
    """
    entity = store.get('e' + role)
    if entity is not None:
        return {
            'id': entity.id,
            'name': getattr(entity, 'title', None) or t('menu.unknown_chat'),
            'entity': entity,
        }

    chat_id = store.get(role)
    if chat_id is None:
        return None
    return await find_chat(chat_id)


async def _header_text(role, data):
    """Kopftext des jeweiligen Schrittes."""
    if role == 's':
        return t('wizard.step1.text')

    source = await _selected(data, 's')
    source_name = escape(source['name']) if source else t('menu.unknown_chat')
    return t('wizard.step2.text', source=source_name)


async def show_picker(event, message, user_id, role, page=0):
    """Auswahlliste für Quelle oder Ziel anzeigen."""
    data = get_session_data(user_id)
    query = data.get('q' + role)
    items = filter_chats(await load_chats(), query)
    text, buttons = build_picker(items, page, role, await _header_text(role, data), query)
    await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)


def _mode_buttons():
    return [
        [Button.inline(t('wizard.btn.mode_all'), 'wz_mode:all')],
        [Button.inline(t('wizard.btn.mode_only'), 'wz_mode:only')],
        [Button.inline(t('wizard.btn.mode_except'), 'wz_mode:except')],
        [Button.inline(t('menu.btn.cancel'), 'menu_main')],
    ]


async def show_mode_step(event, message, user_id):
    """Schritt 3: Was soll ankommen?"""
    data = get_session_data(user_id)
    source = await _selected(data, 's')
    target = await _selected(data, 't')

    text = t(
        'wizard.step3.text',
        source=escape(source['name']) if source else t('menu.unknown_chat'),
        target=escape(target['name']) if target else t('menu.unknown_chat'),
    )
    await message.edit(text, buttons=_mode_buttons(), parse_mode='html', link_preview=False)


async def callback_wizard_start(event, rule_id, session, message, data):
    """Assistent starten – Schritt 1."""
    user_id = event.sender_id
    reset_session(user_id)
    try:
        await show_picker(event, message, user_id, 's', 0)
        await event.answer()
    except Exception as e:
        logger.error(f'Assistent konnte nicht starten: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('wizard.alert.load_chats_failed'))


async def callback_wizard_page(event, rule_id, session, message, data):
    """Blättern in der Auswahlliste: ``wz_page:<rolle>:<seite>``."""
    parts = str(rule_id).split(':')
    role = parts[0]
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await show_picker(event, message, event.sender_id, role, page)
    await event.answer()


async def callback_wizard_select(event, rule_id, session, message, data):
    """Chat gewählt: ``wz_sel:<rolle>:<chat_id>``."""
    parts = str(rule_id).split(':')
    if len(parts) < 2:
        await event.answer(t('common.alert.bad_callback_data'))
        return

    role, chat_id = parts[0], parts[1]
    user_id = event.sender_id
    data_store = get_session_data(user_id)
    data_store[role] = int(chat_id)
    data_store.pop('e' + role, None)

    if role == 's':
        await show_picker(event, message, user_id, 't', 0)
    else:
        await show_mode_step(event, message, user_id)
    await event.answer()


async def callback_wizard_search(event, rule_id, session, message, data):
    """Nach Chatnamen suchen: fragt nach einem Suchbegriff."""
    role = str(rule_id).split(':')[0]
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'wizard_search:{role}', message, 'wizard')

    await message.edit(
        t('wizard.search.ask'),
        buttons=[[Button.inline(t('menu.btn.cancel'), f'wz_page:{role}:0')]],
        parse_mode='html',
        link_preview=False,
    )
    await event.answer()


async def callback_wizard_link(event, rule_id, session, message, data):
    """Chat über einen eingefügten Link auswählen."""
    role = str(rule_id).split(':')[0]
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'wizard_link:{role}', message, 'wizard')

    await message.edit(
        t('wizard.link.ask'),
        buttons=[[Button.inline(t('menu.btn.cancel'), f'wz_page:{role}:0')]],
        parse_mode='html',
        link_preview=False,
    )
    await event.answer()


async def callback_wizard_mode(event, rule_id, session, message, data):
    """Schritt 3 abschließen und Weiterleitung anlegen."""
    mode = str(rule_id).split(':')[0]
    user_id = event.sender_id
    store = get_session_data(user_id)

    source = await _selected(store, 's')
    target = await _selected(store, 't')
    if not source or not target:
        await event.answer(t('wizard.alert.selection_lost'))
        return

    try:
        rule, created = create_forward_rule(session, source['entity'], target['entity'])
        if rule is None:
            await event.answer(t('wizard.alert.create_failed'))
            return

        if mode == 'only':
            rule.forward_mode = ForwardMode.WHITELIST
            rule.add_mode = AddMode.WHITELIST
        else:
            rule.forward_mode = ForwardMode.BLACKLIST
            rule.add_mode = AddMode.BLACKLIST
        session.commit()

        reset_session(user_id)

        text = t(
            'wizard.done.text' if created else 'wizard.done.existing',
            source=escape(source['name']),
            target=escape(target['name']),
        )

        buttons = []
        if mode in ('only', 'except'):
            buttons.append([Button.inline(t('wizard.btn.set_words_now'), f'words:{rule.id}:0')])
        buttons.append([Button.inline(t('menu.btn.settings'), f'rule_settings:{rule.id}')])
        buttons.append([Button.inline(t('wizard.btn.finish'), f'rule_card:{rule.id}')])

        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
        await event.answer()
    except Exception as e:
        session.rollback()
        logger.error(f'Weiterleitung anlegen fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('wizard.alert.create_failed'))


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Freitext-Eingabe des Assistenten auswerten (Suche oder Link).

    Wird aus ``handlers/prompt_handlers.py`` aufgerufen.
    """
    kind, _, role = current_state.partition(':')
    role = (role or 's').split(':')[0]
    text_input = (event.message.text or '').strip()

    state_manager.clear_state(sender_id, chat_id)
    store = get_session_data(sender_id)

    try:
        await event.message.delete()
    except Exception:
        pass

    if kind == 'wizard_search':
        store['q' + role] = text_input
        items = filter_chats(await load_chats(), text_input)
        header = await _header_text(role, store)
        out_text, buttons = build_picker(items, 0, role, header, text_input)
        await message.edit(out_text, buttons=buttons, parse_mode='html', link_preview=False)
        return True

    # wizard_link: Link auflösen und direkt übernehmen
    try:
        from utils.common import get_main_module
        main = await get_main_module()
        entity = await main.user_client.get_entity(text_input)
    except Exception as e:
        logger.error(f'Link konnte nicht aufgelöst werden: {e}')
        await message.edit(
            t('wizard.link.failed'),
            buttons=[[Button.inline(t('wizard.btn.search_again'), f'wz_link:{role}')],
                     [Button.inline(t('menu.btn.cancel'), f'wz_page:{role}:0')]],
            parse_mode='html',
            link_preview=False,
        )
        return True

    store[role] = entity.id
    store['e' + role] = entity

    if role == 's':
        items = filter_chats(await load_chats(), store.get('qt'))
        header = await _header_text('t', store)
        out_text, buttons = build_picker(items, 0, 't', header, store.get('qt'))
        await message.edit(out_text, buttons=buttons, parse_mode='html', link_preview=False)
    else:
        await show_mode_step(event, message, sender_id)
    return True
