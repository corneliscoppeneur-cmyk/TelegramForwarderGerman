"""Abo per Telegram Stars kaufen.

Der Kunde sieht im Bot Pakete (z. B. 500 Stars = 30 Tage) und bezahlt direkt
im Telegram-Chat mit Stars (Währung ``XTR``). Nach erfolgreicher Zahlung
verlängert :func:`on_successful_payment` das Abo in der Datenbank.
"""

import logging
import random

from telethon import Button
from telethon.tl.functions.messages import SendMediaRequest, SetBotPrecheckoutResultsRequest
from telethon.tl.types import (
    DataJSON,
    InputMediaInvoice,
    Invoice,
    LabeledPrice,
    UpdateBotPrecheckoutQuery,
    UpdateNewMessage,
)

from handlers.subscription import PACKAGES, TRIAL_DAYS, status
from utils import widgets
from utils.buttons import styled_inline, STYLE_SUCCESS
from utils.common import get_main_module
from utils.i18n import t

logger = logging.getLogger(__name__)

# Präfix für die Payload, damit successful_payment eindeutig zugeordnet werden kann
PAYLOAD_PREFIX = 'sub_'


def _fmt_state(st):
    """Statuszeile für die Buchungsseite."""
    if st['state'] == 'admin':
        return t('sub.state.admin')
    if st['state'] == 'paid':
        return t('sub.state.paid', days=st['days_left'], until=st['paid_until'])
    if st['state'] == 'trial':
        return t('sub.state.trial', days=st['days_left'])
    if st['state'] == 'expired':
        return t('sub.state.expired')
    return t('sub.state.unknown')


def build_billing_screen(user_id):
    """Text + Buttons für das Abo-Menü."""
    st = status(user_id)
    text = t('sub.screen.text', state=_fmt_state(st))

    buttons = []
    for pkg in PACKAGES:
        label = t(pkg['label_key'], stars=pkg['stars'], days=pkg['days'])
        buttons.append([styled_inline(label, f'sub_buy:{pkg["days"]}:{pkg["stars"]}', STYLE_SUCCESS)])
    buttons.append([Button.inline(t('menu.btn.back_main'), 'menu_main')])
    return text, buttons


async def send_subscription_widget(user_id, caption=None):
    """Abo-Karte als HTML-Widget (Resttage als Balken). Still, wenn nicht möglich."""
    st = status(user_id)
    if st['state'] == 'admin':
        return False
    days = st.get('days_left')
    percent = None
    if days is not None:
        total = TRIAL_DAYS if st['state'] == 'trial' else 30
        percent = max(0, min(100, round(100 * days / max(total, 1))))
    link = await widgets.deeplink('sub_billing')
    return await widgets.send(
        user_id, 'subscription', caption=caption or _fmt_state(st),
        state_text=_fmt_state(st), percent=percent, days_left=days, deeplink=link)


async def callback_billing(event, rule_id, session, message, data):
    """Abo-Menü öffnen."""
    text, buttons = build_billing_screen(event.sender_id)
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise
    await event.answer()


async def callback_buy(event, params, session, message, data):
    """Invoice für ein Paket verschicken. ``params`` = ``"tage:stars"``."""
    try:
        days_str, stars_str = params.split(':', 1)
        days, stars = int(days_str), int(stars_str)
    except Exception:
        await event.answer(t('sub.alert.bad_package'))
        return

    main = await get_main_module()
    bot = main.bot_client

    invoice = Invoice(
        currency='XTR',
        prices=[LabeledPrice(label=t('sub.invoice.label', days=days), amount=stars)],
    )
    media = InputMediaInvoice(
        title=t('sub.invoice.title', days=days),
        description=t('sub.invoice.desc', days=days, stars=stars),
        invoice=invoice,
        payload=f'{PAYLOAD_PREFIX}{days}:{stars}'.encode('utf-8'),
        provider='',              # Stars brauchen keinen externen Provider
        provider_data=DataJSON(data='{}'),
        start_param='',
    )

    try:
        peer = await bot.get_input_entity(event.sender_id)
        await bot(SendMediaRequest(
            peer=peer,
            media=media,
            message='',
            random_id=random.randrange(-(2 ** 63), 2 ** 63),
        ))
        await event.answer()
    except Exception as e:
        logger.error(f'Invoice konnte nicht gesendet werden: {e}')
        await event.answer(t('sub.alert.invoice_failed'))


async def on_pre_checkout(update):
    """Muss den PreCheckout beantworten – sonst bricht Telegram die Zahlung ab.

    ``events.Raw`` liefert den Update direkt (kein Event-Wrapper).
    """
    from handlers.subscription import PACKAGES

    main = await get_main_module()
    bot = main.bot_client
    query = update

    payload = (query.payload or b'').decode('utf-8', errors='replace')
    ok = payload.startswith(PAYLOAD_PREFIX)
    if ok:
        try:
            days_str, stars_str = payload[len(PAYLOAD_PREFIX):].split(':', 1)
            days, stars = int(days_str), int(stars_str)
            ok = any(p['days'] == days and p['stars'] == stars for p in PACKAGES)
        except Exception:
            ok = False

    try:
        await bot(SetBotPrecheckoutResultsRequest(
            query_id=query.query_id,
            success=ok,
            error=None if ok else 'Unbekanntes Paket',
        ))
    except Exception as e:
        logger.error(f'PreCheckout-Antwort fehlgeschlagen: {e}')


async def on_successful_payment(event):
    """Zahlung ist durch – Abo verlängern und Bestätigung schicken."""
    from handlers.subscription import activate

    payment = getattr(event.message, 'action', None)
    if payment is None:
        return

    payload = (getattr(payment, 'payload', b'') or b'').decode('utf-8', errors='replace')
    if not payload.startswith(PAYLOAD_PREFIX):
        return

    try:
        days_str, stars_str = payload[len(PAYLOAD_PREFIX):].split(':', 1)
        days, stars = int(days_str), int(stars_str)
    except Exception:
        logger.warning(f'Ungültige Zahlungs-Payload: {payload}')
        return

    activate(event.sender_id, days=days, stars_paid=stars)

    st = status(event.sender_id)
    done_text = t('sub.payment.done', days=days, until=st['paid_until'])
    # Quittung als Abo-Karte (Widget); Fallback: Textnachricht
    if not await send_subscription_widget(event.sender_id, caption=done_text):
        try:
            await event.reply(done_text, parse_mode='html')
        except Exception as e:
            logger.warning(f'Bestätigung nach Zahlung nicht zustellbar: {e}')

    # Im Main-Bot: Kunde ohne eigenen Bot direkt zum geführten Erstellen leiten.
    try:
        from handlers.onboarding import _is_main_bot
        if _is_main_bot():
            from models.models import ManagedContainer, get_session
            session = get_session()
            try:
                has_bot = session.query(ManagedContainer).get(int(event.sender_id))
            finally:
                session.close()
            if not has_bot:
                from services import botfather
                from utils.buttons import STYLE_PRIMARY
                if botfather.is_configured():
                    rows = [[styled_inline(t('onboard.btn.auto_create'), 'onboard_auto_create', STYLE_PRIMARY)],
                            [Button.inline(t('onboard.btn.create_bot'), 'onboard_create_bot')]]
                else:
                    rows = [[styled_inline(t('onboard.btn.create_bot'), 'onboard_create_bot', STYLE_PRIMARY)]]
                await event.reply(
                    t('onboard.after_pay.create'),
                    buttons=rows,
                    parse_mode='html',
                )
    except Exception as e:
        logger.warning(f'Bot-Erstellen-Hinweis nach Zahlung fehlgeschlagen: {e}')
