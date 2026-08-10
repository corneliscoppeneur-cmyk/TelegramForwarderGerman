"""Info-Bildschirm, der die Einstellungs-Schalter in Alltagssprache erklärt.

Erreichbar über den „Erklärung"-Knopf auf dem Einstellungs- und dem
„+ Mehr"-Bildschirm. Reiner Lesetext, ändert nichts an der Weiterleitung.

Handler-Signatur wie im Dispatcher: ``(event, rule_id, session, message, data)``.
"""

import logging

from telethon import Button

from utils.i18n import t

logger = logging.getLogger(__name__)


async def callback_settings_info(event, rule_id, session, message, data):
    """Erklärung der Schalter anzeigen."""
    rid = str(rule_id).split(':')[0] if rule_id else ''
    buttons = [[Button.inline(t('common.btn.back'), f'rule_settings:{rid}')]]
    try:
        await event.edit(t('settings.info.text'), buttons=buttons,
                         parse_mode='html', link_preview=False)
    except Exception as e:
        if 'not modified' not in str(e).lower():
            logger.error(f'Info-Bildschirm konnte nicht angezeigt werden: {e}')
    await event.answer()
