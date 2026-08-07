"""Telegram-Konto direkt im Bot-Chat verbinden.

Damit muss niemand mehr am Server eine Telefonnummer und einen Anmeldecode
eintippen: der Nutzer wird im Bot Schritt für Schritt durch die Anmeldung
geführt.

Der Anmeldecode wird bewusst **mit Präfix** erwartet (``mycode 12345``).
Telegram entwertet Codes, die als reine Zahl durch einen Telegram-Chat laufen –
das ist ein Schutz gegen Kontodiebstahl. Der Präfix verhindert, dass der Code
als solcher erkannt wird.

Das 2FA-Passwort wird ausschließlich für den Anmeldevorgang benutzt und
nirgends gespeichert. Die Nachricht des Nutzers wird sofort gelöscht.
"""

import logging
import re
import traceback

from telethon import Button
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from managers.state_manager import state_manager
from utils.common import get_main_module
from utils.i18n import t

logger = logging.getLogger(__name__)

# Präfixe, mit denen Code und Passwort geschickt werden müssen
CODE_PREFIX = 'mycode'
PASSWORD_PREFIX = 'mypass'

# Zwischenstand je Nutzer: {'phone': str, 'hash': str}
_pending = {}


async def is_connected():
    """Ist ein Telegram-Konto angemeldet?"""
    try:
        main = await get_main_module()
        client = getattr(main, 'user_client', None)
        if client is None or not client.is_connected():
            return False
        return await client.is_user_authorized()
    except Exception as e:
        logger.error(f'Anmeldestatus konnte nicht geprüft werden: {e}')
        return False


def strip_prefix(text, prefix):
    """``mycode 12 345`` → ``12345``; gibt None zurück, wenn der Präfix fehlt."""
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned.lower().startswith(prefix):
        return None
    rest = cleaned[len(prefix):]
    return rest.strip(' :-_')


async def _edit(message, text, buttons=None):
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise


async def _delete_input(event):
    """Eingabe des Nutzers sofort entfernen – sie enthält Code oder Passwort."""
    try:
        await event.message.delete()
    except Exception as e:
        logger.warning(f'Eingabenachricht konnte nicht gelöscht werden: {e}')


# --------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------

