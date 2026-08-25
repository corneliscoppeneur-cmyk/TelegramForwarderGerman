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

from handlers.subscription import PACKAGES, status
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
        buttons.append([Button.inline(label, f'sub_buy:{pkg["days"]}:{pkg["stars"]}')])
    buttons.append([Button.inline(t('menu.btn.back_main'), 'menu_main')])
    return text, buttons


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
    try:
        await event.reply(
            t('sub.payment.done', days=days, until=st['paid_until']),
            parse_mode='html',
        )
    except Exception as e:
        logger.warning(f'Bestätigung nach Zahlung nicht zustellbar: {e}')
