from sqlalchemy.exc import IntegrityError
from telethon import Button
from models.models import MediaTypes, MediaExtensions
from enums.enums import AddMode, ForwardMode
from models.models import get_session, Keyword, ReplaceRule, User, RuleSync
from utils.common import *
from utils.media import *
from handlers.list_handlers import *
from utils.constants import TEMP_DIR
import traceback
from sqlalchemy import inspect
from version import VERSION, UPDATE_INFO
from utils.i18n import t
import shlex
import logging
import os
import aiohttp
from utils.constants import RSS_HOST, RSS_PORT
import models.models as models
from utils.auto_delete import respond_and_delete,reply_and_delete,async_delete_user_message
from utils.common import get_bot_client
from handlers.button.settings_manager import create_settings_text, create_buttons
from handlers.button.menu import build_main_menu
from handlers.button.account_login import is_connected
from models.db_operations import create_forward_rule

logger = logging.getLogger(__name__)

async def handle_bind_command(event, client, parts):
    """处理 bind 命令"""
    # 使用shlex解析命令
    message_text = event.message.text
    try:
        # 去掉命令前缀，获取原始参数字符串
        if ' ' in message_text:
            command, args_str = message_text.split(' ', 1)
            args = shlex.split(args_str)
            if len(args) >= 1:
                source_target = args[0]
                # 检查是否有第二个参数（目标聊天）
                target_chat_input = args[1] if len(args) >= 2 else None
            else:
                raise ValueError("参数不足")
        else:
            raise ValueError("参数不足")
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.bind.usage'), parse_mode='html', link_preview=False)
        return

    # 检查是否是链接
    is_source_link = source_target.startswith(('https://', 't.me/'))

    # 默认使用当前聊天作为目标聊天
    current_chat = await event.get_chat()
    
    try:
        # 获取 main 模块中的用户客户端
        main = await get_main_module()
        user_client = main.user_client

        # 使用用户客户端获取源聊天的实体信息
        try:
            if is_source_link:
                # 如果是链接，直接获取实体
                source_chat_entity = await user_client.get_entity(source_target)
            else:
                # 如果是名称，获取对话列表并查找匹配的第一个
                async for dialog in user_client.iter_dialogs():
                    if dialog.name and source_target.lower() in dialog.name.lower():
                        source_chat_entity = dialog.entity
                        break
                else:
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,t('cmd.bind.source_not_found'))
                    return
            
            # 获取目标聊天实体
            if target_chat_input:
                is_target_link = target_chat_input.startswith(('https://', 't.me/'))
                if is_target_link:
                    # 如果是链接，直接获取实体
                    target_chat_entity = await user_client.get_entity(target_chat_input)
                else:
                    # 如果是名称，获取对话列表并查找匹配的第一个
                    async for dialog in user_client.iter_dialogs():
                        if dialog.name and target_chat_input.lower() in dialog.name.lower():
                            target_chat_entity = dialog.entity
                            break
                    else:
                        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                        await reply_and_delete(event,t('cmd.bind.target_not_found'))
                        return
            else:
                # 使用当前聊天作为目标
                target_chat_entity = current_chat

            # # 检查是否在绑定自己
            # if str(source_chat_entity.id) == str(target_chat_entity.id):
            #     await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            #     await reply_and_delete(event,'⚠️ 不能将频道/群组绑定到自己')
            #     return

        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.bind.get_chat_failed'))
            return
        except Exception as e:
            logger.error(f'获取聊天信息时出错: {str(e)}')
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.bind.get_chat_error'))
            return

        # 保存到数据库（与设置向导共用同一逻辑）
        session = get_session()
        try:
            rule, created = create_forward_rule(session, source_chat_entity, target_chat_entity)

            source_chat_db = rule.source_chat if rule else None
            target_chat_db = rule.target_chat if rule else None

            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)

            if not created:
                await reply_and_delete(event,
                    t('cmd.bind.exists',
                      source_name=source_chat_db.name if source_chat_db else '',
                      target_name=target_chat_db.name if target_chat_db else '')
                )
                return

            await reply_and_delete(event,
                t('cmd.bind.success', source_name=source_chat_db.name, source_id=source_chat_db.telegram_chat_id, target_name=target_chat_db.name, target_id=target_chat_db.telegram_chat_id),
                buttons=[Button.inline(t('cmd.bind.btn.open_settings'), f"rule_settings:{rule.id}")]
            )
        finally:
            session.close()

    except Exception as e:
        logger.error(f'设置转发规则时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.bind.set_rule_error'))
        return

async def handle_settings_command(event, command, parts):
    """处理 settings 命令"""
    # 添加日志
    logger.info(f'处理 settings 命令 - parts: {parts}')
    
    # 获取参数
    args = parts[1:] if len(parts) > 1 else []
    
    # 检查是否提供了规则ID
    if len(args) >= 1 and args[0].isdigit():
        rule_id = int(args[0])
        
        # 直接打开指定规则的设置界面
        session = get_session()
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                await reply_and_delete(event, t('cmd.settings.rule_not_found', rule_id=rule_id))
                return
                
            # 与callback_rule_settings函数相同的处理方式
            settings_message = await event.respond(
                await create_settings_text(rule),
                buttons=await create_buttons(rule)
            )
            
        except Exception as e:
            logger.error(f'打开规则设置时出错: {str(e)}')
            await reply_and_delete(event, t('cmd.settings.open_error'))
        finally:
            session.close()
        return
    
    current_chat = await event.get_chat()
    current_chat_id = str(current_chat.id)
    # 添加日志
    logger.info(f'正在查找聊天ID: {current_chat_id} 的转发规则')

    session = get_session()
    try:
        # 添加日志，显示数据库中的所有聊天
        all_chats = session.query(Chat).all()
        logger.info('数据库中的所有聊天:')
        for chat in all_chats:
            logger.info(f'ID: {chat.id}, telegram_chat_id: {chat.telegram_chat_id}, name: {chat.name}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_id
        ).first()

        if not current_chat_db:
            logger.info(f'在数据库中找不到聊天ID: {current_chat_id}')
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('callback.alert.no_rules_in_chat'))
            return

        # 添加日志
        logger.info(f'找到聊天: {current_chat_db.name} (ID: {current_chat_db.id})')

        # 查找以当前聊天为目标的规则
        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id  # 改为 target_chat_id
        ).all()

        # 添加日志
        logger.info(f'找到 {len(rules)} 条转发规则')
        for rule in rules:
            logger.info(f'规则ID: {rule.id}, 源聊天: {rule.source_chat.name}, 目标聊天: {rule.target_chat.name}')

        if not rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('callback.alert.no_rules_in_chat'))
            return

        # 创建规则选择按钮
        buttons = []
        for rule in rules:
            source_chat = rule.source_chat  # 显示源聊天
            button_text = f'{source_chat.name}'
            callback_data = f"rule_settings:{rule.id}"
            buttons.append([Button.inline(button_text, callback_data)])
        
        # 删除用户消息
        client = await get_bot_client()
        await async_delete_user_message(client, event.message.chat_id, event.message.id, 0)

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('callback.select_rule_to_manage'), buttons=buttons)

    except Exception as e:
        logger.info(f'获取转发规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.settings.get_rules_error'))
    finally:
        session.close()