async def callback_login_start(event, rule_id, session, message, data):
    """Schritt 1: Nach der Telefonnummer fragen."""
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), 'login_phone:0', message, 'login')

    await _edit(
        message,
        t('login.phone.ask'),
        [[Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
    )
    await event.answer()


async def callback_login_cancel(event, rule_id, session, message, data):
    """Anmeldung abbrechen."""
    chat = await event.get_chat()
    state_manager.clear_state(event.sender_id, abs(chat.id))
    _pending.pop(event.sender_id, None)

    await _edit(message, t('login.cancelled'), await build_login_buttons())
    await event.answer()


async def callback_login_resend(event, rule_id, session, message, data):
    """Code erneut anfordern."""
    store = _pending.get(event.sender_id)
    if not store or not store.get('phone'):
        await event.answer(t('login.alert.start_again'))
        return

    chat = await event.get_chat()
    ok, text, buttons = await request_code(store['phone'], event.sender_id)
    if ok:
        state_manager.set_state(event.sender_id, abs(chat.id), 'login_code:0', message, 'login')
    await _edit(message, text, buttons)
    await event.answer()


async def build_login_buttons():
    return [[Button.inline(t('login.btn.connect'), 'login_start')]]


# --------------------------------------------------------------------------
# Anmeldeschritte
# --------------------------------------------------------------------------

async def request_code(phone, user_id):
    """Anmeldecode anfordern. Returns (ok, text, buttons)."""
    main = await get_main_module()
    client = main.user_client

    try:
        if not client.is_connected():
            await client.connect()
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        logger.warning('Anmeldung: Telefonnummer von Telegram abgelehnt')
        return False, t('login.phone.invalid'), [[Button.inline(t('login.btn.retry'), 'login_start')]]
    except ApiIdInvalidError:
        logger.error('Anmeldung: API_ID und API_HASH passen nicht zusammen (.env prüfen)')
        return False, t('login.api_invalid'), [[Button.inline(t('menu.btn.cancel'), 'login_cancel')]]
    except FloodWaitError as e:
        logger.warning(f'Anmeldung: Telegram bremst aus, {e.seconds}s warten')
        return False, t('login.flood_wait', seconds=e.seconds), [[Button.inline(t('menu.btn.cancel'), 'login_cancel')]]
    except Exception as e:
        logger.error(f'Code anfordern fehlgeschlagen: {e}')
        logger.error(traceback.format_exc())
        return False, t('login.error', error=str(e)), [[Button.inline(t('login.btn.retry'), 'login_start')]]

    _pending[user_id] = {'phone': phone, 'hash': sent.phone_code_hash}
    buttons = [
        [Button.inline(t('login.btn.resend'), 'login_resend')],
        [Button.inline(t('menu.btn.cancel'), 'login_cancel')],
    ]
    return True, t('login.code.ask', prefix=CODE_PREFIX), buttons


async def _finish(event, sender_id, chat_id, message):
    """Anmeldung abgeschlossen: Dienste starten und Hauptmenü zeigen."""
    from handlers.button.menu import build_main_menu

    state_manager.clear_state(sender_id, chat_id)
    _pending.pop(sender_id, None)

    main = await get_main_module()
    name = ''
    try:
        me = await main.user_client.get_me()
        name = me.first_name or ''
    except Exception:
        pass

    # Zeitgesteuerte Dienste laufen erst, wenn ein Konto angemeldet ist
    try:
        if hasattr(main, 'start_account_services'):
            await main.start_account_services()
    except Exception as e:
        logger.error(f'Dienste nach der Anmeldung konnten nicht starten: {e}')

    await _edit(message, t('login.done', name=name), build_main_menu())
    return True


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Telefonnummer, Code und Passwort auswerten.

    Wird aus ``handlers/prompt_handlers.py`` aufgerufen.
    """
    kind = current_state.split(':')[0]
    text_input = (event.message.text or '').strip()

    main = await get_main_module()
    user_client = main.user_client

    # Telefonnummer
    if kind == 'login_phone':
        await _delete_input(event)
        phone = re.sub(r'[^\d+]', '', text_input)
        if len(phone) < 6:
            await _edit(
                message,
                t('login.phone.invalid'),
                [[Button.inline(t('login.btn.retry'), 'login_start')]],
            )
            return True

        ok, text, buttons = await request_code(phone, sender_id)
        if ok:
            state_manager.set_state(sender_id, chat_id, 'login_code:0', message, 'login')
        else:
            state_manager.clear_state(sender_id, chat_id)
        await _edit(message, text, buttons)
        return True

    # Anmeldecode – nur mit Präfix
    if kind == 'login_code':
        code = strip_prefix(text_input, CODE_PREFIX)
        await _delete_input(event)

        if code is None:
            await _edit(
                message,
                t('login.code.missing_prefix', prefix=CODE_PREFIX),
                [[Button.inline(t('login.btn.resend'), 'login_resend')],
                 [Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
            )
            return True

        code = re.sub(r'\D', '', code)
        store = _pending.get(sender_id)
        if not store:
            state_manager.clear_state(sender_id, chat_id)
            await _edit(message, t('login.alert.start_again'), await build_login_buttons())
            return True

        try:
            await user_client.sign_in(
                phone=store['phone'],
                code=code,
                phone_code_hash=store['hash'],
            )
        except SessionPasswordNeededError:
            state_manager.set_state(sender_id, chat_id, 'login_password:0', message, 'login')
            await _edit(
                message,
                t('login.password.ask', prefix=PASSWORD_PREFIX),
                [[Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
            )
            return True
        except PhoneCodeInvalidError:
            await _edit(
                message,
                t('login.code.invalid', prefix=CODE_PREFIX),
                [[Button.inline(t('login.btn.resend'), 'login_resend')],
                 [Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
            )
            return True
        except PhoneCodeExpiredError:
            await _edit(
                message,
                t('login.code.expired'),
                [[Button.inline(t('login.btn.resend'), 'login_resend')],
                 [Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
            )
            return True
        except FloodWaitError as e:
            state_manager.clear_state(sender_id, chat_id)
            await _edit(message, t('login.flood_wait', seconds=e.seconds), await build_login_buttons())
            return True
        except Exception as e:
            logger.error(f'Anmeldung fehlgeschlagen: {e}')
            logger.error(traceback.format_exc())
            state_manager.clear_state(sender_id, chat_id)
            await _edit(message, t('login.error', error=str(e)), await build_login_buttons())
            return True

        return await _finish(event, sender_id, chat_id, message)

    # Zwei-Faktor-Passwort – ebenfalls mit Präfix, wird nicht gespeichert
    if kind == 'login_password':
        password = strip_prefix(text_input, PASSWORD_PREFIX)
        await _delete_input(event)

        if password is None:
            await _edit(
                message,
                t('login.password.missing_prefix', prefix=PASSWORD_PREFIX),
                [[Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
            )
            return True

        try:
            await user_client.sign_in(password=password)
        except Exception as e:
            logger.error(f'Anmeldung mit Passwort fehlgeschlagen: {type(e).__name__}')
            await _edit(
                message,
                t('login.password.invalid', prefix=PASSWORD_PREFIX),
                [[Button.inline(t('menu.btn.cancel'), 'login_cancel')]],
            )
            return True
        finally:
            password = None

        return await _finish(event, sender_id, chat_id, message)

    return False
