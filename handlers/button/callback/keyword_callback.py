"""Filterwörter und Textersetzungen komplett über Buttons verwalten.

Ersetzt die Befehle /add, /remove_keyword, /clear_all_keywords, /replace,
/list_replace, /remove_replace, /export_* und /import_* durch geführte
Bildschirme mit Inline-Buttons. Die Befehle bleiben zusätzlich bestehen.

Freitext- und Datei-Eingaben laufen über den vorhandenen ``state_manager`` und
werden in ``handlers/prompt_handlers.py`` hierher weitergereicht.
"""

import logging
import os
import traceback
from html import escape

from telethon import Button

from enums.enums import AddMode
from handlers.button.menu import shorten
from managers.state_manager import state_manager
from models.models import ForwardRule, Keyword, ReplaceRule, get_session
from utils.common import get_bot_client, get_db_ops
from utils.constants import TEMP_DIR
from utils.i18n import t

logger = logging.getLogger(__name__)

# Einträge pro Seite
ENTRIES_PER_PAGE = 10

# Zwischenspeicher für die zweistufige Eingabe einer Textersetzung
_pending_replace = {}


# --------------------------------------------------------------------------
# Gemeinsame Helfer
# --------------------------------------------------------------------------

def _paged(items, page):
    """Seite ausschneiden und (items, page, total_pages) zurückgeben."""
    total_pages = max(1, (len(items) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    return items[page * ENTRIES_PER_PAGE:(page + 1) * ENTRIES_PER_PAGE], page, total_pages


def _nav_row(action, rule_id, page, total_pages):
    """Blätter-Zeile aufbauen (oder None, wenn nur eine Seite)."""
    if total_pages <= 1:
        return None
    row = []
    if page > 0:
        row.append(Button.inline(t('common.page.prev'), f'{action}:{rule_id}:{page - 1}'))
    row.append(Button.inline(f'{page + 1}/{total_pages}', 'noop'))
    if page < total_pages - 1:
        row.append(Button.inline(t('common.page.next'), f'{action}:{rule_id}:{page + 1}'))
    return row


def _parse_args(rule_id_data):
    """``<rule_id>[:<zahl>[:<zahl>]]`` in eine Liste von Strings zerlegen."""
    return [p for p in str(rule_id_data).split(':') if p != '']


async def _edit(message, text, buttons):
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise


# --------------------------------------------------------------------------
# Filterwörter
# --------------------------------------------------------------------------

def _rule_words(session, rule):
    """Wörter der Liste, die zum eingestellten Modus der Weiterleitung gehört."""
    is_blacklist = rule.add_mode != AddMode.WHITELIST
    return (session.query(Keyword)
            .filter(Keyword.rule_id == rule.id, Keyword.is_blacklist == is_blacklist)
            .order_by(Keyword.id)
            .all())


def build_words_screen(session, rule_id, page=0):
    """Bildschirm „Filterwörter“ aufbauen."""
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return None, None

    words = _rule_words(session, rule)
    entries, page, total_pages = _paged(words, page)

    if rule.add_mode == AddMode.WHITELIST:
        explain = t('words.explain.whitelist')
    else:
        explain = t('words.explain.blacklist')

    text = t(
        'words.text',
        source=escape(rule.source_chat.name or ''),
        target=escape(rule.target_chat.name or ''),
        explain=explain,
        count=len(words),
    )

    buttons = []
    for kw in entries:
        label = f'🗑 {shorten(kw.keyword, 26)}'
        buttons.append([Button.inline(label, f'word_del:{rule.id}:{kw.id}:{page}')])

    nav = _nav_row('words', rule.id, page, total_pages)
    if nav:
        buttons.append(nav)

    buttons.append([Button.inline(t('words.btn.add'), f'word_add:{rule.id}')])
    buttons.append([
        Button.inline(t('words.btn.export'), f'word_export:{rule.id}'),
        Button.inline(t('words.btn.import'), f'word_import:{rule.id}'),
    ])
    row = [Button.inline(t('words.btn.copy_from'), f'copy_keyword:{rule.id}')]
    if words:
        row.append(Button.inline(t('words.btn.clear'), f'word_clear:{rule.id}'))
    buttons.append(row)
    buttons.append([Button.inline(t('menu.btn.back_rules'), f'rule_card:{rule.id}')])

    return text, buttons


async def callback_words(event, rule_id, session, message, data):
    """Filterwörter anzeigen: ``words:<rule_id>[:<seite>]``."""
    args = _parse_args(rule_id)
    page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0

    text, buttons = build_words_screen(session, args[0], page)
    if text is None:
        await event.answer(t('common.alert.rule_not_found'))
        return
    await _edit(message, text, buttons)
    await event.answer()


async def callback_word_delete(event, rule_id, session, message, data):
    """Einzelnes Wort löschen: ``word_del:<rule_id>:<wort_id>:<seite>``."""
    args = _parse_args(rule_id)
    if len(args) < 2:
        await event.answer(t('common.alert.bad_callback_data'))
        return

    page = int(args[2]) if len(args) > 2 and args[2].isdigit() else 0
    try:
        keyword = session.query(Keyword).get(int(args[1]))
        if keyword and str(keyword.rule_id) == str(args[0]):
            session.delete(keyword)
            session.commit()
            await event.answer(t('words.alert.deleted'))
        else:
            await event.answer(t('words.alert.not_found'))
    except Exception as e:
        session.rollback()
        logger.error(f'Wort löschen fehlgeschlagen: {e}')
        await event.answer(t('common.alert.update_failed'))
        return

    text, buttons = build_words_screen(session, args[0], page)
    await _edit(message, text, buttons)


async def callback_word_add(event, rule_id, session, message, data):
    """Nach neuen Wörtern fragen."""
    args = _parse_args(rule_id)
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'word_add:{args[0]}', message, 'words')

    await _edit(
        message,
        t('words.add.ask'),
        [[Button.inline(t('menu.btn.cancel'), f'words:{args[0]}:0')]],
    )
    await event.answer()


async def callback_word_clear(event, rule_id, session, message, data):
    """Sicherheitsabfrage: alle Wörter löschen."""
    args = _parse_args(rule_id)
    await _edit(
        message,
        t('words.clear.confirm'),
        [
            [Button.inline(t('words.btn.clear_yes'), f'word_clear_yes:{args[0]}')],
            [Button.inline(t('menu.btn.cancel'), f'words:{args[0]}:0')],
        ],
    )
    await event.answer()


async def callback_word_clear_yes(event, rule_id, session, message, data):
    """Alle Wörter der aktiven Liste löschen."""
    args = _parse_args(rule_id)
    try:
        rule = session.query(ForwardRule).get(int(args[0]))
        if not rule:
            await event.answer(t('common.alert.rule_not_found'))
            return
        for kw in _rule_words(session, rule):
            session.delete(kw)
        session.commit()
        await event.answer(t('words.alert.cleared'))
    except Exception as e:
        session.rollback()
        logger.error(f'Wörter löschen fehlgeschlagen: {e}')
        await event.answer(t('common.alert.update_failed'))
        return

    text, buttons = build_words_screen(session, args[0], 0)
    await _edit(message, text, buttons)


async def callback_word_export(event, rule_id, session, message, data):
    """Wörter als Textdatei schicken."""
    args = _parse_args(rule_id)
    rule = session.query(ForwardRule).get(int(args[0]))
    if not rule:
        await event.answer(t('common.alert.rule_not_found'))
        return

    words = _rule_words(session, rule)
    if not words:
        await event.answer(t('words.alert.nothing_to_export'))
        return

    path = os.path.join(TEMP_DIR, f'filterwoerter_{rule.id}.txt')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            for kw in words:
                f.write(f'{kw.keyword} {1 if kw.is_blacklist else 0}\n')

        client = await get_bot_client()
        await client.send_file(event.chat_id, path, caption=t('words.export.caption'))
        await event.answer(t('words.alert.exported'))
    except Exception as e:
        logger.error(f'Wörter exportieren fehlgeschlagen: {e}')
        await event.answer(t('words.alert.export_failed'))
    finally:
        if os.path.exists(path):
            os.remove(path)


async def callback_word_import(event, rule_id, session, message, data):
    """Nach einer Datei mit Wörtern fragen."""
    args = _parse_args(rule_id)
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'word_import:{args[0]}', message, 'words')

    await _edit(
        message,
        t('words.import.ask'),
        [[Button.inline(t('menu.btn.cancel'), f'words:{args[0]}:0')]],
    )
    await event.answer()