async def handle_switch_command(event):
    """处理 switch 命令"""
    # 显示可切换的规则列表
    current_chat = await event.get_chat()
    current_chat_id = str(current_chat.id)

    session = get_session()
    try:
        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_id
        ).first()

        if not current_chat_db:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('callback.alert.no_rules_in_chat'))
            return

        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id
        ).all()

        if not rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('callback.alert.no_rules_in_chat'))
            return

        # 创建规则选择按钮
        buttons = []
        for rule in rules:
            source_chat = rule.source_chat
            # 标记当前选中的规则
            current = current_chat_db.current_add_id == source_chat.telegram_chat_id
            button_text = f'{"✓ " if current else ""}{t("callback.from", name=source_chat.name)}'
            callback_data = f"switch:{source_chat.telegram_chat_id}"
            buttons.append([Button.inline(button_text, callback_data)])
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('callback.select_rule_to_manage'), buttons=buttons)
    finally:
        session.close()

async def handle_add_command(event, command, parts):
    """处理 add 和 add_regex 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.usage.keywords', command=command), parse_mode='html')
        return

    # 分离命令和参数部分
    _, args_text = message_text.split(None, 1)
    logger.info(f"分离出的参数部分: {args_text}")

    keywords = []
    if command in ['add', 'a']:
        try:
            # 使用 shlex 来正确处理带引号的参数
            logger.info("开始使用 shlex 解析参数")
            keywords = shlex.split(args_text)
            logger.info(f"shlex 解析结果: {keywords}")
        except ValueError as e:
            logger.error(f"shlex 解析出错: {str(e)}")
            # 处理未闭合的引号等错误
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.quote_mismatch'))
            return
    else:
        # add_regex 命令保持原样
        keywords = parts[1:]
        logger.info(f"add_regex 命令，使用原始参数: {keywords}")

    if not keywords:
        logger.warning("没有提供任何关键字")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.need_keyword'))
        return

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info
        logger.info(f"当前规则ID: {rule.id}, 源聊天: {source_chat.name}")

        # 使用 db_operations 添加关键字
        db_ops = await get_db_ops()
        logger.info(f"准备添加关键字: {keywords}, is_regex={command == 'add_regex'}, is_blacklist={rule.add_mode == AddMode.BLACKLIST}")
        success_count, duplicate_count = await db_ops.add_keywords(
            session,
            rule.id,
            keywords,
            is_regex=(command == 'add_regex'),
            is_blacklist=(rule.add_mode == AddMode.BLACKLIST)
        )
        logger.info(f"添加结果: 成功={success_count}, 重复={duplicate_count}")

        session.commit()

        # 构建回复消息
        keyword_type = t('cmd.kwtype.regex_short') if command == "add_regex" else t('cmd.kwtype.keyword')
        keywords_text = '\n'.join(f'- {k}' for k in keywords)
        result_text = t('cmd.add.added', count=success_count, type=keyword_type)
        if duplicate_count > 0:
            result_text += t('cmd.add.skipped', count=duplicate_count)
        result_text += t('cmd.add.kw_list', keywords=keywords_text)
        result_text += t('cmd.current_rule_from', name=source_chat.name) + '\n'
        mode_text = t('common.whitelist') if rule.add_mode == AddMode.WHITELIST else t('common.blacklist')
        result_text += t('cmd.add.mode', mode=mode_text)

        logger.info(f"发送回复消息: {result_text}")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'添加关键字时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.add_keyword_error'))
    finally:
        session.close()

async def handle_replace_command(event, parts):
    """处理 replace 命令"""
    message_text = event.message.text
    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.replace.usage'), parse_mode='html')
        return

    # 直接分割参数，保持正则表达式的原始形式
    try:
        # 去掉命令前缀，获取原始参数字符串
        _, args_text = message_text.split(None, 1)
        
        # 按第一个空格分割，保持后续内容不变
        parts = args_text.split(None, 1)
        if not parts:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.replace.need_pattern'))
            return
            
        pattern = parts[0]
        content = parts[1] if len(parts) > 1 else ''
        
        logger.info(f"解析替换命令参数: pattern='{pattern}', content='{content}'")
        
    except ValueError as e:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.replace.parse_error', error=str(e)))
        return
        
    if not pattern:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.replace.need_pattern'))
        return

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 使用 add_replace_rules 添加替换规则
        db_ops = await get_db_ops()
        # 分别传递 patterns 和 contents 参数
        success_count, duplicate_count = await db_ops.add_replace_rules(
            session,
            rule.id,
            [pattern],  # patterns 参数
            [content]   # contents 参数
        )

        # 确保启用替换模式
        if success_count > 0 and not rule.is_replace:
            rule.is_replace = True

        session.commit()

        # 检查是否是全文替换
        rule_type = t('cmd.replace.fulltext') if pattern == ".*" else t('cmd.replace.regex')
        action_type = t('cmd.action.delete') if not content else t('cmd.action.replace')

        # 构建回复消息
        result_text = t('cmd.replace.added_rule', rule_type=rule_type)
        if success_count > 0:
            result_text += t('cmd.replace.match', pattern=pattern)
            result_text += t('cmd.replace.action', action=action_type)
            result_text += f'{t("cmd.replace.replace_with_prefix") + content if content else t("cmd.replace.delete_matched")}\n'
        if duplicate_count > 0:
            result_text += t('cmd.replace.skipped_rules', count=duplicate_count)
        result_text += t('cmd.current_rule_from', name=source_chat.name)

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'添加替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.add_replace_error'))
    finally:
        session.close()

async def handle_list_keyword_command(event):
    """处理 list_keyword 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 使用 get_keywords 获取所有关键字
        db_ops = await get_db_ops()
        rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
        keywords = await db_ops.get_keywords(session, rule.id, rule_mode)

        await show_list(
            event,
            'keyword',
            keywords,
            lambda i, kw: f'{i}. {kw.keyword}{t("callback.regex_suffix") if kw.is_regex else ""}',
            t('cmd.list.keyword_header', mode=(t('common.blacklist') if rule.add_mode == AddMode.BLACKLIST else t('common.whitelist')), name=source_chat.name)
        )

    finally:
        session.close()

