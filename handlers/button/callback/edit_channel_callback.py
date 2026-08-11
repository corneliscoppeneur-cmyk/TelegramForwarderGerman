"""Quelle oder Ziel einer bestehenden Weiterleitung ändern.

Nutzt dieselbe Kanal-Auswahl wie der Einrichtungs-Assistent
(``chat_picker.build_picker``), nur mit eigenen Callback-Präfixen und einem
Abbrechen-Knopf, der zurück zur Detailkarte führt.

Callback-Daten:
  ``edit_src:<rule_id>`` / ``edit_dst:<rule_id>``      Auswahl öffnen
  ``edit_page:<rule_id>:<rolle>:<seite>``              blättern
  ``edit_pick:<rule_id>:<rolle>:<chat_id>``            Kanal übernehmen
  ``edit_search:<rule_id>:<rolle>``                    nach Namen suchen
  ``edit_link:<rule_id>:<rolle>``                      über Link auswählen

Handler-Signatur wie im Dispatcher: ``(event, rule_id, session, message, data)``.
"""

import logging
import traceback
from html import escape

from telethon import Button

from handlers.button.chat_picker import build_picker, filter_chats, find_chat, load_chats
from handlers.button.menu import build_rule_card
from managers.state_manager import state_manager
from models.db_operations import change_rule_channel
from models.models import ForwardRule
from utils.i18n import t

logger = logging.getLogger(__name__)

EDIT_PREFIXES = {'sel': 'edit_pick', 'page': 'edit_page', 'search': 'edit_search', 'link': 'edit_link'}

# Aktiver Suchbegriff je Nutzer und Auswahl: {'<user>:<rule>:<rolle>': begriff}
_edit_q = {}


def _q_key(user_id, rule_id, role):
    return f'{user_id}:{rule_id}:{role}'


def _header(session, rule_id, role):
    """Kopftext der Auswahl – nennt den aktuell eingestellten Kanal."""
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return t('common.alert.rule_not_found')
    if role == 's':
        current = rule.source_chat.name if rule.source_chat else t('menu.unknown_chat')
        return t('edit.pick_source.text', current=escape(current or ''))
    current = rule.target_chat.name if rule.target_chat else t('menu.unknown_chat')
    return t('edit.pick_target.text', current=escape(current or ''))


async def _show_picker(message, session, user_id, rule_id, role, page=0):
    query = _edit_q.get(_q_key(user_id, rule_id, role))
    items = filter_chats(await load_chats(), query)
    token = f'{rule_id}:{role}'
    text, buttons = build_picker(
        items, page, token, _header(session, rule_id, role), query,
        prefixes=EDIT_PREFIXES, cancel_data=f'rule_card:{rule_id}',
    )
    await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)


