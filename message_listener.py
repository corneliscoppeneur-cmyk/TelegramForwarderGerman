from telethon import events
from models.models import get_session, Chat, ForwardRule
import logging
from handlers import user_handler, bot_handler
from handlers.prompt_handlers import handle_prompt_setting
import asyncio
import os
import json
import aiohttp
from dotenv import load_dotenv
from telethon.tl.types import ChannelParticipantsAdmins
from managers.state_manager import state_manager
from telethon.tl import types
from filters.process import process_forward_rule

load_dotenv()

logger = logging.getLogger(__name__)
PROCESSED_GROUPS = set()
BOT_ID = None
_last_update_id = 0


async def setup_listeners(user_client, bot_client):
    """设置消息监听器 + Bot API Polling"""
    global BOT_ID

    try:
        me = await bot_client.get_me()
        BOT_ID = me.id
        logger.info(f"获取到机器人ID: {BOT_ID}")
    except Exception as e:
        logger.error(f"获取机器人ID时出错: {str(e)}")
        return

    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("BOT_TOKEN nicht gesetzt!")
        return

    # Starte Bot API Polling (HTTP-direkter Zugriff auf Telegram)
    logger.info("[BOT-API] Starte Bot API HTTP-Polling")
    asyncio.create_task(bot_api_polling_loop(bot_client, bot_token))

    # User-Client für Weiterleitung
    async def not_from_bot(event):
        if BOT_ID is None:
            return True
        try:
            return int(event.sender_id) != BOT_ID
        except (ValueError, TypeError):
            return True

    @user_client.on(events.NewMessage(func=not_from_bot))
    async def user_message_handler(event):
        await handle_user_message(event, user_client, bot_client)

    bot_client.add_event_handler(bot_handler.callback_handler)
    logger.info("[INFO] Message listeners setup complete")


async def bot_api_polling_loop(bot_client, bot_token):
    """Rufe Updates direkt von Telegram Bot API ab (kein Telethon)."""
    global _last_update_id

    logger.info("[BOT-API] Bot API Polling-Schleife gestartet")
    api_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                params = {"offset": _last_update_id + 1, "timeout": 30}
                async with session.post(api_url, json=params) as resp:
                    if resp.status != 200:
                        logger.error(f"[BOT-API] HTTP {resp.status}")
                        await asyncio.sleep(5)
                        continue

                    data = await resp.json()
                    if not data.get("ok"):
                        logger.error(f"[BOT-API] Telegram error: {data.get('description')}")
                        await asyncio.sleep(5)
                        continue

                    updates = data.get("result", [])
                    if updates:
                        logger.info(f"[BOT-API] {len(updates)} Updates empfangen")

                    for update in updates:
                        try:
                            _last_update_id = update["update_id"]
                            message = update.get("message")
                            callback = update.get("callback_query")

                            if message:
                                event = BotApiMessage(message, bot_client)
                                await handle_bot_message(event, bot_client)
                            elif callback:
                                event = BotApiCallback(callback, bot_client)
                                await bot_handler.callback_handler(event)

                        except Exception as e:
                            logger.error(f"[BOT-API] Update-Error: {e}", exc_info=True)

            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error(f"[BOT-API] Polling-Error: {e}", exc_info=True)
                await asyncio.sleep(5)


class BotApiMessage:
    """Telethon-kompatibles Event-Wrapper für Bot API Messages."""
    def __init__(self, msg, bot_client):
        self.message = self
        self.sender_id = msg.get("from", {}).get("id")
        self.chat_id = msg.get("chat", {}).get("id")
        self.text = msg.get("text")
        self.chat = type('Chat', (), {'id': self.chat_id})()  # Für Handler
        self._message_data = msg
        self.bot_client = bot_client

    async def get_chat(self):
        """Simuliere event.get_chat()"""
        return self.chat


class BotApiCallback:
    """Telethon-kompatibles Event-Wrapper für Callbacks."""
    def __init__(self, callback, bot_client):
        self.data = callback.get("data", "").encode() if callback.get("data") else b""
        self.sender_id = callback.get("from", {}).get("id")
        self.chat_id = callback.get("message", {}).get("chat", {}).get("id")
        self._callback_data = callback
        self.bot_client = bot_client

    async def get_chat(self):
        return type('Chat', (), {'id': self.chat_id})()