# --------------------------------------------------------------------------
# Textersetzungen
# --------------------------------------------------------------------------

def build_replaces_screen(session, rule_id, page=0):
    """Bildschirm „Textersetzung“ aufbauen."""
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return None, None

    rules = (session.query(ReplaceRule)
             .filter(ReplaceRule.rule_id == rule.id)
             .order_by(ReplaceRule.id)
             .all())
    entries, page, total_pages = _paged(rules, page)

    text = t(
        'replaces.text',
        source=escape(rule.source_chat.name or ''),
        target=escape(rule.target_chat.name or ''),
        count=len(rules),
    )

    buttons = []
    for rr in entries:
        target_text = shorten(rr.content, 12) if rr.content else t('replaces.removed')
        label = f'🗑 {shorten(rr.pattern, 14)} → {target_text}'
        buttons.append([Button.inline(label, f'rep_del:{rule.id}:{rr.id}:{page}')])

    nav = _nav_row('replaces', rule.id, page, total_pages)
    if nav:
        buttons.append(nav)

    buttons.append([Button.inline(t('replaces.btn.add'), f'rep_add:{rule.id}')])
    buttons.append([
        Button.inline(t('words.btn.export'), f'rep_export:{rule.id}'),
        Button.inline(t('words.btn.import'), f'rep_import:{rule.id}'),
    ])
    row = [Button.inline(t('replaces.btn.copy_from'), f'copy_replace:{rule.id}')]
    if rules:
        row.append(Button.inline(t('replaces.btn.clear'), f'rep_clear:{rule.id}'))
    buttons.append(row)
    buttons.append([Button.inline(t('menu.btn.back_rules'), f'rule_card:{rule.id}')])

    return text, buttons