async def handle_list_replace_command(event):
    """处理 list_replace 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 使用 get_replace_rules 获取所有替换规则
        db_ops = await get_db_ops()
        replace_rules = await db_ops.get_replace_rules(session, rule.id)

        await show_list(
            event,
            'replace',
            replace_rules,
            lambda i, rr: f'{i}. {t("callback.match_label")}{rr.pattern} -> {t("callback.delete_label") if not rr.content else t("callback.replace_with", content=rr.content)}',
            t('callback.replace_list_header', name=source_chat.name)
        )

    finally:
        session.close()

async def handle_remove_command(event, command, parts):
    """处理 remove_keyword 和 remove_replace 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    # 如果是替换规则，保持原来的 ID 删除方式
    if command == 'remove_replace':
        if len(parts) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.remove.usage_id', command=command), parse_mode='html')
            return

        try:
            ids_to_remove = [int(x) for x in parts[1:]]
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.id_number'))
            return
    elif command in ['remove_keyword_by_id', 'rkbi']:  # 添加按ID删除关键字的处理
        if len(parts) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.remove.usage_id', command=command), parse_mode='html')
            return

        try:
            ids_to_remove = [int(x) for x in parts[1:]]
            logger.info(f"准备按ID删除关键字: {ids_to_remove}")
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.id_number'))
            return
    else:  # remove_keyword
        if len(message_text.split(None, 1)) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.usage.keywords', command=command), parse_mode='html')
            return

        # 分离命令和参数部分
        _, args_text = message_text.split(None, 1)
        logger.info(f"分离出的参数部分: {args_text}")

        try:
            # 使用 shlex 来正确处理带引号的参数
            logger.info("开始使用 shlex 解析参数")
            keywords_to_remove = shlex.split(args_text)
            logger.info(f"shlex 解析结果: {keywords_to_remove}")
        except ValueError as e:
            logger.error(f"shlex 解析出错: {str(e)}")
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.quote_mismatch'))
            return

        if not keywords_to_remove:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.need_keyword'))
            return

    # 在 try 块外定义 item_type
    item_type = t('cmd.kwtype.keyword') if command in ['remove_keyword', 'remove_keyword_by_id', 'rkbi'] else t('cmd.item.replace_rule')

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info
        rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
        mode_name = t('common.blacklist') if rule.add_mode == AddMode.BLACKLIST else t('common.whitelist')

        db_ops = await get_db_ops()
        if command == 'remove_keyword':
            # 获取当前模式下的关键字
            items = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.remove.no_kw_in_mode', mode=mode_name))
                return

            # 修改：删除匹配的关键字
            removed_count = 0
            removed_indices = [] # 存储要删除的关键字索引
            
            for keyword in keywords_to_remove:
                logger.info(f"尝试删除关键字: {keyword}")
                for i, item in enumerate(items):
                    if item.keyword == keyword:
                        logger.info(f"找到匹配的关键字: {item.keyword}")
                        removed_indices.append(i + 1) # 转为1-based索引
                        removed_count += 1
                        break
            
            if removed_indices:
                # 使用db_ops删除关键字（支持同步功能）
                await db_ops.delete_keywords(session, rule.id, removed_indices)
                session.commit()
                logger.info(f"成功删除 {removed_count} 个关键字")
            
            # 重新获取更新后的列表
            remaining_items = await db_ops.get_keywords(session, rule.id, rule_mode)

            # 显示删除结果
            if removed_count > 0:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.remove.deleted_from_mode', mode=mode_name, count=removed_count))
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.remove.not_found_in_mode', mode=mode_name))

        elif command in ['remove_keyword_by_id', 'rkbi']:
            # 获取当前模式下的关键字
            items = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.remove.no_kw_in_mode', mode=mode_name))
                return

            # 检查ID是否有效
            max_id = len(items)
            invalid_ids = [id for id in ids_to_remove if id < 1 or id > max_id]
            if invalid_ids:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.err.invalid_id', ids=", ".join(map(str, invalid_ids))))
                return

            # 修改：记录要删除的关键字
            removed_count = 0
            removed_keywords = []
            valid_ids = [id for id in ids_to_remove if 1 <= id <= max_id]
            
            for id in valid_ids:
                removed_keywords.append(items[id - 1].keyword)
                
            # 使用db_ops删除关键字（支持同步功能）
            removed_count, _ = await db_ops.delete_keywords(session, rule.id, valid_ids)
            session.commit()
            logger.info(f"成功删除 {removed_count} 个关键字")

            # 构建回复消息
            if removed_count > 0:
                keywords_text = '\n'.join(f'- {k}' for k in removed_keywords)
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,
                    t('cmd.remove.deleted_from_mode_list', mode=mode_name, count=removed_count, keywords=keywords_text)
                )
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.remove.not_found_in_mode', mode=mode_name))

        else:  # remove_replace
            # 处理替换规则的删除（保持原有逻辑）
            items = await db_ops.get_replace_rules(session, rule.id)
            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.remove.no_item', item=item_type))
                return

            max_id = len(items)
            invalid_ids = [id for id in ids_to_remove if id < 1 or id > max_id]
            if invalid_ids:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.err.invalid_id', ids=", ".join(map(str, invalid_ids))))
                return

            await db_ops.delete_replace_rules(session, rule.id, ids_to_remove)
            session.commit()

            remaining_items = await db_ops.get_replace_rules(session, rule.id)
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.remove.deleted_replace', count=len(ids_to_remove)))

    except Exception as e:
        session.rollback()
        logger.error(f'删除{item_type}时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.remove_error', item=item_type))
    finally:
        session.close()

async def handle_clear_all_command(event):
    """处理 clear_all 命令"""
    session = get_session()
    try:
        # 删除所有替换规则
        replace_count = session.query(ReplaceRule).delete(synchronize_session=False)

        # 删除所有关键字
        keyword_count = session.query(Keyword).delete(synchronize_session=False)

        # 删除所有转发规则
        rule_count = session.query(ForwardRule).delete(synchronize_session=False)

        # 删除所有聊天
        chat_count = session.query(Chat).delete(synchronize_session=False)

        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.clear_all.result', chats=chat_count, rules=rule_count, keywords=keyword_count, replaces=replace_count)
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清空数据时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.clear_all_error'))
    finally:
        session.close()


