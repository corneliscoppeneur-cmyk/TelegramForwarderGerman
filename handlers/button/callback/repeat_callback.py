"""Callbacks für die Wiederholung eines Beitrags.

Der Bot schickt den zuletzt weitergeleiteten Beitrag in festem Abstand erneut
in den Zielchat. Gemerkt wird der Beitrag vom ``RepeatFilter``, gesendet vom
``RepeatScheduler``.

Handler-Signatur wie im Dispatcher: ``(event, rule_id, session, message, data)``.
"""

import logging
import traceback

from telethon import Button

from managers.state_manager import state_manager
from models.models import ForwardRule
from utils.common import get_main_module
from utils.i18n import t

logger = logging.getLogger(__name__)

# Schnellwahl in Minuten – deckt die üblichen Fälle ohne Tipparbeit ab
QUICK_CHOICES = [30, 60, 180, 360, 720, 1440]

# Grenzen für eigene Eingaben
MIN_MINUTES = 1
MAX_MINUTES = 10080  # eine Woche


async def _safe_edit(message, text, buttons):
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise


def describe_interval(minutes):
    """60 → „1 Stunde“, 90 → „1 Stunde 30 Minuten“."""
    minutes = int(minutes or 0)
    if minutes < 60:
        return t('repeat.every.minutes', minutes=minutes)

    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return t('repeat.every.hours', hours=hours)
    return t('repeat.every.hours_minutes', hours=hours, minutes=rest)


def build_repeat_screen(session, rule_id):
    """Bildschirm der Wiederholung aufbauen.

    Returns:
        (text, buttons) oder (None, None), wenn es die Weiterleitung nicht gibt.
    """
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return None, None

    interval = int(rule.repeat_interval or 60)

    if rule.enable_repeat:
        status = t('repeat.status.on', interval=describe_interval(interval))
        if not rule.last_message_id:
            status += '\n\n' + t('repeat.status.waiting')
    else:
        status = t('repeat.status.off')

    text = t('repeat.text', status=status)

    toggle = t('repeat.btn.turn_off') if rule.enable_repeat else t('repeat.btn.turn_on')
    buttons = [[Button.inline(toggle, f'repeat_toggle:{rule.id}')]]

    row = []
    for minutes in QUICK_CHOICES:
        mark = '✅ ' if minutes == interval else ''
        row.append(Button.inline(f'{mark}{describe_interval(minutes)}', f'repeat_set:{rule.id}:{minutes}'))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([Button.inline(t('repeat.btn.custom'), f'repeat_custom:{rule.id}')])
    buttons.append([Button.inline(t('menu.btn.back_card'), f'rule_card:{rule.id}')])

    return text, buttons


async def _reschedule(rule):
    """Zeitplan der Regel im Scheduler auffrischen."""
    try:
        main = await get_main_module()
        scheduler = getattr(main, 'repeat_scheduler', None)
        if scheduler:
            await scheduler.schedule_rule(rule)
    except Exception as e:
        logger.error(f'Wiederholung: Zeitplan konnte nicht aufgefrischt werden: {e}')
        logger.error(traceback.format_exc())


async def callback_repeat(event, rule_id, session, message, data):
    """Bildschirm der Wiederholung anzeigen."""
    text, buttons = build_repeat_screen(session, str(rule_id).split(':')[0])
    if text is None:
        await event.answer(t('common.alert.rule_not_found'))
        return
    await _safe_edit(message, text, buttons)
    await event.answer()


async def callback_repeat_toggle(event, rule_id, session, message, data):
    """Wiederholung ein- oder ausschalten."""
    try:
        rule = session.query(ForwardRule).get(int(str(rule_id).split(':')[0]))
        if not rule:
            await event.answer(t('common.alert.rule_not_found'))
            return

        rule.enable_repeat = not rule.enable_repeat
        session.commit()
        await _reschedule(rule)

        text, buttons = build_repeat_screen(session, rule.id)
        await _safe_edit(message, text, buttons)
        await event.answer(
            t('repeat.alert.turned_on') if rule.enable_repeat else t('repeat.alert.turned_off')
        )
    except Exception as e:
        session.rollback()
        logger.error(f'Wiederholung umschalten fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('common.alert.update_failed'))


async def callback_repeat_set(event, rule_id, session, message, data):
    """Abstand über die Schnellwahl setzen: ``repeat_set:{rule_id}:{minuten}``."""
    parts = str(rule_id).split(':')
    if len(parts) < 2:
        await event.answer(t('common.alert.update_failed'))
        return

    try:
        rule = session.query(ForwardRule).get(int(parts[0]))
        if not rule:
            await event.answer(t('common.alert.rule_not_found'))
            return

        minutes = max(MIN_MINUTES, min(int(parts[1]), MAX_MINUTES))
        rule.repeat_interval = minutes
        session.commit()
        await _reschedule(rule)

        text, buttons = build_repeat_screen(session, rule.id)
        await _safe_edit(message, text, buttons)
        await event.answer(t('repeat.alert.interval_saved', interval=describe_interval(minutes)))
    except Exception as e:
        session.rollback()
        logger.error(f'Wiederholung: Abstand konnte nicht gesetzt werden: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('common.alert.update_failed'))


async def callback_repeat_custom(event, rule_id, session, message, data):
    """Nach einem eigenen Abstand fragen."""
    rule_id = str(rule_id).split(':')[0]
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'repeat_interval:{rule_id}', message, 'repeat')

    await _safe_edit(
        message,
        t('repeat.custom.ask'),
        [[Button.inline(t('menu.btn.cancel'), f'repeat:{rule_id}')]],
    )
    await event.answer()


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Eigenen Abstand auswerten. Wird aus ``prompt_handlers`` aufgerufen."""
    from models.models import get_session

    rule_id = current_state.split(':')[1]
    raw = (event.message.text or '').strip()

    try:
        await event.message.delete()
    except Exception:
        pass

    digits = ''.join(c for c in raw if c.isdigit())
    if not digits:
        await _safe_edit(
            message,
            t('repeat.custom.invalid'),
            [[Button.inline(t('menu.btn.back_card'), f'repeat:{rule_id}')]],
        )
        return True

    minutes = int(digits)
    if minutes < MIN_MINUTES or minutes > MAX_MINUTES:
        await _safe_edit(
            message,
            t('repeat.custom.out_of_range', min=MIN_MINUTES, max=MAX_MINUTES),
            [[Button.inline(t('menu.btn.back_card'), f'repeat:{rule_id}')]],
        )
        return True

    state_manager.clear_state(sender_id, chat_id)

    session = get_session()
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await _safe_edit(message, t('common.alert.rule_not_found'), None)
            return True

        rule.repeat_interval = minutes
        session.commit()
        await _reschedule(rule)

        text, buttons = build_repeat_screen(session, rule.id)
        await _safe_edit(message, text, buttons)
    except Exception as e:
        session.rollback()
        logger.error(f'Wiederholung: eigener Abstand konnte nicht gespeichert werden: {e}')
        logger.error(traceback.format_exc())
    finally:
        session.close()

    return True