async def callback_replaces(event, rule_id, session, message, data):
    """Textersetzungen anzeigen: ``replaces:<rule_id>[:<seite>]``."""
    args = _parse_args(rule_id)
    page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0

    text, buttons = build_replaces_screen(session, args[0], page)
    if text is None:
        await event.answer(t('common.alert.rule_not_found'))
        return
    await _edit(message, text, buttons)
    await event.answer()


async def callback_replace_delete(event, rule_id, session, message, data):
    """Einzelne Ersetzung löschen: ``rep_del:<rule_id>:<id>:<seite>``."""
    args = _parse_args(rule_id)
    if len(args) < 2:
        await event.answer(t('common.alert.bad_callback_data'))
        return

    page = int(args[2]) if len(args) > 2 and args[2].isdigit() else 0
    try:
        rr = session.query(ReplaceRule).get(int(args[1]))
        if rr and str(rr.rule_id) == str(args[0]):
            session.delete(rr)
            session.commit()
            await event.answer(t('replaces.alert.deleted'))
        else:
            await event.answer(t('replaces.alert.not_found'))
    except Exception as e:
        session.rollback()
        logger.error(f'Ersetzung löschen fehlgeschlagen: {e}')
        await event.answer(t('common.alert.update_failed'))
        return

    text, buttons = build_replaces_screen(session, args[0], page)
    await _edit(message, text, buttons)


async def callback_replace_add(event, rule_id, session, message, data):
    """Schritt 1: Nach dem zu ersetzenden Text fragen."""
    args = _parse_args(rule_id)
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'rep_add_from:{args[0]}', message, 'replaces')

    await _edit(
        message,
        t('replaces.add.ask_from'),
        [[Button.inline(t('menu.btn.cancel'), f'replaces:{args[0]}:0')]],
    )
    await event.answer()


async def callback_replace_add_empty(event, rule_id, session, message, data):
    """Schritt 2 abkürzen: gefundenen Text ersatzlos entfernen."""
    args = _parse_args(rule_id)
    user_id = event.sender_id
    pattern = _pending_replace.pop(user_id, None)
    if pattern is None:
        await event.answer(t('replaces.alert.input_lost'))
        return

    chat = await event.get_chat()
    state_manager.clear_state(user_id, abs(chat.id))

    await _save_replace(session, args[0], pattern, '')
    text, buttons = build_replaces_screen(session, args[0], 0)
    await _edit(message, text, buttons)
    await event.answer(t('replaces.alert.saved'))


