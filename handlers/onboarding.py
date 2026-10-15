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

import aiohttp
from telethon import Button

from handlers.subscription import is_admin_user
from models.models import ManagedContainer, PendingBotRequest, get_session
from utils.bot_config import get_config, set_config
from utils.host_jobs import host_jobs_available, run_host_job
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


def _support_url():
    """Support-Link aus SUPPORT_HANDLE (``@name`` oder t.me-URL)."""
    raw = (os.getenv('SUPPORT_HANDLE', '@tele420') or '').strip()
    if not raw:
        return None
    if raw.startswith(('http://', 'https://', 't.me/')):
        return raw if raw.startswith('http') else f'https://{raw}'
    return f'https://t.me/{raw.lstrip("@")}'


def _network_url():
    """Link zum Gruppennetzwerk aus NETWORK_URL (optional)."""
    return (os.getenv('NETWORK_URL', '') or '').strip() or None


def _link_buttons():
    """Externe Link-Buttons: Support + Gruppennetzwerk (nur wenn konfiguriert)."""
    rows = []
    support = _support_url()
    network = _network_url()
    if support:
        rows.append([Button.url(t('onboard.btn.support'), support)])
    if network:
        rows.append([Button.url(t('onboard.btn.network'), network)])
    return rows


def build_welcome_stranger():
    """Einstieg für einen Fremden: erklärt kurz und bietet die Aktion an."""
    text = t('onboard.welcome.text')
    if _network_url():
        text += '\n\n' + t('onboard.network.note')
    buttons = []
    # Im Main-Bot ist der geführte Selbst-Weg die Haupt-Aktion.
    if _is_main_bot():
        buttons.append([Button.inline(t('onboard.btn.create_bot'), 'onboard_create_bot')])
    buttons += [
        [Button.inline(t('onboard.btn.request'), 'onboard_request')],
        [Button.inline(t('onboard.btn.selfbot'), 'onboard_selfbot')],
        [Button.inline(t('onboard.btn.how'), 'onboard_how')],
    ] + _link_buttons()
    return text, buttons


def build_how_it_works():
    text = t('onboard.how.text')
    buttons = [
        [Button.inline(t('onboard.btn.request'), 'onboard_request')],
        [Button.inline(t('onboard.btn.selfbot'), 'onboard_selfbot')],
        [Button.inline(t('common.btn.back'), 'onboard_home')],
    ] + _link_buttons()
    return text, buttons


