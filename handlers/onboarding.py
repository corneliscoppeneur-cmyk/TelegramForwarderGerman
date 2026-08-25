"""Onboarding fremder Interessenten und halbautomatisches Container-Deployment.

Ablauf:

1. Fremder klickt ``/start`` und danach den Button "Bot anfordern".
2. Der Bot schickt dem Admin eine **Schritt-für-Schritt-Anleitung** mit der
   Kunden-ID – so weiß der Admin auch Wochen später sofort, was zu tun ist.
3. Admin holt einen neuen Bot vom @BotFather, schickt an den Betreiber-Bot
   ``/anlegen <kunden_id> <bot_token>``. Der Deploy-Handler ruft dann ein
   Bash-Skript auf, das den neuen Container startet.
4. Nach Erfolg bekommt der Kunde automatisch den Link zu seinem eigenen Bot.
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta

from telethon import Button

from handlers.subscription import is_admin_user
from utils.bot_config import get_config, set_config
from utils.i18n import t

logger = logging.getLogger(__name__)

# Ein Bash-Skript auf dem VPS, das einen neuen Container aufsetzt.
# Erwartet: DEPLOY_SCRIPT_PATH in .env, sonst wird ein Standardpfad genutzt.
DEFAULT_DEPLOY_SCRIPT = '/root/deploy_customer_bot.sh'

# Zwischenspeicher: {sender_id: {'username': str, 'name': str, 'at': datetime}}
_pending_requests = {}

# Cooldown, damit ein Fremder nicht zwanzigmal "Bot anfordern" klickt
REQUEST_COOLDOWN = 30 * 60  # 30 Minuten


def _admin_ids():
    raw = os.getenv('ADMIN_USER_ID', '')
    ids = set()
    for part in raw.split(','):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                pass
    return ids


def build_welcome_stranger():
    """Einstieg für einen Fremden: erklärt kurz und bietet die Aktion an."""
    text = t('onboard.welcome.text')
    buttons = [
        [Button.inline(t('onboard.btn.request'), 'onboard_request')],
        [Button.inline(t('onboard.btn.how'), 'onboard_how')],
    ]
    return text, buttons


def build_how_it_works():
    text = t('onboard.how.text')
    buttons = [
        [Button.inline(t('onboard.btn.request'), 'onboard_request')],
        [Button.inline(t('common.btn.back'), 'onboard_home')],
    ]
    return text, buttons


async def show_stranger_home(bot_client, event):
    """Wird aus ``message_listener.handle_bot_message`` aufgerufen (statt Sales-Pitch)."""
    text, buttons = build_welcome_stranger()
    try:
        await event.reply(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        logger.error(f'Onboarding-Willkommen konnte nicht gesendet werden: {e}')


async def callback_onboard_home(event, rule_id, session, message, data):
    text, buttons = build_welcome_stranger()
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise
    await event.answer()


async def callback_onboard_how(event, rule_id, session, message, data):
    text, buttons = build_how_it_works()
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise
    await event.answer()


async def callback_onboard_request(event, rule_id, session, message, data):
    """Fremder klickt „Bot anfordern" – schickt Admin eine Anleitung."""
    sender_id = event.sender_id
    now = time.time()

    last = _pending_requests.get(sender_id, {}).get('at_ts', 0)
    if now - last < REQUEST_COOLDOWN:
        await event.answer(t('onboard.alert.already_sent'), alert=True)
        return

    # Absenderdaten sammeln
    try:
        sender = await event.get_sender()
        username = getattr(sender, 'username', None) or ''
        name = ((getattr(sender, 'first_name', None) or '') + ' '
                + (getattr(sender, 'last_name', None) or '')).strip() or t('onboard.stranger')
    except Exception:
        username, name = '', t('onboard.stranger')

    _pending_requests[sender_id] = {
        'username': username, 'name': name, 'at_ts': now,
        'at': datetime.utcnow().isoformat(timespec='seconds'),
    }

    # Bot dem Admin melden
    await _notify_admins(event.client, sender_id, name, username)

    # Bestätigung an den Fremden
    try:
        await message.edit(
            t('onboard.request.sent', name=name),
            buttons=[[Button.inline(t('common.btn.close'), 'onboard_close')]],
            parse_mode='html',
        )
    except Exception as e:
        if 'not modified' not in str(e).lower():
            logger.warning(f'Onboarding-Bestätigung konnte nicht angezeigt werden: {e}')
    await event.answer()