async def _open(event, rule_id, session, message, role):
    rule_id = str(rule_id).split(':')[0]
    _edit_q.pop(_q_key(event.sender_id, rule_id, role), None)
    try:
        await _show_picker(message, session, event.sender_id, rule_id, role, 0)
        await event.answer()
    except Exception as e:
        logger.error(f'Kanal-Auswahl konnte nicht geöffnet werden: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('wizard.alert.load_chats_failed'))


async def callback_edit_source(event, rule_id, session, message, data):
    """Auswahl für die Quelle öffnen."""
    await _open(event, rule_id, session, message, 's')


async def callback_edit_target(event, rule_id, session, message, data):
    """Auswahl für das Ziel öffnen."""
    await _open(event, rule_id, session, message, 't')


async def callback_edit_page(event, rule_id, session, message, data):
    """Blättern: ``edit_page:<rule_id>:<rolle>:<seite>``."""
    parts = str(rule_id).split(':')
    if len(parts) < 2:
        await event.answer(t('common.alert.bad_callback_data'))
        return
    rid, role = parts[0], parts[1]
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    await _show_picker(message, session, event.sender_id, rid, role, page)
    await event.answer()


async def _apply(event, session, message, rid, role, entity, name):
    """Änderung durchführen und passendes Ergebnis anzeigen."""
    rule, status = change_rule_channel(session, rid, role, entity)
    _edit_q.pop(_q_key(event.sender_id, rid, role), None)

    if status == 'not_found':
        await event.answer(t('common.alert.rule_not_found'))
        return
    if status == 'duplicate':
        # Karte unverändert zeigen, Hinweis als Alert
        text, buttons = build_rule_card(session, rid)
        if text:
            await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
        await event.answer(t('edit.alert.duplicate'), alert=True)
        return

    text, buttons = build_rule_card(session, rid)
    await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    if status == 'unchanged':
        await event.answer(t('edit.alert.unchanged'))
    else:
        key = 'edit.alert.source_changed' if role == 's' else 'edit.alert.target_changed'
        await event.answer(t(key, name=name))


async def callback_edit_pick(event, rule_id, session, message, data):
    """Kanal übernehmen: ``edit_pick:<rule_id>:<rolle>:<chat_id>``."""
    parts = str(rule_id).split(':')
    if len(parts) < 3:
        await event.answer(t('common.alert.bad_callback_data'))
        return
    rid, role, chat_id = parts[0], parts[1], parts[2]

    item = await find_chat(chat_id)
    if not item:
        await event.answer(t('edit.alert.chat_not_found'))
        return

    try:
        await _apply(event, session, message, rid, role, item['entity'], escape(item['name']))
    except Exception as e:
        session.rollback()
        logger.error(f'Kanal ändern fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('common.alert.update_failed'))


async def callback_edit_search(event, rule_id, session, message, data):
    """Nach Kanalnamen suchen (fragt nach einem Suchbegriff)."""
    parts = str(rule_id).split(':')
    rid, role = parts[0], (parts[1] if len(parts) > 1 else 's')
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'edit_search:{rid}:{role}', message, 'edit')
    await message.edit(
        t('wizard.search.ask'),
        buttons=[[Button.inline(t('menu.btn.cancel'), f'edit_page:{rid}:{role}:0')]],
        parse_mode='html', link_preview=False,
    )
    await event.answer()


async def callback_edit_link(event, rule_id, session, message, data):
    """Kanal über einen eingefügten Link auswählen."""
    parts = str(rule_id).split(':')
    rid, role = parts[0], (parts[1] if len(parts) > 1 else 's')
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'edit_link:{rid}:{role}', message, 'edit')
    await message.edit(
        t('wizard.link.ask'),
        buttons=[[Button.inline(t('menu.btn.cancel'), f'edit_page:{rid}:{role}:0')]],
        parse_mode='html', link_preview=False,
    )
    await event.answer()


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Freitext auswerten (Suche oder Link). Aus ``prompt_handlers`` aufgerufen."""
    from models.models import get_session

    kind, _, rest = current_state.partition(':')
    parts = rest.split(':')
    rid = parts[0]
    role = parts[1] if len(parts) > 1 else 's'
    text_input = (event.message.text or '').strip()

    state_manager.clear_state(sender_id, chat_id)
    try:
        await event.message.delete()
    except Exception:
        pass

    if kind == 'edit_search':
        _edit_q[_q_key(sender_id, rid, role)] = text_input
        session = get_session()
        try:
            await _show_picker(message, session, sender_id, rid, role, 0)
        finally:
            session.close()
        return True

    # edit_link: Link auflösen und direkt übernehmen
    try:
        from utils.common import get_main_module
        main = await get_main_module()
        entity = await main.user_client.get_entity(text_input)
    except Exception as e:
        logger.error(f'Link konnte nicht aufgelöst werden: {e}')
        await message.edit(
            t('wizard.link.failed'),
            buttons=[[Button.inline(t('wizard.btn.search_again'), f'edit_link:{rid}:{role}')],
                     [Button.inline(t('menu.btn.cancel'), f'edit_page:{rid}:{role}:0')]],
            parse_mode='html', link_preview=False,
        )
        return True

    name = escape(getattr(entity, 'title', None) or t('menu.unknown_chat'))
    session = get_session()
    try:
        await _apply(event, session, message, rid, role, entity, name)
    except Exception as e:
        session.rollback()
        logger.error(f'Kanal per Link ändern fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
    finally:
        session.close()
    return True
