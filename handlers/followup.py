"""Follow-up-Nachrichten an Testkunden und Empfehlungslinks (nur Main-Bot).

Der Kunde hat den Main-Bot zuerst gestartet, darum darf der Main-Bot ihm
schreiben. Der Scheduler (``scheduler/followup_scheduler.py``) verschickt die
Nachrichten; hier liegen Texte/Buttons, die Button-Antworten und das Einsammeln
von Freitext-Feedback. Jede Antwort geht als Meldung an den Admin.

Callback-Daten: ``fu:<stufe>:<antwort>`` bzw. ``fu:ref``.
"""

import html
import logging
import re
import time
from datetime import datetime

from telethon import Button

from models.models import ManagedContainer, Referral, get_session
from utils.i18n import t

logger = logging.getLogger(__name__)

# Antworten je Stufe (Reihenfolge = Button-Reihenfolge)
ANSWERS = {
    'd1': ('ok', 'help'),
    'd3': ('ok', 'fb'),
    'lost': ('price', 'complex', 'notneeded', 'other'),
}

# Antworten, nach denen der Kunde Freitext schreiben soll
_FREE_TEXT = {('d3', 'fb'), ('lost', 'other'), ('d1', 'help')}

FEEDBACK_TIMEOUT = 60 * 60  # 1 Stunde auf Freitext warten

# {user_id: (stufe, zeitstempel)}
_awaiting_feedback = {}

_REF_RE = re.compile(r'^/start\s+ref_(\d+)\s*$')

_bot_username = None


def _admin_ids():
    from handlers.onboarding import _admin_ids as ids
    return ids()


def _support_url():
    from handlers.onboarding import _support_url as url
    return url()


async def referral_link(client, customer_id):
    """``https://t.me/<mainbot>?start=ref_<id>`` – Bot-Name wird gecacht."""
    global _bot_username
    if not _bot_username:
        me = await client.get_me()
        _bot_username = me.username
    return f'https://t.me/{_bot_username}?start=ref_{customer_id}'


def build_stage_message(stage, bot_link=None):
    """Text + Buttons für eine Follow-up-Stufe."""
    buttons = []
    if stage in ANSWERS:
        for answer in ANSWERS[stage]:
            buttons.append([Button.inline(t(f'fu.{stage}.btn.{answer}'), f'fu:{stage}:{answer}')])
    if stage == 'd3':
        buttons.append([Button.inline(t('fu.btn.ref'), 'fu:ref')])
    if stage == 'end' and bot_link:
        buttons.append([Button.url(t('fu.end.btn.open'), bot_link)])
    return t(f'fu.{stage}.text'), buttons or None


async def _sender_label(event):
    try:
        sender = await event.get_sender()
        username = getattr(sender, 'username', None)
        name = ((getattr(sender, 'first_name', None) or '') + ' '
                + (getattr(sender, 'last_name', None) or '')).strip() or t('onboard.stranger')
    except Exception:
        username, name = None, t('onboard.stranger')
    handle = f'@{username}' if username else t('onboard.no_username')
    return html.escape(name), handle


async def _notify_admins(client, text):
    for admin_id in _admin_ids():
        try:
            await client.send_message(admin_id, text, parse_mode='html', link_preview=False)
        except Exception as e:
            logger.warning(f'Follow-up-Meldung an Admin {admin_id} fehlgeschlagen: {e}')


async def _edit(message, text, buttons=None):
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            logger.warning(f'Follow-up-Nachricht konnte nicht geändert werden: {e}')


async def callback_followup(event, params, session, message, data):
    """Kunde klickt einen Follow-up-Button."""
    params = params or ''

    if params == 'ref':
        link = await referral_link(event.client, event.sender_id)
        await event.client.send_message(
            event.sender_id, t('ref.text', link=link), parse_mode='html', link_preview=False)
        await event.answer()
        return

    stage, _, answer = params.partition(':')
    if answer not in ANSWERS.get(stage, ()):
        await event.answer()
        return

    name, handle = await _sender_label(event)
    await _notify_admins(event.client, t(
        'fu.admin.answer', name=name, handle=handle, id=event.sender_id,
        stage=t(f'fu.stage.{stage}'), answer=t(f'fu.{stage}.btn.{answer}')))

    if (stage, answer) in _FREE_TEXT:
        _awaiting_feedback[event.sender_id] = (stage, time.time())
        buttons = None
        if answer == 'help' and _support_url():
            buttons = [[Button.url(t('onboard.btn.support'), _support_url())]]
        await _edit(message, t('fu.help.text' if answer == 'help' else 'fu.feedback.ask'), buttons)
    else:
        await _edit(message, t('fu.thanks'))
    await event.answer()


async def capture_feedback(event):
    """Freitext nach „Feedback geben" an den Admin weiterleiten. True = erledigt."""
    entry = _awaiting_feedback.get(event.sender_id)
    text = (event.message.text or '').strip()
    if not entry or not text or text.startswith('/'):
        return False
    stage, since = entry
    _awaiting_feedback.pop(event.sender_id, None)
    if time.time() - since > FEEDBACK_TIMEOUT:
        return False

    name, handle = await _sender_label(event)
    await _notify_admins(event.client, t(
        'fu.admin.feedback', name=name, handle=handle, id=event.sender_id,
        stage=t(f'fu.stage.{stage}'), text=html.escape(text)))
    try:
        await event.reply(t('fu.thanks'), parse_mode='html')
    except Exception:
        pass
    return True


def capture_referral(event):
    """``/start ref_<id>``: Werber merken, wenn der Absender ein Neukunde ist."""
    match = _REF_RE.match((event.message.text or '').strip())
    if not match:
        return
    referrer_id = int(match.group(1))
    referred_id = int(event.sender_id)
    if referrer_id == referred_id:
        return

    session = get_session()
    try:
        # Werber muss echter Kunde sein, Geworbener darf noch keiner sein.
        if not session.query(ManagedContainer).get(referrer_id):
            return
        if session.query(ManagedContainer).get(referred_id):
            return
        if session.query(Referral).get(referred_id):
            return
        session.add(Referral(
            referred_id=referred_id,
            referrer_id=referrer_id,
            created_at=datetime.utcnow().date().isoformat(),
        ))
        session.commit()
        logger.info(f'Empfehlung: {referred_id} geworben von {referrer_id}')
    except Exception as e:
        session.rollback()
        logger.error(f'Empfehlung konnte nicht gespeichert werden: {e}')
    finally:
        session.close()