async def handle_changelog_command(event):
    """处理 changelog 命令"""
    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,UPDATE_INFO, parse_mode='html')


async def handle_start_command(event):
    """处理 start 命令"""

    connected = await is_connected()
    welcome_text = t("cmd.start.text", version=VERSION) if connected else t('login.needed.text')

    # Testphase beim ersten Kontakt anlegen (nur für Kunden, nicht Admin)
    try:
        from handlers.subscription import ensure_trial
        ensure_trial(event.sender_id)
    except Exception as e:
        logger.error(f'Testphase konnte nicht angelegt werden: {e}')

    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    # Startnachricht bleibt stehen (-1): sie trägt das Hauptmenü.
    await reply_and_delete(
        event,
        welcome_text,
        delete_after_seconds=-1,
        parse_mode='html',
        link_preview=False,
        buttons=build_main_menu(connected, event.sender_id),
    )

async def handle_help_command(event, command):
    """处理帮助命令"""
    help_text = t("cmd.help.text", version=VERSION)

    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)

    await reply_and_delete(
        event,
        help_text,
        delete_after_seconds=-1,
        parse_mode='html',
        link_preview=False,
        buttons=build_main_menu(user_id=event.sender_id),
    )

async def handle_export_keyword_command(event, command):
    """处理 export_keyword 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取所有关键字
        normal_keywords = []
        regex_keywords = []

        # 直接从规则对象获取关键字
        for keyword in rule.keywords:
            if keyword.is_regex:
                regex_keywords.append(f"{keyword.keyword} {1 if keyword.is_blacklist else 0}")
            else:
                normal_keywords.append(f"{keyword.keyword} {1 if keyword.is_blacklist else 0}")

        # 创建临时文件
        normal_file = os.path.join(TEMP_DIR, 'keywords.txt')
        regex_file = os.path.join(TEMP_DIR, 'regex_keywords.txt')

        # 写入普通关键字，确保每行一个
        with open(normal_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(normal_keywords))

        # 写入正则关键字，确保每行一个
        with open(regex_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(regex_keywords))

        # 如果两个文件都是空的
        if not normal_keywords and not regex_keywords:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, t('cmd.no_keywords'))
            return

        try:
            # 先发送文件
            files = []
            if normal_keywords:
                files.append(normal_file)
            if regex_keywords:
                files.append(regex_file)

            await event.client.send_file(
                event.chat_id,
                files
            )

            # 然后单独发送说明文字
            await respond_and_delete(event,(t('cmd.export.rule', name=source_chat.name)))

        finally:
            # 删除临时文件
            if os.path.exists(normal_file):
                os.remove(normal_file)
            if os.path.exists(regex_file):
                os.remove(regex_file)

    except Exception as e:
        logger.error(f'导出关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.export_kw_error'))
    finally:
        session.close()

async def handle_import_command(event, command):
    """处理导入命令"""
    try:
        # 检查是否有附件
        if not event.message.file:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.import.send_file', command=command))
            return

        # 获取当前规则
        session = get_session()
        try:
            rule_info = await get_current_rule(session, event)
            if not rule_info:
                return

            rule, source_chat = rule_info

            # 下载文件
            file_path = await event.message.download_media(TEMP_DIR)

            try:
                # 读取文件内容
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]

                # 根据命令类型处理
                if command == 'import_replace':
                    success_count = 0
                    logger.info(f'开始导入替换规则,共 {len(lines)} 行')
                    for i, line in enumerate(lines, 1):
                        try:
                            # 按第一个制表符分割
                            parts = line.split('\t', 1)
                            pattern = parts[0].strip()
                            content = parts[1].strip() if len(parts) > 1 else ''

                            logger.info(f'处理第 {i} 行: pattern="{pattern}", content="{content}"')

                            # 创建替换规则
                            replace_rule = ReplaceRule(
                                rule_id=rule.id,
                                pattern=pattern,
                                content=content
                            )
                            session.add(replace_rule)
                            success_count += 1
                            logger.info(f'成功添加替换规则: pattern="{pattern}", content="{content}"')

                            # 确保启用替换模式
                            if not rule.is_replace:
                                rule.is_replace = True
                                logger.info('已启用替换模式')

                        except Exception as e:
                            logger.error(f'处理第 {i} 行替换规则时出错: {str(e)}\n{traceback.format_exc()}')
                            continue

                    session.commit()
                    logger.info(f'导入完成,成功导入 {success_count} 条替换规则')
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,t('cmd.import.replace_success', count=success_count, name=source_chat.name))


                else:
                    # 处理关键字导入
                    success_count = 0
                    duplicate_count = 0
                    is_regex = (command == 'import_regex_keyword')
                    for i, line in enumerate(lines, 1):
                        try:
                            # 按空格分割，提取关键字和标志
                            parts = line.split()
                            if len(parts) < 2:
                                raise ValueError("行格式无效，至少需要关键字和标志")
                            flag_str = parts[-1]  # 最后一个部分为标志
                            if flag_str not in ('0', '1'):
                                raise ValueError("标志值必须为 0 或 1")
                            is_blacklist = (flag_str == '1')  # 转换为布尔值
                            keyword = ' '.join(parts[:-1])  # 前面的部分组合为关键字
                            if not keyword:
                                raise ValueError("关键字为空")
                            # 检查是否已存在相同的关键字
                            existing = session.query(Keyword).filter_by(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=is_regex
                            ).first()

                            if existing:
                                duplicate_count += 1
                                continue

                            # 创建新的 Keyword 对象
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=is_regex,
                                is_blacklist=is_blacklist
                            )
                            session.add(new_keyword)
                            success_count += 1

                        except Exception as e:
                            logger.error(f'处理第 {i} 行时出错: {line}\n{str(e)}')
                            continue

                    session.commit()
                    keyword_type = t('cmd.kwtype.regex') if is_regex else t('cmd.kwtype.keyword')
                    result_text = t('cmd.import.kw_success', count=success_count, type=keyword_type)
                    if duplicate_count > 0:
                        result_text += t('cmd.add.skipped', count=duplicate_count)
                    result_text += t('cmd.import.rule_line', name=source_chat.name)
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,result_text)
            finally:
                # 删除临时文件
                if os.path.exists(file_path):
                    os.remove(file_path)

        finally:
            session.close()

    except Exception as e:
        logger.error(f'导入过程出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.import_error'))

async def handle_ufb_item_change_command(event, command):
    """处理 ufb_item_change 命令"""

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 创建4个按钮
        buttons = [
            [
                Button.inline(t('cmd.ufb.main'), "ufb_item:main"),
                Button.inline(t('cmd.ufb.content'), "ufb_item:content")
            ],
            [
                Button.inline(t('cmd.ufb.main_username'), "ufb_item:main_username"),
                Button.inline(t('cmd.ufb.content_username'), "ufb_item:content_username")
            ]
        ]

        # 发送带按钮的消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event, t('cmd.ufb.select_type'), buttons=buttons)

    except Exception as e:
        session.rollback()
        logger.error(f'切换UFB配置类型时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.ufb_switch_error'))
    finally:
        session.close()

async def handle_ufb_bind_command(event, command):
    """处理 ufb_bind 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 从消息中获取域名和类型
        parts = event.message.text.split()
        if len(parts) < 2 or len(parts) > 3:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.ufb.bind_usage'), parse_mode='html')
            return

        domain = parts[1].strip().lower()
        item = 'main'  # 默认值

        if len(parts) == 3:
            item = parts[2].strip().lower()
            if item not in ['main', 'content', 'main_username', 'content_username']:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.ufb.invalid_type'))
                return

        # 更新规则的 ufb_domain 和 ufb_item
        rule.ufb_domain = domain
        rule.ufb_item = item
        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.ufb.bound', domain=domain, item=item, name=source_chat.name))

    except Exception as e:
        session.rollback()
        logger.error(f'绑定 UFB 域名时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.ufb_bind_error'))
    finally:
        session.close()

