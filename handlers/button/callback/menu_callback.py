"""Callbacks für Hauptmenü, Weiterleitungs-Übersicht und Detailkarte.

Alle Handler folgen der Signatur des Dispatchers in ``callback_handlers.py``:
``(event, rule_id, session, message, data)``.
"""

import logging
import traceback

from models.models import ForwardRule
from handlers.button.account_login import is_connected
from handlers.button.menu import (
    build_delete_confirm,
    build_help_page,
    build_main_menu,
    build_rule_card,
    build_rule_overview,
    main_menu_text,
)
from utils.i18n import t

logger = logging.getLogger(__name__)


async def _safe_edit(message, text, buttons):
    """Nachricht bearbeiten und „not modified“-Fehler schlucken."""
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise


async def callback_menu_main(event, rule_id, session, message, data):
    """Hauptmenü anzeigen."""
    connected = await is_connected()
    await _safe_edit(message, main_menu_text(connected), build_main_menu(connected))
    await event.answer()


async def callback_menu_rules(event, rule_id, session, message, data):
    """Übersicht aller Weiterleitungen anzeigen."""
    try:
        page = int(rule_id) if rule_id and str(rule_id).isdigit() else 0
    except (TypeError, ValueError):
        page = 0

    text, buttons = build_rule_overview(session, page)
    await _safe_edit(message, text, buttons)
    await event.answer()


async def callback_rule_card(event, rule_id, session, message, data):
    """Detailkarte einer Weiterleitung anzeigen."""
    text, buttons = build_rule_card(session, str(rule_id).split(':')[0])
    if text is None:
        await event.answer(t('common.alert.rule_not_found'))
        return
    await _safe_edit(message, text, buttons)
    await event.answer()


async def callback_rule_toggle(event, rule_id, session, message, data):
    """Weiterleitung ein- oder ausschalten."""
    try:
        rule = session.query(ForwardRule).get(int(str(rule_id).split(':')[0]))
        if not rule:
            await event.answer(t('common.alert.rule_not_found'))
            return

        rule.enable_rule = not rule.enable_rule
        session.commit()

        text, buttons = build_rule_card(session, rule.id)
        await _safe_edit(message, text, buttons)
        await event.answer(t('menu.alert.turned_on') if rule.enable_rule else t('menu.alert.turned_off'))
    except Exception as e:
        session.rollback()
        logger.error(f'Weiterleitung umschalten fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('common.alert.update_failed'))


async def callback_rule_delete_ask(event, rule_id, session, message, data):
    """Sicherheitsabfrage vor dem Löschen anzeigen."""
    text, buttons = build_delete_confirm(session, str(rule_id).split(':')[0])
    if text is None:
        await event.answer(t('common.alert.rule_not_found'))
        return
    await _safe_edit(message, text, buttons)
    await event.answer()


async def callback_menu_help(event, rule_id, session, message, data):
    """Kurzanleitung anzeigen."""
    text, buttons = build_help_page()
    await _safe_edit(message, text, buttons)
    await event.answer()