async def callback_replace_clear(event, rule_id, session, message, data):
    """Sicherheitsabfrage: alle Ersetzungen löschen."""
    args = _parse_args(rule_id)
    await _edit(
        message,
        t('replaces.clear.confirm'),
        [
            [Button.inline(t('replaces.btn.clear_yes'), f'rep_clear_yes:{args[0]}')],
            [Button.inline(t('menu.btn.cancel'), f'replaces:{args[0]}:0')],
        ],
    )
    await event.answer()


async def callback_replace_clear_yes(event, rule_id, session, message, data):
    """Alle Ersetzungen der Weiterleitung löschen."""
    args = _parse_args(rule_id)
    try:
        session.query(ReplaceRule).filter(ReplaceRule.rule_id == int(args[0])).delete()
        session.commit()
        await event.answer(t('replaces.alert.cleared'))
    except Exception as e:
        session.rollback()
        logger.error(f'Ersetzungen löschen fehlgeschlagen: {e}')
        await event.answer(t('common.alert.update_failed'))
        return

    text, buttons = build_replaces_screen(session, args[0], 0)
    await _edit(message, text, buttons)


async def callback_replace_export(event, rule_id, session, message, data):
    """Ersetzungen als Textdatei schicken (gleiches Format wie /export_replace)."""
    args = _parse_args(rule_id)
    rules = (session.query(ReplaceRule)
             .filter(ReplaceRule.rule_id == int(args[0]))
             .order_by(ReplaceRule.id)
             .all())
    if not rules:
        await event.answer(t('replaces.alert.nothing_to_export'))
        return

    path = os.path.join(TEMP_DIR, f'textersetzungen_{args[0]}.txt')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            for rr in rules:
                f.write(f"{rr.pattern}\t{rr.content or ''}\n")

        client = await get_bot_client()
        await client.send_file(event.chat_id, path, caption=t('replaces.export.caption'))
        await event.answer(t('words.alert.exported'))
    except Exception as e:
        logger.error(f'Ersetzungen exportieren fehlgeschlagen: {e}')
        await event.answer(t('words.alert.export_failed'))
    finally:
        if os.path.exists(path):
            os.remove(path)


async def callback_replace_import(event, rule_id, session, message, data):
    """Nach einer Datei mit Ersetzungen fragen."""
    args = _parse_args(rule_id)
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'rep_import:{args[0]}', message, 'replaces')

    await _edit(
        message,
        t('replaces.import.ask'),
        [[Button.inline(t('menu.btn.cancel'), f'replaces:{args[0]}:0')]],
    )
    await event.answer()


async def _save_replace(session, rule_id, pattern, content):
    """Ersetzung speichern und ``is_replace`` der Weiterleitung einschalten."""
    db_ops = await get_db_ops()
    await db_ops.add_replace_rules(session, int(rule_id), [pattern], [content])

    rule = session.query(ForwardRule).get(int(rule_id))
    if rule and not rule.is_replace:
        rule.is_replace = True
    session.commit()


# --------------------------------------------------------------------------
# Freitext- und Datei-Eingaben
# --------------------------------------------------------------------------