async def handle_user_message(event, user_client, bot_client):
    """处理用户客户端收到的消息"""
    # logger.info("handle_user_message:开始处理用户消息")
    
    chat = await event.get_chat()
    chat_id = abs(chat.id)
    # logger.info(f"handle_user_message:获取到聊天ID: {chat_id}")

    # 检查是否频道消息
    if isinstance(event.chat, types.Channel) and state_manager.check_state():
        # logger.info("handle_user_message:检测到频道消息且存在状态")
        sender_id = os.getenv('USER_ID')
        # 频道ID需要加上100前缀
        chat_id = int(f"100{chat_id}")
        # logger.info(f"handle_user_message:频道消息处理: sender_id={sender_id}, chat_id={chat_id}")
    else:
        sender_id = event.sender_id
        # logger.info(f"handle_user_message:非频道消息处理: sender_id={sender_id}")

    # 检查用户状态
    current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
    # logger.info(f'handle_user_message：当前是否有状态: {state_manager.check_state()}')
    # logger.info(f"handle_user_message：当前用户ID和聊天ID: {sender_id}, {chat_id}")
    # logger.info(f"handle_user_message：获取当前聊天窗口的用户状态: {current_state}")
    
    if current_state:
        # logger.info(f"检测到用户状态: {current_state}")
        # 处理提示词设置
        # logger.info("准备处理提示词设置")
        if await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message):
            # logger.info("提示词设置处理完成，返回")
            return
        # logger.info("提示词设置处理未完成，继续执行")

    # 检查是否是媒体组消息
    if event.message.grouped_id:
        # 如果这个媒体组已经处理过，就跳过
        group_key = f"{chat_id}:{event.message.grouped_id}"
        if group_key in PROCESSED_GROUPS:
            return
        # 标记这个媒体组为已处理
        PROCESSED_GROUPS.add(group_key)
        asyncio.create_task(clear_group_cache(group_key))
    
    # 首先检查数据库中是否有该聊天的转发规则
    session = get_session()
    try:
        # 查询源聊天
        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == str(chat_id)
        ).first()
        
        if not source_chat:
            return
            
        # 添加日志：查询转发规则
        logger.info(f'找到源聊天: {source_chat.name} (ID: {source_chat.id})')
        
        # 查找以当前聊天为源的规则
        rules = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id
        ).all()
        
        if not rules:
            logger.info(f'聊天 {source_chat.name} 没有转发规则')
            return
        
        # 有转发规则时，才记录消息信息
        if event.message.grouped_id:
            logger.info(f'[用户] 收到媒体组消息 来自聊天: {source_chat.name} ({chat_id}) 组ID: {event.message.grouped_id}')
        else:
            logger.info(f'[用户] 收到新消息 来自聊天: {source_chat.name} ({chat_id}) 内容: {event.message.text}')
            
        # 添加日志：处理规则
        logger.info(f'找到 {len(rules)} 条转发规则')
        
        # 处理每条转发规则
        for rule in rules:
            target_chat = rule.target_chat
            if not rule.enable_rule:
                logger.info(f'规则 {rule.id} 未启用')
                continue
            logger.info(f'处理转发规则 ID: {rule.id} (从 {source_chat.name} 转发到: {target_chat.name})')
            if rule.use_bot:
                # 直接使用过滤器模块中的process_forward_rule函数
                await process_forward_rule(bot_client, event, str(chat_id), rule)
            else:
                await user_handler.process_forward_rule(user_client, event, str(chat_id), rule)
        
    except Exception as e:
        logger.error(f'处理用户消息时发生错误: {str(e)}')
        logger.exception(e)  # 添加详细的错误堆栈
    finally:
        session.close()

async def handle_bot_message(event, bot_client):
    """处理机器人客户端收到的消息（命令）"""
    try:

        logger.info("[DEBUG] handle_bot_message: Nachricht empfangen, Admin-Check wird durchgeführt")
        
        chat = await event.get_chat()
        chat_id = abs(chat.id)
        # logger.info(f"handle_bot_message:获取到聊天ID: {chat_id}")

        # 检查是否频道消息
        if isinstance(event.chat, types.Channel) and state_manager.check_state():
            # logger.info("handle_bot_message:检测到频道消息且存在状态")
            sender_id = os.getenv('USER_ID')
            # 频道ID需要加上100前缀
            chat_id = int(f"100{chat_id}")
            # logger.info(f"handle_bot_message:频道消息处理: sender_id={sender_id}, chat_id={chat_id}")
        else:
            sender_id = event.sender_id
            # logger.info(f"handle_bot_message:非频道消息处理: sender_id={sender_id}")

        # 检查用户状态
        current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
        # logger.info(f'handle_bot_message：当前是否有状态: {state_manager.check_state()}')
        # logger.info(f"handle_bot_message：当前用户ID和聊天ID: {sender_id}, {chat_id}")
        # logger.info(f"handle_bot_message：获取当前聊天窗口的用户状态: {current_state}")

        
        
        # 处理提示词设置
        if current_state:
            await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message)
            return

        # 如果没有特殊状态，则处理常规命令
        await bot_handler.handle_command(bot_client, event)
    except Exception as e:
        logger.error(f'处理机器人命令时发生错误: {str(e)}')
        logger.exception(e)

async def clear_group_cache(group_key, delay=300):  # 5分钟后清除缓存
    """清除已处理的媒体组记录"""
    await asyncio.sleep(delay)
    PROCESSED_GROUPS.discard(group_key) 

