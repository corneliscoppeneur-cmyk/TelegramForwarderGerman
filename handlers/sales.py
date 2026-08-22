"""Werbe-/Vermietungsnachricht an fremde Nutzer.

Schreibt ein Nicht-Admin dem Bot, antwortet dieser – sofern eingeschaltet –
mit dem hinterlegten Vermietungstext. So erfährt jeder, der neugierig ist,
dass und wie er den Forwarder mieten kann.

Bewusst schlank gehalten (nur bot_config + i18n), damit ``message_listener``
das ohne schwere Importe aufrufen kann.
"""

import logging
import time

from utils.bot_config import get_config
from utils.i18n import t

logger = logging.getLogger(__name__)

# Schlüssel im bot_config-Speicher
KEY_ENABLED = 'sales_enabled'
KEY_TEXT = 'sales_text'

# So lange wird demselben Nutzer nicht erneut geantwortet (Sekunden)
COOLDOWN = 6 * 60 * 60

# Zuletzt beantwortet je Nutzer (im Speicher; nach Neustart zurückgesetzt)
_last_reply = {}


def is_enabled():
    return get_config(KEY_ENABLED, '0') == '1'


def get_pitch():
    """Aktueller Vermietungstext (oder der Standardtext)."""
    return get_config(KEY_TEXT) or t('sales.default')


async def maybe_send_pitch(bot_client, event):
    """Fremdem Nutzer den Vermietungstext schicken – gedrosselt, wenn aktiv."""
    if not is_enabled():
        return

    sender_id = event.sender_id
    now = time.time()
    last = _last_reply.get(sender_id, 0)
    if now - last < COOLDOWN:
        return
    _last_reply[sender_id] = now

    try:
        await event.reply(get_pitch(), parse_mode='html', link_preview=False)
        logger.info(f'Vermietungstext an {sender_id} gesendet')
    except Exception as e:
        logger.error(f'Vermietungstext konnte nicht gesendet werden: {e}')