async def _download_lines(event):
    """Angehängte Textdatei herunterladen und Zeilen zurückgeben."""
    if not event.message.document:
        return None

    client = await get_bot_client()
    path = os.path.join(TEMP_DIR, f'import_{event.message.id}.txt')
    try:
        await client.download_media(event.message, path)
        with open(path, 'r', encoding='utf-8') as f:
            return [line.rstrip('\n') for line in f if line.strip()]
    finally:
        if os.path.exists(path):
            os.remove(path)


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Eingaben zu Wörtern und Ersetzungen auswerten.

    Wird aus ``handlers/prompt_handlers.py`` aufgerufen.
    """
    kind, _, rule_id = current_state.partition(':')
    rule_id = rule_id.split(':')[0]
    session = get_session()

    try:
        if kind == 'word_add':
            lines = [line.strip() for line in (event.message.text or '').splitlines() if line.strip()]
            if not lines:
                await event.respond(t('words.alert.empty_input'))
                return True

            rule = session.query(ForwardRule).get(int(rule_id))
            if not rule:
                return True

            db_ops = await get_db_ops()
            added, duplicates = await db_ops.add_keywords(
                session, int(rule_id), lines,
                is_regex=False,
                is_blacklist=(rule.add_mode != AddMode.WHITELIST),
            )
            session.commit()
            state_manager.clear_state(sender_id, chat_id)
            await _delete_user_message(event)

            text, buttons = build_words_screen(session, rule_id, 0)
            await _edit(message, t('words.added', added=added, duplicates=duplicates) + '\n\n' + text, buttons)
            return True

        if kind == 'word_import':
            lines = await _download_lines(event)
            if lines is None:
                await event.respond(t('words.import.no_file'))
                return True

            rule = session.query(ForwardRule).get(int(rule_id))
            if not rule:
                return True

            normal, blacklist_flags = [], (rule.add_mode != AddMode.WHITELIST)
            for line in lines:
                parts = line.rsplit(' ', 1)
                normal.append(parts[0] if len(parts) == 2 and parts[1] in ('0', '1') else line)

            db_ops = await get_db_ops()
            added, duplicates = await db_ops.add_keywords(
                session, int(rule_id), normal, is_regex=False, is_blacklist=blacklist_flags
            )
            session.commit()
            state_manager.clear_state(sender_id, chat_id)
            await _delete_user_message(event)

            text, buttons = build_words_screen(session, rule_id, 0)
            await _edit(message, t('words.added', added=added, duplicates=duplicates) + '\n\n' + text, buttons)
            return True

        if kind == 'rep_add_from':
            pattern = (event.message.text or '').strip()
            if not pattern:
                await event.respond(t('replaces.alert.empty_input'))
                return True

            _pending_replace[sender_id] = pattern
            state_manager.set_state(sender_id, chat_id, f'rep_add_to:{rule_id}', message, 'replaces')
            await _delete_user_message(event)

            await _edit(
                message,
                t('replaces.add.ask_to', pattern=escape(pattern)),
                [
                    [Button.inline(t('replaces.btn.remove_completely'), f'rep_add_empty:{rule_id}')],
                    [Button.inline(t('menu.btn.cancel'), f'replaces:{rule_id}:0')],
                ],
            )
            return True

        if kind == 'rep_add_to':
            pattern = _pending_replace.pop(sender_id, None)
            if pattern is None:
                state_manager.clear_state(sender_id, chat_id)
                await event.respond(t('replaces.alert.input_lost'))
                return True

            content = event.message.text or ''
            state_manager.clear_state(sender_id, chat_id)
            await _delete_user_message(event)

            await _save_replace(session, rule_id, pattern, content)
            text, buttons = build_replaces_screen(session, rule_id, 0)
            await _edit(message, text, buttons)
            return True

        if kind == 'rep_import':
            lines = await _download_lines(event)
            if lines is None:
                await event.respond(t('replaces.import.no_file'))
                return True

            patterns, contents = [], []
            for line in lines:
                pattern, _, content = line.partition('\t')
                if not pattern:
                    continue
                patterns.append(pattern)
                contents.append(content)

            if patterns:
                db_ops = await get_db_ops()
                await db_ops.add_replace_rules(session, int(rule_id), patterns, contents)
                rule = session.query(ForwardRule).get(int(rule_id))
                if rule and not rule.is_replace:
                    rule.is_replace = True
                session.commit()

            state_manager.clear_state(sender_id, chat_id)
            await _delete_user_message(event)

            text, buttons = build_replaces_screen(session, rule_id, 0)
            await _edit(message, text, buttons)
            return True

        return False
    except Exception as e:
        session.rollback()
        logger.error(f'Eingabe konnte nicht verarbeitet werden: {e}')
        logger.error(traceback.format_exc())
        state_manager.clear_state(sender_id, chat_id)
        return True
    finally:
        session.close()


async def _delete_user_message(event):
    """Eingabenachricht des Nutzers entfernen, damit der Chat aufgeräumt bleibt."""
    try:
        await event.message.delete()
    except Exception:
        pass