async def callback_onboard_close(event, rule_id, session, message, data):
    try:
        await message.delete()
    except Exception:
        pass
    await event.answer()


async def _notify_admins(bot_client, customer_id, name, username):
    """Schritt-für-Schritt-Anleitung + fertigen ``/anlegen``-Befehl an den Admin senden."""
    admins = _admin_ids()
    if not admins:
        logger.warning('Onboarding: kein ADMIN_USER_ID gesetzt – keine Benachrichtigung möglich')
        return

    handle = f'@{username}' if username else t('onboard.no_username')
    text = t(
        'onboard.admin.notify',
        name=name,
        handle=handle,
        id=customer_id,
    )

    for admin_id in admins:
        try:
            await bot_client.send_message(
                admin_id,
                text,
                parse_mode='html',
                link_preview=False,
            )
            logger.info(f'Onboarding-Benachrichtigung an Admin {admin_id} verschickt')
        except Exception as e:
            logger.warning(f'Onboarding-Benachrichtigung an Admin {admin_id} fehlgeschlagen: {e}')


# --------------------------------------------------------------------------
# Admin-Befehl: /anlegen <kunden_id> <bot_token>
# --------------------------------------------------------------------------

_ANLEGEN_RE = re.compile(r'^/anlegen\s+(-?\d+)\s+(\S+)\s*$')


async def handle_anlegen_command(event, bot_client):
    """Admin-Befehl zum Anlegen eines neuen Kunden-Containers.

    Aufruf:  ``/anlegen 123456789 8123456:AA...token``
    """
    if not is_admin_user(event.sender_id):
        return  # normale Nutzer werden von handle_bot_message schon abgefangen

    text = event.message.text or ''
    match = _ANLEGEN_RE.match(text.strip())
    if not match:
        await event.reply(t('onboard.anlegen.usage'), parse_mode='html', link_preview=False)
        return

    customer_id = int(match.group(1))
    bot_token = match.group(2)

    # Kurze Rückmeldung, damit der Admin weiß dass der Deploy läuft
    status = await event.reply(t('onboard.anlegen.started', id=customer_id), parse_mode='html')

    ok, output = await _run_deploy(customer_id, bot_token)

    if ok:
        # Botname aus dem Token ableiten (@BotFather nennt ihn erst nach Anlage
        # – der Admin fügt bei Bedarf im Deploy-Skript einen Link ein)
        try:
            await status.edit(
                t('onboard.anlegen.done', id=customer_id, output=output[-600:]),
                parse_mode='html',
                link_preview=False,
            )
        except Exception:
            pass

        # Kunde benachrichtigen (falls wir seine ID kennen und er noch offen ist)
        try:
            await bot_client.send_message(
                customer_id,
                t('onboard.customer.ready'),
                parse_mode='html',
            )
        except Exception as e:
            logger.info(f'Kunde {customer_id} konnte nicht direkt benachrichtigt werden: {e}')
    else:
        try:
            await status.edit(
                t('onboard.anlegen.failed', output=output[-800:]),
                parse_mode='html',
                link_preview=False,
            )
        except Exception:
            pass


async def _run_deploy(customer_id, bot_token):
    """Deploy-Skript auf dem VPS ausführen."""
    script = os.getenv('DEPLOY_SCRIPT_PATH', DEFAULT_DEPLOY_SCRIPT)
    if not os.path.exists(script):
        return False, f'Deploy-Skript nicht gefunden: {script}'

    try:
        proc = await asyncio.create_subprocess_exec(
            'bash', script, str(customer_id), bot_token,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            return False, 'Deploy-Timeout (>3 Minuten)'

        output = (stdout or b'').decode('utf-8', errors='replace')
        return proc.returncode == 0, output
    except Exception as e:
        logger.error(f'Deploy fehlgeschlagen: {e}')
        return False, str(e)
