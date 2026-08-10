"""Callbacks für den Preis bezahlter Beiträge.

Leitet der Bot einen bezahlten Beitrag weiter, setzt er im Ziel wieder eine
Bezahlschranke. Standardmäßig gilt der Preis des Originals; hier lässt er sich
überschreiben.

Handler-Signatur wie im Dispatcher: ``(event, rule_id, session, message, data)``.
"""

import logging
import traceback

from telethon import Button

from managers.state_manager import state_manager
from models.models import ForwardRule
from utils.i18n import t

logger = logging.getLogger(__name__)

# Telegram nimmt zwischen 1 und 10000 Sternen je Beitrag
MIN_STARS = 1
MAX_STARS = 10000


async def _safe_edit(message, text, buttons):
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise


def build_paid_screen(session, rule_id):
    """Bildschirm für den Preis aufbauen."""
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return None, None

    if rule.paid_media_stars:
        status = t('paid.status.custom', stars=rule.paid_media_stars)
    else:
        status = t('paid.status.same_as_original')

    text = t('paid.text', status=status)

    buttons = []
    if rule.paid_media_stars:
        buttons.append([Button.inline(t('paid.btn.use_original'), f'paid_reset:{rule.id}')])
    buttons.append([Button.inline(t('paid.btn.set'), f'paid_set:{rule.id}')])
    buttons.append([Button.inline(t('menu.btn.back_card'), f'rule_card:{rule.id}')])

    return text, buttons


async def callback_paid(event, rule_id, session, message, data):
    """Preis-Bildschirm anzeigen."""
    text, buttons = build_paid_screen(session, str(rule_id).split(':')[0])
    if text is None:
        await event.answer(t('common.alert.rule_not_found'))
        return
    await _safe_edit(message, text, buttons)
    await event.answer()


async def callback_paid_reset(event, rule_id, session, message, data):
    """Wieder den Preis des Originals verwenden."""
    try:
        rule = session.query(ForwardRule).get(int(str(rule_id).split(':')[0]))
        if not rule:
            await event.answer(t('common.alert.rule_not_found'))
            return

        rule.paid_media_stars = None
        session.commit()

        text, buttons = build_paid_screen(session, rule.id)
        await _safe_edit(message, text, buttons)
        await event.answer(t('paid.alert.uses_original'))
    except Exception as e:
        session.rollback()
        logger.error(f'Preis zurücksetzen fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
        await event.answer(t('common.alert.update_failed'))


async def callback_paid_set(event, rule_id, session, message, data):
    """Nach einem eigenen Preis fragen."""
    rule_id = str(rule_id).split(':')[0]
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), f'paid_stars:{rule_id}', message, 'paid')

    await _safe_edit(
        message,
        t('paid.ask', min=MIN_STARS, max=MAX_STARS),
        [[Button.inline(t('menu.btn.cancel'), f'paid:{rule_id}')]],
    )
    await event.answer()


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Preis auswerten. Wird aus ``prompt_handlers`` aufgerufen."""
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
            t('paid.invalid'),
            [[Button.inline(t('menu.btn.back_card'), f'paid:{rule_id}')]],
        )
        return True

    stars = int(digits)
    if stars < MIN_STARS or stars > MAX_STARS:
        await _safe_edit(
            message,
            t('paid.out_of_range', min=MIN_STARS, max=MAX_STARS),
            [[Button.inline(t('menu.btn.back_card'), f'paid:{rule_id}')]],
        )
        return True

    state_manager.clear_state(sender_id, chat_id)

    session = get_session()
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await _safe_edit(message, t('common.alert.rule_not_found'), None)
            return True

        rule.paid_media_stars = stars
        session.commit()

        text, buttons = build_paid_screen(session, rule.id)
        await _safe_edit(message, text, buttons)
    except Exception as e:
        session.rollback()
        logger.error(f'Preis konnte nicht gespeichert werden: {e}')
        logger.error(traceback.format_exc())
    finally:
        session.close()

    return True
