import os
from utils.settings import load_ai_models
from enums.enums import ForwardMode, MessageMode, PreviewMode, AddMode, HandleMode
from models.models import get_session
from telethon import Button
from utils.constants import RSS_ENABLED, UFB_ENABLED
from utils.i18n import t

AI_MODELS = load_ai_models()

# 规则配置字段定义
RULE_SETTINGS = {
    'enable_rule': {
        'display_name': t('settings.rule.enable_rule.name'),
        'values': {
            True: t('common.yes'),
            False: t('common.no')
        },
        'toggle_action': 'toggle_enable_rule',
        'toggle_func': lambda current: not current
    },
    'add_mode': {
        'display_name': t('settings.rule.add_mode.name'),
        'values': {
            AddMode.WHITELIST: t('common.whitelist'),
            AddMode.BLACKLIST: t('common.blacklist')
        },
        'toggle_action': 'toggle_add_mode',
        'toggle_func': lambda current: AddMode.BLACKLIST if current == AddMode.WHITELIST else AddMode.WHITELIST
    },
    'is_filter_user_info': {
        'display_name': t('settings.rule.is_filter_user_info.name'),
        'values': {
            True: t('common.yes'),
            False: t('common.no')
        },
        'toggle_action': 'toggle_filter_user_info',
        'toggle_func': lambda current: not current
    },
    'forward_mode': {
        'display_name': t('settings.rule.forward_mode.name'),
        'values': {
            ForwardMode.BLACKLIST: t('settings.rule.forward_mode.blacklist'),
            ForwardMode.WHITELIST: t('settings.rule.forward_mode.whitelist'),
            ForwardMode.BLACKLIST_THEN_WHITELIST: t('settings.rule.forward_mode.blacklist_then_whitelist'),
            ForwardMode.WHITELIST_THEN_BLACKLIST: t('settings.rule.forward_mode.whitelist_then_blacklist')
        },
        'toggle_action': 'toggle_forward_mode',
        'toggle_func': lambda current: {
            ForwardMode.BLACKLIST: ForwardMode.WHITELIST,
            ForwardMode.WHITELIST: ForwardMode.BLACKLIST_THEN_WHITELIST,
            ForwardMode.BLACKLIST_THEN_WHITELIST: ForwardMode.WHITELIST_THEN_BLACKLIST,
            ForwardMode.WHITELIST_THEN_BLACKLIST: ForwardMode.BLACKLIST
        }[current]
    },
    'use_bot': {
        'display_name': t('settings.rule.use_bot.name'),
        'values': {
            True: t('settings.rule.use_bot.bot'),
            False: t('settings.rule.use_bot.user')
        },
        'toggle_action': 'toggle_bot',
        'toggle_func': lambda current: not current
    },
    'is_replace': {
        'display_name': t('settings.rule.is_replace.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_replace',
        'toggle_func': lambda current: not current
    },
    'message_mode': {
        'display_name': t('settings.rule.message_mode.name'),
        'values': {
            MessageMode.MARKDOWN: 'Markdown',
            MessageMode.HTML: 'HTML'
        },
        'toggle_action': 'toggle_message_mode',
        'toggle_func': lambda current: MessageMode.HTML if current == MessageMode.MARKDOWN else MessageMode.MARKDOWN
    },
    'is_preview': {
        'display_name': t('settings.rule.is_preview.name'),
        'values': {
            PreviewMode.ON: t('common.on'),
            PreviewMode.OFF: t('common.off'),
            PreviewMode.FOLLOW: t('settings.rule.is_preview.follow')
        },
        'toggle_action': 'toggle_preview',
        'toggle_func': lambda current: {
            PreviewMode.ON: PreviewMode.OFF,
            PreviewMode.OFF: PreviewMode.FOLLOW,
            PreviewMode.FOLLOW: PreviewMode.ON
        }[current]
    },
    'is_original_link': {
        'display_name': t('settings.rule.is_original_link.name'),
        'values': {
            True: t('settings.rule.is_original_link.with'),
            False: t('settings.rule.is_original_link.without')
        },
        'toggle_action': 'toggle_original_link',
        'toggle_func': lambda current: not current
    },
    'is_delete_original': {
        'display_name': t('settings.rule.is_delete_original.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_delete_original',
        'toggle_func': lambda current: not current
    },
    'is_ufb': {
        'display_name': t('settings.rule.is_ufb.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_ufb',
        'toggle_func': lambda current: not current
    },
    'is_original_sender': {
        'display_name': t('settings.rule.is_original_sender.name'),
        'values': {
            True: t('common.show'),
            False: t('common.hide')
        },
        'toggle_action': 'toggle_original_sender',
        'toggle_func': lambda current: not current
    },
    'is_original_time': {
        'display_name': t('settings.rule.is_original_time.name'),
        'values': {
            True: t('common.show'),
            False: t('common.hide')
        },
        'toggle_action': 'toggle_original_time',
        'toggle_func': lambda current: not current
    },
    # 添加延迟过滤器设置
    'enable_delay': {
        'display_name': t('settings.rule.enable_delay.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_enable_delay',
        'toggle_func': lambda current: not current
    },
    'delay_seconds': {
        'values': {
            None: 5,
            '': 5
        },
        'toggle_action': 'set_delay_time',
        'toggle_func': None
    },
    'handle_mode': {
        'display_name': t('settings.rule.handle_mode.name'),
        'values': {
            HandleMode.FORWARD: t('settings.rule.handle_mode.forward'),
            HandleMode.EDIT: t('settings.rule.handle_mode.edit')
        },
        'toggle_action': 'toggle_handle_mode',
        'toggle_func': lambda current: HandleMode.EDIT if current == HandleMode.FORWARD else HandleMode.FORWARD
    },
    'enable_comment_button': {
        'display_name': t('settings.rule.enable_comment_button.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_enable_comment_button',
        'toggle_func': lambda current: not current
    },
    'only_rss': {
        'display_name': t('settings.rule.only_rss.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_only_rss',
        'toggle_func': lambda current: not current
    },
    'close_settings': {
        'display_name': t('common.close'),
        'toggle_action': 'close_settings',
        'toggle_func': None
    },
    'enable_sync': {
        'display_name': t('settings.rule.enable_sync.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_enable_sync',
        'toggle_func': lambda current: not current
    }
}


# 添加 AI 设置
AI_SETTINGS = {
    'is_ai': {
        'display_name': t('settings.ai.is_ai.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_ai',
        'toggle_func': lambda current: not current
    },
    'ai_model': {
        'display_name': t('settings.ai.ai_model.name'),
        'values': {
            None: t('settings.ai.ai_model.default'),
            '': t('settings.ai.ai_model.default'),
            **{model: model for model in AI_MODELS}
        },
        'toggle_action': 'change_model',
        'toggle_func': None
    },
    'ai_prompt': {
        'display_name': t('settings.ai.ai_prompt.name'),
        'toggle_action': 'set_ai_prompt',
        'toggle_func': None
    },
    'enable_ai_upload_image': {
        'display_name': t('settings.ai.enable_ai_upload_image.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_ai_upload_image',
        'toggle_func': lambda current: not current
    },
    'is_keyword_after_ai': {
        'display_name': t('settings.ai.is_keyword_after_ai.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_keyword_after_ai',
        'toggle_func': lambda current: not current
    },
    'is_summary': {
        'display_name': t('settings.ai.is_summary.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_summary',
        'toggle_func': lambda current: not current
    },
    'summary_time': {
        'display_name': t('settings.ai.summary_time.name'),
        'values': {
            None: '00:00',
            '': '00:00'
        },
        'toggle_action': 'set_summary_time',
        'toggle_func': None
    },
    'summary_prompt': {
        'display_name': t('settings.ai.summary_prompt.name'),
        'toggle_action': 'set_summary_prompt',
        'toggle_func': None
    },
    'is_top_summary': {
        'display_name': t('settings.ai.is_top_summary.name'),
        'values': {
            True: t('common.yes'),
            False: t('common.no')
        },
        'toggle_action': 'toggle_top_summary',
        'toggle_func': lambda current: not current
    },
    'summary_now': {
        'display_name': t('settings.ai.summary_now.name'),
        'toggle_action': 'summary_now',
        'toggle_func': None
    }

}

MEDIA_SETTINGS = {
    'enable_media_type_filter': {
        'display_name': t('settings.media.enable_media_type_filter.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_enable_media_type_filter',
        'toggle_func': lambda current: not current
    },
    'selected_media_types': {
        'display_name': t('settings.media.selected_media_types.name'),
        'toggle_action': 'set_media_types',
        'toggle_func': None
    },
    'enable_media_size_filter': {
        'display_name': t('settings.media.enable_media_size_filter.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_enable_media_size_filter',
        'toggle_func': lambda current: not current
    },
    'max_media_size': {
        'display_name': t('settings.media.max_media_size.name'),
        'values': {
            None: '5MB',
            '': '5MB'
        },
        'toggle_action': 'set_max_media_size',
        'toggle_func': None
    },
    'is_send_over_media_size_message': {
        'display_name': t('settings.media.is_send_over_media_size_message.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_send_over_media_size_message',
        'toggle_func': lambda current: not current
    },
    'enable_extension_filter': {
        'display_name': t('settings.media.enable_extension_filter.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_enable_media_extension_filter',
        'toggle_func': lambda current: not current
    },
    'extension_filter_mode': {
        'display_name': t('settings.media.extension_filter_mode.name'),
        'values': {
            AddMode.BLACKLIST: t('common.blacklist'),
            AddMode.WHITELIST: t('common.whitelist')
        },
        'toggle_action': 'toggle_media_extension_filter_mode',
        'toggle_func': lambda current: AddMode.WHITELIST if current == AddMode.BLACKLIST else AddMode.BLACKLIST
    },
    'media_extensions': {
        'display_name': t('settings.media.media_extensions.name'),
        'toggle_action': 'set_media_extensions',
        'toggle_func': None,
        'values': {}
    },
    'media_allow_text': {
        'display_name': t('settings.media.media_allow_text.name'),
        'values': {
            True: t('common.on'),
            False: t('common.off')
        },
        'toggle_action': 'toggle_media_allow_text',
        'toggle_func': lambda current: not current
    }
}


OTHER_SETTINGS = {
    'copy_rule': {
        'display_name': t('settings.other.copy_rule.name'),
        'toggle_action': 'copy_rule',
        'toggle_func': None
    },
    'copy_keyword': {
        'display_name': t('settings.other.copy_keyword.name'),
        'toggle_action': 'copy_keyword',
        'toggle_func': None
    },
    'copy_replace': {
        'display_name': t('settings.other.copy_replace.name'),
        'toggle_action': 'copy_replace',
        'toggle_func': None
    },
    'clear_keyword': {
        'display_name': t('settings.other.clear_keyword.name'),
        'toggle_action': 'clear_keyword',
        'toggle_func': None
    },
    'clear_replace': {
        'display_name': t('settings.other.clear_replace.name'),
        'toggle_action': 'clear_replace',
        'toggle_func': None
    },
    'delete_rule': {
        'display_name': t('settings.other.delete_rule.name'),
        'toggle_action': 'delete_rule',
        'toggle_func': None
    },
    'null': {
        'display_name': '-----------',
        'toggle_action': 'null',
        'toggle_func': None
    },
    'set_userinfo_template': {
        'display_name': t('settings.other.set_userinfo_template.name'),
        'toggle_action': 'set_userinfo_template',
        'toggle_func': None
    },
    'set_time_template': {
        'display_name': t('settings.other.set_time_template.name'),
        'toggle_action': 'set_time_template',
        'toggle_func': None
    },
    'set_original_link_template': {
        'display_name': t('settings.other.set_original_link_template.name'),
        'toggle_action': 'set_original_link_template',
        'toggle_func': None
    },
    'reverse_blacklist': {
        'display_name': t('settings.other.reverse_blacklist.name'),
        'toggle_action': 'toggle_reverse_blacklist',
        'toggle_func': None
    },
    'reverse_whitelist': {
        'display_name': t('settings.other.reverse_whitelist.name'),
        'toggle_action': 'toggle_reverse_whitelist',
        'toggle_func': None
    }
}

PUSH_SETTINGS = {
    'enable_push_channel': {
        'display_name': t('settings.push.enable_push_channel.name'),
        'toggle_action': 'toggle_enable_push',
        'toggle_func': None
    },
    'add_push_channel': {
        'display_name': t('settings.push.add_push_channel.name'),
        'toggle_action': 'add_push_channel',
        'toggle_func': None
    },
    'enable_only_push': {
        'display_name': t('settings.push.enable_only_push.name'),
        'toggle_action': 'toggle_enable_only_push',
        'toggle_func': None
    }
}

async def create_settings_text(rule):
    """创建设置信息文本"""
    text = t(
        "settings.rule.header",
        rule_id=rule.id,
        source=rule.source_chat.name,
        target=rule.target_chat.name
    )
    return text

async def create_buttons(rule):
    """创建规则设置按钮"""
    buttons = []

    # 获取当前聊天的当前选中规则
    session = get_session()
    try:
        target_chat = rule.target_chat
        current_add_id = target_chat.current_add_id
        source_chat = rule.source_chat

        # Der frühere Schalter "aktuelle Regel anwenden" betrifft nur die alten
        # Textbefehle (/switch) und ist in der Button-Bedienung nicht nötig.

        buttons.append([
            Button.inline(
                f"{t('settings.rule.enable_rule.name')}: {RULE_SETTINGS['enable_rule']['values'][rule.enable_rule]}",
                f"toggle_enable_rule:{rule.id}"
            )
        ])

        # 当前关键字添加模式
        buttons.append([
            Button.inline(
                f"{t('settings.rule.add_mode.name')}: {RULE_SETTINGS['add_mode']['values'][rule.add_mode]}",
                f"toggle_add_mode:{rule.id}"
            )
        ])

        # 是否过滤用户信息
        buttons.append([
            Button.inline(
                f"{t('settings.rule.is_filter_user_info.name')}: {RULE_SETTINGS['is_filter_user_info']['values'][rule.is_filter_user_info]}",
                f"toggle_filter_user_info:{rule.id}"
            )
        ])

        if RSS_ENABLED == 'false':
            # 处理模式
            buttons.append([
                Button.inline(
                    f"⚙️ {t('settings.rule.handle_mode.name')}: {RULE_SETTINGS['handle_mode']['values'][rule.handle_mode]}",
                    f"toggle_handle_mode:{rule.id}"
                )
            ])
        else:
            # 处理模式
            buttons.append([
                Button.inline(
                    f"⚙️ {t('settings.rule.handle_mode.name')}: {RULE_SETTINGS['handle_mode']['values'][rule.handle_mode]}",
                    f"toggle_handle_mode:{rule.id}"
                ),
                Button.inline(
                    f"⚠️ {t('settings.rule.only_rss.name')}: {RULE_SETTINGS['only_rss']['values'][rule.only_rss]}",
                    f"toggle_only_rss:{rule.id}"
                )
            ])


        buttons.append([
            Button.inline(
                f"📥 {t('settings.rule.forward_mode.label')}: {RULE_SETTINGS['forward_mode']['values'][rule.forward_mode]}",
                f"toggle_forward_mode:{rule.id}"
            ),
            Button.inline(
                f"🤖 {t('settings.rule.use_bot.name')}: {RULE_SETTINGS['use_bot']['values'][rule.use_bot]}",
                f"toggle_bot:{rule.id}"
            )
        ])


        if rule.use_bot:  # 只在使用机器人时显示这些设置
            buttons.append([
                Button.inline(
                    f"🔄 {t('settings.rule.is_replace.name')}: {RULE_SETTINGS['is_replace']['values'][rule.is_replace]}",
                    f"toggle_replace:{rule.id}"
                ),
                Button.inline(
                    f"📝 {t('settings.rule.message_mode.label')}: {RULE_SETTINGS['message_mode']['values'][rule.message_mode]}",
                    f"toggle_message_mode:{rule.id}"
                )
            ])

            buttons.append([
                Button.inline(
                    f"👁 {t('settings.rule.is_preview.name')}: {RULE_SETTINGS['is_preview']['values'][rule.is_preview]}",
                    f"toggle_preview:{rule.id}"
                ),
                Button.inline(
                    f"🔗 {t('settings.rule.is_original_link.name')}: {RULE_SETTINGS['is_original_link']['values'][rule.is_original_link]}",
                    f"toggle_original_link:{rule.id}"
                )
            ])

            buttons.append([
                Button.inline(
                    f"👤 {t('settings.rule.is_original_sender.name')}: {RULE_SETTINGS['is_original_sender']['values'][rule.is_original_sender]}",
                    f"toggle_original_sender:{rule.id}"
                ),
                Button.inline(
                    f"⏰ {t('settings.rule.is_original_time.name')}: {RULE_SETTINGS['is_original_time']['values'][rule.is_original_time]}",
                    f"toggle_original_time:{rule.id}"
                )
            ])

            buttons.append([
                Button.inline(
                    f"🗑 {t('settings.rule.is_delete_original.label')}: {RULE_SETTINGS['is_delete_original']['values'][rule.is_delete_original]}",
                    f"toggle_delete_original:{rule.id}"
                ),
                Button.inline(
                    f"💬 {t('settings.rule.enable_comment_button.label')}: {RULE_SETTINGS['enable_comment_button']['values'][rule.enable_comment_button]}",
                    f"toggle_enable_comment_button:{rule.id}"
                )

            ])

            # 添加延迟过滤器按钮
            buttons.append([
                Button.inline(
                    f"⏱️ {t('settings.rule.enable_delay.name')}: {RULE_SETTINGS['enable_delay']['values'][rule.enable_delay]}",
                    f"toggle_enable_delay:{rule.id}"
                ),
                Button.inline(
                    f"⌛ {t('settings.rule.delay_seconds.button', seconds=rule.delay_seconds or 5)}",
                    f"set_delay_time:{rule.id}"
                )
            ])



            # 添加同步规则相关按钮
            buttons.append([
                Button.inline(
                    f"🔄 {t('settings.rule.enable_sync.label')}: {RULE_SETTINGS['enable_sync']['values'][rule.enable_sync]}",
                    f"toggle_enable_sync:{rule.id}"
                ),
                Button.inline(
                    f"📡 {t('settings.rule.sync_settings')}",
                    f"set_sync_rule:{rule.id}"
                )
            ])

            if UFB_ENABLED == 'true':
                buttons.append([
                    Button.inline(
                        f"☁️ {t('settings.rule.is_ufb.name')}: {RULE_SETTINGS['is_ufb']['values'][rule.is_ufb]}",
                        f"toggle_ufb:{rule.id}"
                    )
                ])




            buttons.append([
                Button.inline(
                    f"🤖 {t('settings.menu.ai')}",
                    f"ai_settings:{rule.id}"
                ),
                Button.inline(
                    f"🎬 {t('settings.menu.media')}",
                    f"media_settings:{rule.id}"
                ),
                Button.inline(
                    f"➕ {t('settings.menu.other')}",
                    f"other_settings:{rule.id}"
                )
            ])


            buttons.append([
                Button.inline(
                    f"🔔 {t('settings.menu.push')}",
                    f"push_settings:{rule.id}"
                )
            ])

        # Zurueck fuehrt immer zur Detailkarte der Weiterleitung – auch wenn die
        # Weiterleitung ueber das eigene Konto statt ueber den Bot laeuft.
        buttons.append([
            Button.inline(
                t('common.btn.back'),
                f"rule_card:{rule.id}"
            ),
            Button.inline(
                t('common.btn.close'),
                "close_settings"
            )
        ])

    finally:
        session.close()

    return buttons