async def handle_ufb_unbind_command(event, command):
    """处理 ufb_unbind 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 清除规则的 ufb_domain
        old_domain = rule.ufb_domain
        rule.ufb_domain = None
        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.ufb.unbound', domain=old_domain or t('cmd.ufb.none'), name=source_chat.name))

    except Exception as e:
        session.rollback()
        logger.error(f'解绑 UFB 域名时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.ufb_unbind_error'))
    finally:
        session.close()

async def handle_clear_all_keywords_command(event, command):
    """处理清除所有关键字命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取当前规则的关键字数量
        keyword_count = len(rule.keywords)

        if keyword_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, t('cmd.no_keywords'))
            return

        # 删除所有关键字
        for keyword in rule.keywords:
            session.delete(keyword)

        session.commit()

        # 发送成功消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.clear.keywords', rule_id=rule.id, name=source_chat.name, count=keyword_count),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清除关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.clear_kw_error'))
    finally:
        session.close()

async def handle_clear_all_keywords_regex_command(event, command):
    """处理清除所有正则关键字命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取当前规则的正则关键字数量
        regex_keywords = [kw for kw in rule.keywords if kw.is_regex]
        keyword_count = len(regex_keywords)

        if keyword_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, t('cmd.no_regex_keywords'))
            return

        # 删除所有正则关键字
        for keyword in regex_keywords:
            session.delete(keyword)

        session.commit()

        # 发送成功消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.clear.regex', rule_id=rule.id, name=source_chat.name, count=keyword_count),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清除正则关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.clear_regex_error'))
    finally:
        session.close()

async def handle_clear_all_replace_command(event, command):
    """处理清除所有替换规则命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取当前规则的替换规则数量
        replace_count = len(rule.replace_rules)

        if replace_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, t('cmd.no_replace_rules'))
            return

        # 删除所有替换规则
        for replace_rule in rule.replace_rules:
            session.delete(replace_rule)

        # 如果没有替换规则了，关闭替换模式
        rule.is_replace = False

        session.commit()

        # 发送成功消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.clear.replace', rule_id=rule.id, name=source_chat.name, count=replace_count),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清除替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.clear_replace_error'))
    finally:
        session.close()

async def handle_copy_keywords_command(event, command):
    """处理复制关键字命令"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.copy_kw.usage'), parse_mode='html')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.rule_id_number'))
        return

    session = get_session()
    try:
        # 获取当前规则
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.rule_id_not_found', rule_id=source_rule_id))
            return

        # 复制关键字
        success_count = 0
        skip_count = 0

        for keyword in source_rule.keywords:
            if not keyword.is_regex:  # 只复制普通关键字
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and not k.is_regex
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    success_count += 1
                else:
                    skip_count += 1

        session.commit()

        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.copy_kw.result', source=source_rule_id, target=target_rule.id, ok=success_count, skip=skip_count),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.copy_kw_error'))
    finally:
        session.close()

async def handle_copy_keywords_regex_command(event, command):
    """处理复制正则关键字命令"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.copy_regex.usage'), parse_mode='html')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.rule_id_number'))
        return

    session = get_session()
    try:
        # 获取当前规则
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.rule_id_not_found', rule_id=source_rule_id))
            return

        # 复制正则关键字
        success_count = 0
        skip_count = 0

        for keyword in source_rule.keywords:
            if keyword.is_regex:  # 只复制正则关键字
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and k.is_regex
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    success_count += 1
                else:
                    skip_count += 1

        session.commit()

        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.copy_regex.result', source=source_rule_id, target=target_rule.id, ok=success_count, skip=skip_count),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制正则关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.copy_regex_error'))
    finally:
        session.close()

