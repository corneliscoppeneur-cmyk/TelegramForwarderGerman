"""Hauptmenü und Weiterleitungs-Übersicht.

Baustein für die button-basierte Bedienung: liefert Texte und Inline-Buttons
für das Hauptmenü, die Liste aller Weiterleitungen und die Detailkarte einer
einzelnen Weiterleitung.

Bewusst nur Aufbau (Text + Buttons), kein Versand – der Versand passiert in den
Callback-Handlern bzw. in ``handle_start_command``. Alle Nutzertexte laufen über
``t()`` aus ``lang/*.json``.
"""

import logging
from html import escape

from telethon import Button

from enums.enums import ForwardMode
from models.models import ForwardRule, Keyword, ReplaceRule
from utils.i18n import t

logger = logging.getLogger(__name__)

# Weiterleitungen pro Seite in der Übersicht (Telegram: max. 100 Buttons je Nachricht)
RULES_PER_MENU_PAGE = 8

# Maximale Länge eines Chat-Namens in einer Button-Beschriftung
MAX_NAME_LEN = 22


def shorten(name, max_len=MAX_NAME_LEN):
    """Chat-Namen für Button-Beschriftungen kürzen."""
    if not name:
        return t('menu.unknown_chat')
    name = name.strip()
    if len(name) <= max_len:
        return name
    return name[:max_len - 1] + '…'


def main_menu_text(connected=True):
    """Begrüßungstext des Hauptmenüs."""
    if not connected:
        return t('login.needed.text')
    return t('menu.main.text')


def build_main_menu(connected=True):
    """Buttons des Hauptmenüs.

    Ohne verbundenes Telegram-Konto führt der einzige Weg über die Anmeldung –
    ohne Konto kann der Bot keine Nachrichten mitlesen.
    """
    if not connected:
        return [
            [Button.inline(t('login.btn.connect'), 'login_start')],
            [Button.inline(t('menu.btn.how_it_works'), 'menu_help')],
        ]

    return [
        [Button.inline(t('menu.btn.new_forward'), 'wizard_start')],
        [Button.inline(t('menu.btn.my_forwards'), 'menu_rules:0')],
        [Button.inline(t('menu.btn.how_it_works'), 'menu_help')],
        [Button.inline(t('menu.btn.sales'), 'sales')],
    ]


def describe_mode(rule):
    """Weiterleitungs-Modus in Alltagssprache beschreiben."""
    if rule.forward_mode == ForwardMode.WHITELIST:
        return t('menu.mode.only_with_words')
    if rule.forward_mode == ForwardMode.BLACKLIST:
        return t('menu.mode.all_except_words')
    return t('menu.mode.combined')


def build_rule_overview(session, page=0):
    """Liste aller Weiterleitungen aufbauen.

    Returns:
        (text, buttons) – fertig für ``message.edit`` / ``event.respond``
    """
    total = session.query(ForwardRule).count()

    if total == 0:
        return t('menu.rules.empty'), [
            [Button.inline(t('menu.btn.new_forward'), 'wizard_start')],
            [Button.inline(t('menu.btn.back_main'), 'menu_main')],
        ]

    total_pages = (total + RULES_PER_MENU_PAGE - 1) // RULES_PER_MENU_PAGE
    page = max(0, min(page, total_pages - 1))

    rules = (session.query(ForwardRule)
             .order_by(ForwardRule.id)
             .offset(page * RULES_PER_MENU_PAGE)
             .limit(RULES_PER_MENU_PAGE)
             .all())

    buttons = []
    for rule in rules:
        status = '🟢' if rule.enable_rule else '⚪️'
        label = f'{status} {shorten(rule.source_chat.name)} ➜ {shorten(rule.target_chat.name)}'
        buttons.append([Button.inline(label, f'rule_card:{rule.id}')])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(Button.inline(t('common.page.prev'), f'menu_rules:{page - 1}'))
        nav.append(Button.inline(f'{page + 1}/{total_pages}', 'noop'))
        if page < total_pages - 1:
            nav.append(Button.inline(t('common.page.next'), f'menu_rules:{page + 1}'))
        buttons.append(nav)

    buttons.append([Button.inline(t('menu.btn.new_forward'), 'wizard_start')])
    buttons.append([Button.inline(t('menu.btn.back_main'), 'menu_main')])

    return t('menu.rules.text', count=total), buttons


def build_rule_card(session, rule_id):
    """Detailkarte einer Weiterleitung aufbauen.

    Returns:
        (text, buttons) oder (None, None), wenn es die Weiterleitung nicht gibt.
    """
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return None, None

    keyword_count = session.query(Keyword).filter(Keyword.rule_id == rule.id).count()
    replace_count = session.query(ReplaceRule).filter(ReplaceRule.rule_id == rule.id).count()

    text = t(
        'menu.card.text',
        status=t('menu.status.on') if rule.enable_rule else t('menu.status.off'),
        source=escape(rule.source_chat.name or t('menu.unknown_chat')),
        target=escape(rule.target_chat.name or t('menu.unknown_chat')),
        mode=describe_mode(rule),
        words=keyword_count,
        replaces=replace_count,
    )

    toggle_label = t('menu.btn.turn_off') if rule.enable_rule else t('menu.btn.turn_on')
    repeat_label = t('menu.btn.repeat')
    if rule.enable_repeat:
        repeat_label += ' ✅'

    buttons = [
        [Button.inline(toggle_label, f'rule_toggle:{rule.id}')],
        [
            Button.inline(t('menu.btn.words'), f'words:{rule.id}:0'),
            Button.inline(t('menu.btn.replaces'), f'replaces:{rule.id}:0'),
        ],
        [
            Button.inline(t('menu.btn.settings'), f'rule_settings:{rule.id}'),
            Button.inline(repeat_label, f'repeat:{rule.id}'),
        ],
        [Button.inline(t('menu.btn.paid'), f'paid:{rule.id}')],
        [
            Button.inline(t('menu.btn.edit_source'), f'edit_src:{rule.id}'),
            Button.inline(t('menu.btn.edit_target'), f'edit_dst:{rule.id}'),
        ],
        [
            Button.inline(t('menu.btn.copy'), f'copy_rule:{rule.id}'),
            Button.inline(t('menu.btn.delete'), f'rule_delete_ask:{rule.id}'),
        ],
        [Button.inline(t('menu.btn.back_rules'), 'menu_rules:0')],
    ]

    return text, buttons


def build_delete_confirm(session, rule_id):
    """Sicherheitsabfrage vor dem Löschen einer Weiterleitung."""
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        return None, None

    text = t(
        'menu.delete.confirm',
        source=escape(rule.source_chat.name or t('menu.unknown_chat')),
        target=escape(rule.target_chat.name or t('menu.unknown_chat')),
    )
    buttons = [
        [Button.inline(t('menu.btn.delete_yes'), f'perform_delete_rule:{rule.id}')],
        [Button.inline(t('menu.btn.cancel'), f'rule_card:{rule.id}')],
    ]
    return text, buttons


def build_help_page():
    """Kurzanleitung „So funktioniert's“."""
    buttons = [
        [Button.inline(t('menu.btn.new_forward'), 'wizard_start')],
        [Button.inline(t('menu.btn.back_main'), 'menu_main')],
    ]
    return t('menu.help.text'), buttons