def build_selfbot_guide():
    """Kunde will eigenen Bot-Token schicken: Schritt-für-Schritt @BotFather."""
    text = t('onboard.selfbot.text')
    buttons = [
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


async def callback_onboard_selfbot(event, rule_id, session, message, data):
    text, buttons = build_selfbot_guide()
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            raise
    await event.answer()


async def callback_onboard_create_bot(event, rule_id, session, message, data):
    """Geführter BotFather-Ablauf (nur Main-Bot, pay-first).

    Zeigt Schritt-für-Schritt, wie der Kunde bei @BotFather selbst einen Bot
    erstellt. Danach schickt er den Token als ``mybot <token>`` – der Rest läuft
    über :func:`handle_mybot_command` (Deploy, bei AUTO_APPROVE_SELFBOT direkt).
    """
    sender_id = event.sender_id

    # Pay-first: ohne aktives Abo/Test erst zur Paywall.
    if _is_main_bot():
        from handlers.subscription import is_active
        if not is_active(sender_id):
            from handlers.button.payment import build_billing_screen
            _, buttons = build_billing_screen(sender_id)
            try:
                await message.edit(
                    t('onboard.paywall.text'), buttons=buttons,
                    parse_mode='html', link_preview=False)
            except Exception as e:
                if 'not modified' not in str(e).lower():
                    raise
            await event.answer()
            return

    # Vorschlag für den Bot-Benutzernamen aus dem Telegram-Username.
    try:
        sender = await event.get_sender()
        suggest = (getattr(sender, 'username', None) or 'mein').lower()
    except Exception:
        suggest = 'mein'

    text = t('onboard.create.text', suggest=suggest)
    buttons = [
        [Button.url(t('onboard.create.btn.open_botfather'), 'https://t.me/BotFather')],
        [Button.inline(t('common.btn.back'), 'onboard_home')],
    ]

    # Optionales Anleitungsbild (Pfad oder Telegram file_id) via BOTFATHER_IMAGE.
    image = (os.getenv('BOTFATHER_IMAGE', '') or '').strip()
    try:
        if image:
            await event.client.send_file(
                sender_id, image, caption=text, buttons=buttons, parse_mode='html')
            try:
                await message.delete()
            except Exception:
                pass
        else:
            await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            logger.error(f'BotFather-Anleitung konnte nicht gezeigt werden: {e}')
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

# Kunde schickt seinen eigenen Bot-Token: ``mybot 1234567890:ABCdef...``
_MYBOT_RE = re.compile(r'^mybot\s+(\d{5,}:[A-Za-z0-9_-]{20,})\s*$', re.IGNORECASE)


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
        # Bot-Username automatisch aus dem Token holen (via Telegram Bot HTTP-API)
        bot_username = await _bot_username_from_token(bot_token)
        bot_link = f'https://t.me/{bot_username}' if bot_username else t('onboard.no_bot_link')
        support_handle = os.getenv('SUPPORT_HANDLE', '@tele420')

        # In DB registrieren, damit der Cleanup-Scheduler ihn kennt.
        _register_container(customer_id)

        # Admin: Bestätigung mit klickbarem Link (zum Weiterleiten als Backup)
        try:
            await status.edit(
                t('onboard.anlegen.done',
                  id=customer_id,
                  bot_link=bot_link,
                  output=output[-500:]),
                parse_mode='html',
                link_preview=False,
            )
        except Exception:
            pass

        # Kunde benachrichtigen (falls er den Bot noch nicht geblockt hat)
        try:
            await bot_client.send_message(
                customer_id,
                t('onboard.customer.ready',
                  bot_link=bot_link,
                  customer_id=customer_id,
                  support=support_handle),
                parse_mode='html',
                link_preview=False,
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


def _register_container(customer_id):
    """Neu angelegten Kunden-Container in DB festhalten (für Cleanup)."""
    customers_dir = os.getenv('CUSTOMERS_DIR', '/root/customer_bots')
    path = f'{customers_dir}/customer-{customer_id}'
    container_name = f'telegram-forwarder-customer-{customer_id}'

    session = get_session()
    try:
        row = session.query(ManagedContainer).get(int(customer_id))
        if row:
            # Wieder-Deploy nach Löschung: Timer zurücksetzen
            row.container_name = container_name
            row.path = path
            row.created_at = datetime.utcnow().date().isoformat()
            row.warned_at = None
            row.kept_until = None
            row.deleted_at = None
        else:
            session.add(ManagedContainer(
                customer_id=int(customer_id),
                container_name=container_name,
                path=path,
                created_at=datetime.utcnow().date().isoformat(),
            ))
        session.commit()
        logger.info(f'Container-Verwaltung: Kunde {customer_id} registriert')
    except Exception as e:
        session.rollback()
        logger.error(f'Container-Verwaltung: Registrierung fehlgeschlagen: {e}')
    finally:
        session.close()


async def handle_keep_command(event, bot_client):
    """``/keep <id>`` – Container von der Aufräumliste ausnehmen (30 Tage)."""
    if not is_admin_user(event.sender_id):
        return

    parts = (event.message.text or '').strip().split()
    if len(parts) != 2 or not parts[1].lstrip('-').isdigit():
        await event.reply(t('onboard.keep.usage'), parse_mode='html')
        return
    customer_id = int(parts[1])

    session = get_session()
    try:
        row = session.query(ManagedContainer).get(customer_id)
        if not row:
            await event.reply(t('onboard.keep.unknown', id=customer_id), parse_mode='html')
            return
        keep_until = (datetime.utcnow().date() + timedelta(days=30)).isoformat()
        row.kept_until = keep_until
        row.warned_at = None
        session.commit()
        await event.reply(t('onboard.keep.done', id=customer_id, until=keep_until), parse_mode='html')
    except Exception as e:
        session.rollback()
        logger.error(f'/keep fehlgeschlagen: {e}')
        await event.reply(t('onboard.keep.failed', error=str(e)), parse_mode='html')
    finally:
        session.close()


async def _bot_username_from_token(bot_token):
    """Holt den Bot-Nutzernamen (ohne @) via getMe – braucht keine Session."""
    try:
        url = f'https://api.telegram.org/bot{bot_token}/getMe'
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get('ok'):
                    return data['result'].get('username')
    except Exception as e:
        logger.warning(f'Bot-Username konnte nicht aus Token gelesen werden: {e}')
    return None


async def _run_deploy(customer_id, bot_token):
    """Deploy-Skript auf dem VPS ausführen."""
    script = os.getenv('DEPLOY_SCRIPT_PATH', DEFAULT_DEPLOY_SCRIPT)
    if not os.path.exists(script):
        # Im Container: Auftrag an den Host-Dienst übergeben
        if host_jobs_available():
            return await run_host_job('deploy', [customer_id, bot_token], timeout=900)
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


# --------------------------------------------------------------------------
# Kunden-Selbstbedienung: mybot <token>  →  Pay-first + optional vollautomatisch
# --------------------------------------------------------------------------

def _is_main_bot():
    """True, wenn dies der zentrale Betreiber-/Abrechnungs-Bot ist (MAIN_BOT=1).

    Nur im Main-Bot laufen Paywall und vollautomatische Selbst-Anbindung. In
    Kunden-Containern ist MAIN_BOT nicht gesetzt (deploy_customer_bot.sh kopiert
    es nicht) – deren Verhalten bleibt unverändert.
    """
    return (os.getenv('MAIN_BOT', '') or '').strip().lower() in ('1', 'true', 'yes')


def _auto_approve_selfbot():
    """True, wenn nach bezahltem Abo ohne Admin-Klick deployt werden soll."""
    return (os.getenv('AUTO_APPROVE_SELFBOT', '') or '').strip().lower() in ('1', 'true', 'yes')


async def _send_paywall(bot_client, customer_id):
    """Zahlungsaufforderung + Paket-Buttons schicken (Pay-first)."""
    from handlers.button.payment import build_billing_screen
    try:
        _, buttons = build_billing_screen(customer_id)
        await bot_client.send_message(
            customer_id, t('onboard.paywall.text'),
            buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        logger.error(f'Paywall konnte nicht gesendet werden: {e}')


async def _auto_deploy_selfbot(bot_client, customer_id, bot_token, bot_username):
    """Nach bezahltem Abo den Kunden-Bot ohne Admin-Freigabe anlegen."""
    try:
        await bot_client.send_message(
            customer_id, t('onboard.mybot.deploying'), parse_mode='html')
    except Exception:
        pass

    ok, output = await _run_deploy(customer_id, bot_token)

    if ok:
        if not bot_username:
            bot_username = await _bot_username_from_token(bot_token)
        bot_link = f'https://t.me/{bot_username}' if bot_username else t('onboard.no_bot_link')
        support_handle = os.getenv('SUPPORT_HANDLE', '@tele420')
        _register_container(customer_id)
        try:
            await bot_client.send_message(
                customer_id,
                t('onboard.customer.ready',
                  bot_link=bot_link, customer_id=customer_id, support=support_handle),
                parse_mode='html', link_preview=False)
        except Exception:
            pass
        for admin_id in _admin_ids():
            try:
                await bot_client.send_message(
                    admin_id,
                    t('onboard.anlegen.done', id=customer_id, bot_link=bot_link, output=output[-500:]),
                    parse_mode='html', link_preview=False)
            except Exception:
                pass
    else:
        try:
            await bot_client.send_message(
                customer_id, t('onboard.mybot.deploy_failed'), parse_mode='html')
        except Exception:
            pass
        for admin_id in _admin_ids():
            try:
                await bot_client.send_message(
                    admin_id, t('onboard.anlegen.failed', output=output[-800:]), parse_mode='html')
            except Exception:
                pass


async def handle_mybot_command(event, bot_client):
    """Kunde schickt eigenen Bot-Token: ``mybot <token>``.

    Token wird geprüft (getMe), die Nachricht sofort gelöscht (Geheimnis),
    die Anfrage in der DB geparkt und dem Admin mit Freigabe-Buttons gemeldet.
    Deploy läuft erst nach Admin-Klick auf „Freigeben".
    """
    sender_id = event.sender_id
    text = (event.message.text or '').strip()
    match = _MYBOT_RE.match(text)

    # Token-Nachricht sofort löschen – enthält ein Geheimnis.
    try:
        await event.message.delete()
    except Exception:
        pass

    if not match:
        try:
            await bot_client.send_message(
                sender_id, t('onboard.mybot.usage'), parse_mode='html', link_preview=False)
        except Exception:
            pass
        return

    bot_token = match.group(1)

    # Token gegen Telegram prüfen, bevor wir den Admin behelligen.
    bot_username = await _bot_username_from_token(bot_token)
    if not bot_username:
        try:
            await bot_client.send_message(
                sender_id, t('onboard.mybot.invalid'), parse_mode='html', link_preview=False)
        except Exception:
            pass
        return

    # Pay-first: im Main-Bot nur weiter, wenn Abo/Test aktiv bezahlt ist.
    if _is_main_bot():
        from handlers.subscription import is_active
        if not is_active(sender_id):
            await _send_paywall(bot_client, sender_id)
            return

    # Absenderdaten sammeln
    try:
        sender = await event.get_sender()
        username = getattr(sender, 'username', None) or ''
        name = ((getattr(sender, 'first_name', None) or '') + ' '
                + (getattr(sender, 'last_name', None) or '')).strip() or t('onboard.stranger')
    except Exception:
        username, name = '', t('onboard.stranger')

    # Vollautomatisch: bezahlt + Flag → direkt deployen, kein Admin-Klick.
    if _is_main_bot() and _auto_approve_selfbot():
        await _auto_deploy_selfbot(bot_client, sender_id, bot_token, bot_username)
        return

    _save_pending(sender_id, bot_token, username, name, bot_username)

    # Kunde: Eingangsbestätigung
    try:
        await bot_client.send_message(
            sender_id, t('onboard.mybot.received'), parse_mode='html', link_preview=False)
    except Exception:
        pass

    # Admin: Freigabe-Anfrage mit Buttons
    await _notify_admins_approval(bot_client, sender_id, name, username, bot_username)


def _save_pending(customer_id, bot_token, username, name, bot_username):
    session = get_session()
    try:
        row = session.query(PendingBotRequest).get(int(customer_id))
        if row:
            row.bot_token = bot_token
            row.username = username
            row.name = name
            row.bot_username = bot_username
            row.requested_at = datetime.utcnow().isoformat(timespec='seconds')
        else:
            session.add(PendingBotRequest(
                customer_id=int(customer_id),
                bot_token=bot_token,
                username=username,
                name=name,
                bot_username=bot_username,
                requested_at=datetime.utcnow().isoformat(timespec='seconds'),
            ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f'Pending-Anfrage speichern fehlgeschlagen: {e}')
    finally:
        session.close()


async def _notify_admins_approval(bot_client, customer_id, name, username, bot_username):
    """Freigabe-Anfrage mit Buttons an alle Admins senden."""
    admins = _admin_ids()
    if not admins:
        logger.warning('mybot: kein ADMIN_USER_ID gesetzt – keine Freigabe-Meldung möglich')
        return

    handle = f'@{username}' if username else t('onboard.no_username')
    text = t('onboard.admin.notify_approval',
             name=name, handle=handle, id=customer_id, bot=bot_username)
    buttons = [[
        Button.inline(t('onboard.cadm.btn.approve'), f'cadm_ok:{customer_id}'),
        Button.inline(t('onboard.cadm.btn.reject'), f'cadm_no:{customer_id}'),
    ]]

    for admin_id in admins:
        try:
            await bot_client.send_message(
                admin_id, text, buttons=buttons, parse_mode='html', link_preview=False)
            logger.info(f'mybot-Freigabe-Anfrage an Admin {admin_id} verschickt')
        except Exception as e:
            logger.warning(f'mybot-Freigabe-Anfrage an Admin {admin_id} fehlgeschlagen: {e}')


async def callback_cadm_approve(event, rule_id, session, message, data):
    """Admin klickt „Freigeben" – Container bauen und Kunde benachrichtigen."""
    try:
        customer_id = int(rule_id)
    except (TypeError, ValueError):
        await event.answer()
        return

    row = session.query(PendingBotRequest).get(customer_id)
    if not row:
        await event.answer(t('onboard.cadm.gone'), alert=True)
        return

    bot_token = row.bot_token
    bot_username = row.bot_username

    await event.answer(t('onboard.cadm.deploying'))
    try:
        await message.edit(t('onboard.anlegen.started', id=customer_id), parse_mode='html')
    except Exception:
        pass

    ok, output = await _run_deploy(customer_id, bot_token)

    if ok:
        if not bot_username:
            bot_username = await _bot_username_from_token(bot_token)
        bot_link = f'https://t.me/{bot_username}' if bot_username else t('onboard.no_bot_link')
        support_handle = os.getenv('SUPPORT_HANDLE', '@tele420')

        _register_container(customer_id)
        try:
            session.delete(row)
            session.commit()
        except Exception:
            session.rollback()

        try:
            await message.edit(
                t('onboard.anlegen.done', id=customer_id, bot_link=bot_link, output=output[-500:]),
                parse_mode='html', link_preview=False)
        except Exception:
            pass

        try:
            await event.client.send_message(
                customer_id,
                t('onboard.customer.ready',
                  bot_link=bot_link, customer_id=customer_id, support=support_handle),
                parse_mode='html', link_preview=False)
        except Exception as e:
            logger.info(f'Kunde {customer_id} konnte nicht benachrichtigt werden: {e}')
    else:
        # Fehlgeschlagen: Zeile behalten, Buttons wieder anbieten für Retry.
        buttons = [[
            Button.inline(t('onboard.cadm.btn.approve'), f'cadm_ok:{customer_id}'),
            Button.inline(t('onboard.cadm.btn.reject'), f'cadm_no:{customer_id}'),
        ]]
        try:
            await message.edit(
                t('onboard.anlegen.failed', output=output[-800:]),
                buttons=buttons, parse_mode='html', link_preview=False)
        except Exception:
            pass


async def callback_cadm_reject(event, rule_id, session, message, data):
    """Admin klickt „Ablehnen" – Anfrage verwerfen, Kunde informieren."""
    try:
        customer_id = int(rule_id)
    except (TypeError, ValueError):
        await event.answer()
        return

    row = session.query(PendingBotRequest).get(customer_id)
    if row:
        try:
            session.delete(row)
            session.commit()
        except Exception:
            session.rollback()

    try:
        await message.edit(t('onboard.cadm.rejected', id=customer_id), parse_mode='html')
    except Exception:
        pass

    try:
        await event.client.send_message(
            customer_id,
            t('onboard.customer.rejected', support=os.getenv('SUPPORT_HANDLE', '@tele420')),
            parse_mode='html', link_preview=False)
    except Exception:
        pass

    await event.answer()