async def handle_copy_replace_command(event, command):
    """处理复制替换规则命令"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.copy_replace.usage'), parse_mode='html')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.rule_id_number'))
        return

    session = get_session()
    try:
        # 获取当前规则
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.rule_id_not_found', rule_id=source_rule_id))
            return

        # 复制替换规则
        success_count = 0
        skip_count = 0

        for replace_rule in source_rule.replace_rules:
            # 检查是否已存在
            exists = any(r.pattern == replace_rule.pattern
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                success_count += 1
            else:
                skip_count += 1

        session.commit()

        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('cmd.copy_replace.result', source=source_rule_id, target=target_rule.id, ok=success_count, skip=skip_count),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.copy_replace_error'))
    finally:
        session.close()

async def handle_copy_rule_command(event, command):
    """处理复制规则命令 - 复制一个规则的所有设置到当前规则或指定规则"""
    parts = event.message.text.split()
    
    # 检查参数数量
    if len(parts) not in [2, 3]:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.copy_rule.usage'), parse_mode='html')
        return

    try:
        source_rule_id = int(parts[1])
        
        # 确定目标规则ID
        if len(parts) == 3:
            # 如果提供了两个参数，使用第二个参数作为目标规则ID
            target_rule_id = int(parts[2])
            use_current_rule = False
        else:
            # 如果只提供了一个参数，使用当前规则作为目标
            target_rule_id = None
            use_current_rule = True
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.rule_id_number'))
        return

    session = get_session()
    try:
        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.source_rule_not_found', rule_id=source_rule_id))
            return

        # 获取目标规则
        if use_current_rule:
            # 获取当前规则
            rule_info = await get_current_rule(session, event)
            if not rule_info:
                return
            target_rule, source_chat = rule_info
        else:
            # 使用指定的目标规则ID
            target_rule = session.query(ForwardRule).get(target_rule_id)
            if not target_rule:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.err.target_rule_not_found', rule_id=target_rule_id))
                return

        if source_rule.id == target_rule.id:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('other.alert.cannot_copy_self'))
            return

        # 记录复制的各个部分成功数量
        keywords_normal_success = 0
        keywords_normal_skip = 0
        keywords_regex_success = 0
        keywords_regex_skip = 0
        replace_rules_success = 0
        replace_rules_skip = 0
        media_extensions_success = 0
        media_extensions_skip = 0


        # 复制普通关键字
        for keyword in source_rule.keywords:
            if not keyword.is_regex:
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and not k.is_regex and k.is_blacklist == keyword.is_blacklist
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_normal_success += 1
                else:
                    keywords_normal_skip += 1

        # 复制正则关键字
        for keyword in source_rule.keywords:
            if keyword.is_regex:
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and k.is_regex and k.is_blacklist == keyword.is_blacklist
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_regex_success += 1
                else:
                    keywords_regex_skip += 1

        # 复制替换规则
        for replace_rule in source_rule.replace_rules:
            # 检查是否已存在
            exists = any(r.pattern == replace_rule.pattern and r.content == replace_rule.content
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                replace_rules_success += 1
            else:
                replace_rules_skip += 1

        # 复制媒体扩展名设置
        if hasattr(source_rule, 'media_extensions') and source_rule.media_extensions:
            for extension in source_rule.media_extensions:
                # 检查是否已存在
                exists = any(e.extension == extension.extension for e in target_rule.media_extensions)
                if not exists:
                    new_extension = MediaExtensions(
                        rule_id=target_rule.id,
                        extension=extension.extension
                    )
                    session.add(new_extension)
                    media_extensions_success += 1
                else:
                    media_extensions_skip += 1

        # 复制媒体类型设置
        if hasattr(source_rule, 'media_types') and source_rule.media_types:
            target_media_types = session.query(MediaTypes).filter_by(rule_id=target_rule.id).first()

            if not target_media_types:
                # 如果目标规则没有媒体类型设置，创建新的
                target_media_types = MediaTypes(rule_id=target_rule.id)

                # 使用inspect自动复制所有字段（除了id和rule_id）
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

                session.add(target_media_types)
            else:
                # 如果已有设置，更新现有设置
                # 使用inspect自动复制所有字段（除了id和rule_id）
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

        # 复制规则同步表数据
        rule_syncs_success = 0
        rule_syncs_skip = 0
        
        # 检查源规则是否有同步关系
        if hasattr(source_rule, 'rule_syncs') and source_rule.rule_syncs:
            for sync in source_rule.rule_syncs:
                # 检查是否已存在
                exists = any(s.sync_rule_id == sync.sync_rule_id for s in target_rule.rule_syncs)
                if not exists:
                    # 确保不会创建自引用的同步关系
                    if sync.sync_rule_id != target_rule.id:
                        new_sync = RuleSync(
                            rule_id=target_rule.id,
                            sync_rule_id=sync.sync_rule_id
                        )
                        session.add(new_sync)
                        rule_syncs_success += 1
                        
                        # 启用目标规则的同步功能
                        if rule_syncs_success > 0:
                            target_rule.enable_sync = True
                else:
                    rule_syncs_skip += 1

        # 复制规则设置
        # 获取ForwardRule模型的所有字段
        inspector = inspect(ForwardRule)
        for column in inspector.columns:
            column_name = column.key
            if column_name not in ['id', 'source_chat_id', 'target_chat_id', 'source_chat', 'target_chat',
                                      'keywords', 'replace_rules', 'media_types']:
                # 获取源规则的值并设置到目标规则
                value = getattr(source_rule, column_name)
                setattr(target_rule, column_name, value)

        session.commit()


        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            t('other.copy_rule.result', source=source_rule_id, target=target_rule.id, kn_ok=keywords_normal_success, kn_skip=keywords_normal_skip, kr_ok=keywords_regex_success, kr_skip=keywords_regex_skip, rr_ok=replace_rules_success, rr_skip=replace_rules_skip, me_ok=media_extensions_success, me_skip=media_extensions_skip, rs_ok=rule_syncs_success, rs_skip=rule_syncs_skip),
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.copy_rule_error'))
    finally:
        session.close()

async def handle_export_replace_command(event, client):
    """处理 export_replace 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取所有替换规则
        replace_rules = []
        for rule in rule.replace_rules:
            replace_rules.append((rule.pattern, rule.content))

        # 如果没有替换规则
        if not replace_rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, t('cmd.no_replace_rules'))
            return

        # 创建并写入文件
        replace_file = os.path.join(TEMP_DIR, 'replace_rules.txt')

        # 写入替换规则，每行一个规则，用制表符分隔
        with open(replace_file, 'w', encoding='utf-8') as f:
            for pattern, content in replace_rules:
                line = f"{pattern}\t{content if content else ''}"
                f.write(line + '\n')

        try:
            # 先发送文件
            await event.client.send_file(
                event.chat_id,
                replace_file
            )

            # 然后单独发送说明文字
            await respond_and_delete(event,(t('cmd.export.rule', name=source_chat.name)))

        finally:
            # 删除临时文件
            if os.path.exists(replace_file):
                os.remove(replace_file)

    except Exception as e:
        logger.error(f'导出替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.export_replace_error'))
    finally:
        session.close()


