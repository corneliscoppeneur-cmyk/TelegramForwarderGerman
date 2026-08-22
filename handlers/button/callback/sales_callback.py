"""Verwaltung des Vermietungs-/Werbetextes durch den Admin.

Ein-/Ausschalten und Bearbeiten des Textes, den der Bot an fremde Nutzer
schickt. Der Text liegt im ``bot_config``-Speicher und ist so ohne .env und
ohne Neustart änderbar.

Handler-Signatur wie im Dispatcher: ``(event, rule_id, session, message, data)``.
"""

import logging

from telethon import Button

from handlers.sales import KEY_ENABLED, KEY_TEXT, is_enabled, get_pitch
from managers.state_manager import state_manager
from utils.bot_config import set_config
from utils.i18n import t

logger = logging.getLogger(__name__)


def build_sales_screen():
    """Bildschirm (Text + Buttons) für die Vermietung aufbauen."""
    if is_enabled():
        status = t('sales.status.on')
        toggle = t('sales.btn.turn_off')
    else:
        status = t('sales.status.off')
        toggle = t('sales.btn.turn_on')

    text = t('sales.screen.text', status=status, preview=get_pitch())
    buttons = [
        [Button.inline(toggle, 'sales_toggle')],
        [Button.inline(t('sales.btn.edit'), 'sales_edit')],
        [Button.inline(t('menu.btn.back_main'), 'menu_main')],
    ]
    return text, buttons


async def _show(event, message):
    text, buttons = build_sales_screen()
    try:
        await message.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception as e:
        # Ungültige HTML-Formatierung im Text: ohne Vorschau anzeigen und warnen
        if 'not modified' in str(e).lower():
            return
        logger.warning(f'Vermietungs-Bildschirm mit Vorschau fehlgeschlagen: {e}')
        safe = t('sales.screen.text_no_preview',
                 status=t('sales.status.on') if is_enabled() else t('sales.status.off'))
        buttons = [
            [Button.inline(t('sales.btn.edit'), 'sales_edit')],
            [Button.inline(t('menu.btn.back_main'), 'menu_main')],
        ]
        await message.edit(safe, buttons=buttons, parse_mode='html', link_preview=False)


async def callback_sales(event, rule_id, session, message, data):
    """Vermietungs-Bildschirm anzeigen."""
    await _show(event, message)
    await event.answer()


async def callback_sales_toggle(event, rule_id, session, message, data):
    """Automatische Antwort ein- oder ausschalten."""
    now_on = not is_enabled()
    set_config(KEY_ENABLED, '1' if now_on else '0')
    await _show(event, message)
    await event.answer(t('sales.alert.turned_on') if now_on else t('sales.alert.turned_off'))


async def callback_sales_edit(event, rule_id, session, message, data):
    """Nach einem neuen Text fragen."""
    chat = await event.get_chat()
    state_manager.set_state(event.sender_id, abs(chat.id), 'sales_text:0', message, 'sales')
    await message.edit(
        t('sales.edit.ask'),
        buttons=[[Button.inline(t('menu.btn.cancel'), 'sales')]],
        parse_mode='html', link_preview=False,
    )
    await event.answer()


async def apply_text_input(event, client, sender_id, chat_id, current_state, message):
    """Neuen Vermietungstext speichern. Aus ``prompt_handlers`` aufgerufen."""
    new_text = (event.message.text or '').strip()

    try:
        await event.message.delete()
    except Exception:
        pass

    if not new_text:
        await message.edit(
            t('sales.edit.empty'),
            buttons=[[Button.inline(t('menu.btn.back_main'), 'sales')]],
            parse_mode='html', link_preview=False,
        )
        return True

    set_config(KEY_TEXT, new_text)
    state_manager.clear_state(sender_id, chat_id)
    await _show(event, message)
    return True