async def handle_remove_all_keyword_command(event, command, parts):
    """处理 remove_all_keyword 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.usage.keywords', command=command), parse_mode='html')
        return

    # 分离命令和参数部分
    _, args_text = message_text.split(None, 1)
    logger.info(f"分离出的参数部分: {args_text}")

    try:
        # 使用 shlex 来正确处理带引号的参数
        logger.info("开始使用 shlex 解析参数")
        keywords_to_remove = shlex.split(args_text)
        logger.info(f"shlex 解析结果: {keywords_to_remove}")
    except ValueError as e:
        logger.error(f"shlex 解析出错: {str(e)}")
        # 处理未闭合的引号等错误
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.quote_mismatch'))
        return

    if not keywords_to_remove:
        logger.warning("没有提供任何关键字")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.need_keyword'))
        return

    session = get_session()
    try:
        # 获取当前规则以确定黑白名单模式
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        current_rule, source_chat = rule_info
        mode_name = t('common.blacklist') if current_rule.add_mode == AddMode.BLACKLIST else t('common.whitelist')

        # 获取所有相关规则
        rules = await get_all_rules(session, event)
        if not rules:
            return

        db_ops = await get_db_ops()
        total_removed = 0
        total_not_found = 0
        removed_details = {}  # 用于记录每个规则删除的关键字

        # 从每个规则中删除关键字
        for rule in rules:
            # 获取当前规则的关键字
            rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
            keywords = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not keywords:
                continue

            rule_removed = 0
            rule_removed_keywords = []

            # 删除匹配的关键字
            for keyword in keywords:
                if keyword.keyword in keywords_to_remove:
                    logger.info(f"在规则 {rule.id} 中删除关键字: {keyword.keyword}")
                    session.delete(keyword)
                    rule_removed += 1
                    rule_removed_keywords.append(keyword.keyword)

            if rule_removed > 0:
                removed_details[rule.id] = rule_removed_keywords
                total_removed += rule_removed
            else:
                total_not_found += 1

        session.commit()

        # 构建回复消息
        if total_removed > 0:
            result_text = t('cmd.remove_all.header', mode=mode_name)
            for rule_id, keywords in removed_details.items():
                rule = next((r for r in rules if r.id == rule_id), None)
                if rule:
                    result_text += t('cmd.remove_all.rule_line', rule_id=rule_id, name=rule.source_chat.name)
                    result_text += "\n".join(f"- {k}" for k in keywords)
                    result_text += "\n\n"
            result_text += t('cmd.remove_all.total', count=total_removed)

            logger.info(f"发送回复消息: {result_text}")
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,result_text)
        else:
            msg = t('cmd.remove.not_found_in_mode', mode=mode_name)
            logger.info(msg)
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,msg)

    except Exception as e:
        session.rollback()
        logger.error(f'批量删除关键字时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.delete_kw_error'))
    finally:
        session.close()

async def handle_add_all_command(event, command, parts):
    """处理 add_all 和 add_regex_all 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.usage.keywords', command=command), parse_mode='html')
        return

    # 分离命令和参数部分
    _, args_text = message_text.split(None, 1)
    logger.info(f"分离出的参数部分: {args_text}")

    keywords = []
    if command == 'add_all':
        try:
            # 使用 shlex 来正确处理带引号的参数
            logger.info("开始使用 shlex 解析参数")
            keywords = shlex.split(args_text)
            logger.info(f"shlex 解析结果: {keywords}")
        except ValueError as e:
            logger.error(f"shlex 解析出错: {str(e)}")
            # 处理未闭合的引号等错误
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.quote_mismatch'))
            return
    else:
        # add_regex_all 命令使用简单分割，保持正则表达式的原始形式
        if len(args_text.split()) > 0:
            keywords = args_text.split()
        else:
            keywords = [args_text]
        logger.info(f"add_regex_all 命令，使用原始参数: {keywords}")

    if not keywords:
        logger.warning("没有提供任何关键字")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.need_keyword'))
        return

    session = get_session()
    try:
        rules = await get_all_rules(session, event)
        if not rules:
            return

        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        current_rule, source_chat = rule_info

        db_ops = await get_db_ops()
        # 为每个规则添加关键字
        success_count = 0
        duplicate_count = 0
        for rule in rules:
            # 使用 add_keywords 添加关键字
            s_count, d_count = await db_ops.add_keywords(
                session,
                rule.id,
                keywords,
                is_regex=(command == 'add_regex_all'),
                is_blacklist=(current_rule.add_mode == AddMode.BLACKLIST)
            )
            success_count += s_count
            duplicate_count += d_count

        session.commit()

        # 构建回复消息
        keyword_type = t('cmd.kwtype.regex') if command == "add_regex_all" else t('cmd.kwtype.keyword')
        keywords_text = '\n'.join(f'- {k}' for k in keywords)
        result_text = t('cmd.add_all.added', count=success_count, type=keyword_type)
        if duplicate_count > 0:
            result_text += t('cmd.add_all.skipped', count=duplicate_count)
        result_text += t('cmd.add_all.kw_list', keywords=keywords_text)

        logger.info(f"发送回复消息: {result_text}")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'批量添加关键字时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.add_keyword_error'))
    finally:
        session.close()

async def handle_replace_all_command(event, parts):
    """处理 replace_all 命令"""
    message_text = event.message.text
    
    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.replace_all.usage'))
        return

    # 直接分割参数，保持正则表达式的原始形式
    _, args_text = message_text.split(None, 1)
    
    # 按第一个空格分割，保持后续内容不变
    parts = args_text.split(None, 1)
    pattern = parts[0]
    content = parts[1] if len(parts) > 1 else ''
    
    logger.info(f"解析替换命令参数: pattern='{pattern}', content='{content}'")

    session = get_session()
    try:
        rules = await get_all_rules(session, event)
        if not rules:
            return

        db_ops = await get_db_ops()
        # 为每个规则添加替换规则
        total_success = 0
        total_duplicate = 0

        for rule in rules:
            # 使用 add_replace_rules 添加替换规则
            success_count, duplicate_count = await db_ops.add_replace_rules(
                session,
                rule.id,
                [(pattern, content)]  # 传入一个元组列表，每个元组包含 pattern 和 content
            )

            # 累计成功和重复的数量
            total_success += success_count
            total_duplicate += duplicate_count

            # 确保启用替换模式
            if success_count > 0 and not rule.is_replace:
                rule.is_replace = True

        session.commit()

        # 构建回复消息
        action_type = t('cmd.action.delete') if not content else t('cmd.action.replace')
        result_text = t('cmd.replace_all.added', count=len(rules))
        if total_success > 0:
            result_text += t('cmd.replace_all.success', count=total_success)
            result_text += t('cmd.replace_all.pattern', pattern=pattern)
            result_text += t('cmd.replace.action', action=action_type)
            if content:
                result_text += t('cmd.replace_all.replace_with', content=content)
        if total_duplicate > 0:
            result_text += t('cmd.replace_all.skipped', count=total_duplicate)

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'批量添加替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.add_replace_error'))
    finally:
        session.close()

async def handle_list_rule_command(event, command, parts):
    """处理 list_rule 命令"""
    session = get_session()
    try:
        # 获取页码参数，默认为第1页
        try:
            page = int(parts[1]) if len(parts) > 1 else 1
            if page < 1:
                page = 1
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.err.page_number'))
            return

        # 设置每页显示的数量
        per_page = 30
        offset = (page - 1) * per_page

        # 获取总规则数
        total_rules = session.query(ForwardRule).count()

        if total_rules == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.no_rules'))
            return

        # 计算总页数
        total_pages = (total_rules + per_page - 1) // per_page

        # 如果请求的页码超出范围，使用最后一页
        if page > total_pages:
            page = total_pages
            offset = (page - 1) * per_page

        # 获取当前页的规则
        rules = session.query(ForwardRule).order_by(ForwardRule.id).offset(offset).limit(per_page).all()

        # 构建规则列表消息
        message_parts = [t('callback.rule_list_header', page=page, total_pages=total_pages)]

        for rule in rules:
            # 获取源聊天和目标聊天的名称
            source_chat = rule.source_chat
            target_chat = rule.target_chat

            # 构建规则描述
            rule_desc = (
                f'<b>ID: {rule.id}</b>\n'
                f'<blockquote>{t("callback.source_label")}{source_chat.name} ({source_chat.telegram_chat_id})\n'
                f'{t("callback.target_label")}{target_chat.name} ({target_chat.telegram_chat_id})\n'
                '</blockquote>'
            )
            message_parts.append(rule_desc)

        # 创建分页按钮
        buttons = []
        nav_row = []

        # 添加上一页按钮
        if page > 1:
            nav_row.append(Button.inline(t('common.page.prev'), f'page_rule:{page-1}'))
        else:
            nav_row.append(Button.inline('⬅️', 'noop'))  # 禁用状态的按钮

        # 添加页码按钮
        nav_row.append(Button.inline(f'{page}/{total_pages}', 'noop'))

        # 添加下一页按钮
        if page < total_pages:
            nav_row.append(Button.inline(t('common.page.next'), f'page_rule:{page+1}'))
        else:
            nav_row.append(Button.inline('➡️', 'noop'))  # 禁用状态的按钮

        buttons.append(nav_row)

        # 发送消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'\n'.join(message_parts), buttons=buttons, parse_mode='html')

    except Exception as e:
        logger.error(f'列出规则时出错: {str(e)}')
        logger.exception(e)
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.list_rule_error'))
    finally:
        session.close()

async def handle_delete_rule_command(event, command, parts):
    """处理 delete_rule 命令"""
    if len(parts) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.remove.usage_id', command=command), parse_mode='html')
        return

    try:
        ids_to_remove = [int(x) for x in parts[1:]]
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.id_number'))
        return

    session = get_session()
    try:
        success_ids = []
        failed_ids = []
        not_found_ids = []

        for rule_id in ids_to_remove:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                not_found_ids.append(rule_id)
                continue

            try:
                # 删除规则（关联的替换规则、关键字和媒体类型会自动删除）
                session.delete(rule)

                # 尝试从RSS服务删除规则数据
                try:
                    rss_url = f"http://{RSS_HOST}:{RSS_PORT}/api/rule/{rule_id}"
                    async with aiohttp.ClientSession() as client_session:
                        async with client_session.delete(rss_url) as response:
                            if response.status == 200:
                                logger.info(f"成功删除RSS规则数据: {rule_id}")
                            else:
                                response_text = await response.text()
                                logger.warning(f"删除RSS规则数据失败 {rule_id}, 状态码: {response.status}, 响应: {response_text}")
                except Exception as rss_err:
                    logger.error(f"调用RSS删除API时出错: {str(rss_err)}")
                    # 不影响主要流程，继续执行

                success_ids.append(rule_id)
            except Exception as e:
                logger.error(f'删除规则 {rule_id} 时出错: {str(e)}')
                failed_ids.append(rule_id)

        # 提交事务
        session.commit()
        
        # 清理不再使用的聊天记录
        # 这里直接对整个数据库进行一次清理，不需要单独处理每个规则
        # 因为所有规则都已经从数据库中删除
        deleted_chats = await check_and_clean_chats(session)
        if deleted_chats > 0:
            logger.info(f"删除规则后清理了 {deleted_chats} 个未使用的聊天记录")

        # 构建响应消息
        response_parts = []
        if success_ids:
            response_parts.append(t('cmd.delete.success', ids=", ".join(map(str, success_ids))))
        if not_found_ids:
            response_parts.append(t('cmd.delete.not_found', ids=", ".join(map(str, not_found_ids))))
        if failed_ids:
            response_parts.append(t('cmd.delete.failed', ids=", ".join(map(str, failed_ids))))
        if deleted_chats > 0:
            response_parts.append(t('cmd.delete.cleaned', count=deleted_chats))

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'\n'.join(response_parts) or t('cmd.delete.none'))

    except Exception as e:
        session.rollback()
        logger.error(f'删除规则时出错: {str(e)}')
        logger.exception(e)
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.err.delete_rule_error'))
    finally:
        session.close()


async def handle_delete_rss_user_command(event, command, parts):
    """处理 delete_rss_user 命令"""
    db_ops = await get_db_ops()
    session = get_session()

    try:
        # 检查是否指定了用户名
        specified_username = None
        if len(parts) > 1:
            specified_username = parts[1].strip()

        # 查询所有用户
        users = session.query(models.User).all()

        if not users:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, t('cmd.rss.no_users'))
            return

        # 占位，不排除以后有多用户功能，如果指定了用户名，尝试删除该用户
        if specified_username:
            user = session.query(models.User).filter(models.User.username == specified_username).first()
            if user:
                session.delete(user)
                session.commit()
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.rss.deleted', user=specified_username))
                return
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,t('cmd.rss.user_not_found', user=specified_username))
                return

        # 如果没有指定用户名
        # 默认只有一个用户，直接删除
        if len(users) == 1:
            user = users[0]
            username = user.username
            session.delete(user)
            session.commit()
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,t('cmd.rss.deleted', user=username))
            return

        # 占位，不排除以后有多用户功能，如果有多个用户，则列出所有用户并提示指定用户名
        usernames = [user.username for user in users]
        user_list = "\n".join([f"{i+1}. {username}" for i, username in enumerate(usernames)])

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,t('cmd.rss.multiple', users=user_list))

    except Exception as e:
        session.rollback()
        error_message = t('cmd.rss.delete_error', error=str(e))
        logger.error(error_message)
        logger.error(traceback.format_exc())
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,error_message)
    finally:
        session.close()
