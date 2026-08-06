from telethon import TelegramClient, types
from telethon.tl.types import BotCommand
from telethon.tl.functions.bots import SetBotCommandsRequest
from models.models import init_db
from dotenv import load_dotenv
from message_listener import setup_listeners
import os
import asyncio
import logging
from utils.i18n import t
import uvicorn
import multiprocessing
from models.db_operations import DBOperations
from scheduler.summary_scheduler import SummaryScheduler
from scheduler.chat_updater import ChatUpdater
from handlers.bot_handler import send_welcome_message
from rss.main import app as rss_app
from utils.log_config import setup_logging
from utils.proxy import build_proxy

# 设置Docker日志的默认配置，如果docker-compose.yml中没有配置日志选项将使用这些值
os.environ.setdefault('DOCKER_LOG_MAX_SIZE', '10m')
os.environ.setdefault('DOCKER_LOG_MAX_FILE', '3')

# 设置日志配置
setup_logging()

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 从环境变量获取配置
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')
phone_number = os.getenv('PHONE_NUMBER')

# 创建 DBOperations 实例
db_ops = None

scheduler = None
chat_updater = None
user_updates_task = None


async def init_db_ops():
    """初始化 DBOperations 实例"""
    global db_ops
    if db_ops is None:
        db_ops = await DBOperations.create()
    return db_ops


# 创建文件夹
os.makedirs('./sessions', exist_ok=True)
os.makedirs('./temp', exist_ok=True)


# 清空./temp文件夹
def clear_temp_dir():
    for file in os.listdir('./temp'):
        os.remove(os.path.join('./temp', file))


# Optionaler Proxy: eigene Ausgangs-IP je Instanz (PROXY_URL in der .env)
_proxy, _proxy_connection = build_proxy()
_client_options = {}
if _proxy:
    _client_options['proxy'] = _proxy
if _proxy_connection:
    _client_options['connection'] = _proxy_connection

# 创建客户端
user_client = TelegramClient('./sessions/user', api_id, api_hash, **_client_options)
bot_client = TelegramClient('./sessions/bot', api_id, api_hash, **_client_options)

# 初始化数据库
engine = init_db()


def run_rss_server(host: str, port: int):
    """在新进程中运行 RSS 服务器"""
    uvicorn.run(
        rss_app,
        host=host,
        port=port
    )


async def start_account_services():
    """Dienste starten, die ein angemeldetes Telegram-Konto voraussetzen.

    Wird beim Start aufgerufen und noch einmal, sobald sich jemand über den
    Bot-Chat angemeldet hat. Mehrfachaufrufe sind unschädlich.
    """
    global scheduler, chat_updater, user_updates_task

    if not await user_client.is_user_authorized():
        return False

    # Update-Schleife des Kontos erst jetzt starten: ohne Anmeldung antwortet
    # Telegram auf die erste Abfrage mit AuthKeyUnregisteredError.
    if user_updates_task is None or user_updates_task.done():
        user_updates_task = asyncio.create_task(user_client.run_until_disconnected())

    if scheduler is None:
        scheduler = SummaryScheduler(user_client, bot_client)
        await scheduler.start()

    if chat_updater is None:
        chat_updater = ChatUpdater(user_client)
        await chat_updater.start()

    return True


async def start_clients():
    # 初始化 DBOperations
    global db_ops, scheduler, chat_updater
    db_ops = await DBOperations.create()

    try:
        # 启动机器人客户端
        await bot_client.start(bot_token=bot_token)
        me_bot = await bot_client.get_me()
        print(f'机器人客户端已启动: {me_bot.first_name} (@{me_bot.username})')

        # Nutzerkonto verbinden, aber NICHT im Terminal nach einem Code fragen:
        # ohne angemeldetes Konto läuft die Anmeldung über den Bot-Chat.
        await user_client.connect()
        authorized = await user_client.is_user_authorized()

        # Der alte Weg (Nummer und Code am Terminal) muss ausdrücklich angefordert
        # werden. Auf stdin zu prüfen reicht nicht: docker-compose setzt tty=true,
        # dann sähe auch ein Start im Hintergrund wie ein Terminal aus und der
        # Prozess würde auf eine Eingabe warten, die nie kommt.
        if not authorized and phone_number and os.getenv('TERMINAL_LOGIN', 'false').lower() == 'true':
            await user_client.start(phone=phone_number)
            authorized = await user_client.is_user_authorized()

        if authorized:
            me_user = await user_client.get_me()
            print(f'用户客户端已启动: {me_user.first_name} (@{me_user.username})')
        else:
            logger.warning('Kein Telegram-Konto angemeldet – Anmeldung läuft über den Bot-Chat')

        # 设置消息监听器
        await setup_listeners(user_client, bot_client)

        # 注册命令
        await register_bot_commands(bot_client)

        # Zeitgesteuerte Dienste nur mit angemeldetem Konto
        await start_account_services()

        # 如果启用了 RSS 服务
        if os.getenv('RSS_ENABLED', '').lower() == 'true':
            try:
                rss_host = os.getenv('RSS_HOST', '0.0.0.0')
                rss_port = int(os.getenv('RSS_PORT', '8000'))
                logger.info(f"正在启动 RSS 服务 (host={rss_host}, port={rss_port})")
                
                # 在新进程中启动 RSS 服务
                rss_process = multiprocessing.Process(
                    target=run_rss_server,
                    args=(rss_host, rss_port)
                )
                rss_process.start()
                logger.info("RSS 服务启动成功")
            except Exception as e:
                logger.error(f"启动 RSS 服务失败: {str(e)}")
                logger.exception(e)
        else:
            logger.info("RSS 服务未启用")

        # 发送欢迎消息
        await send_welcome_message(bot_client)

        # Der Bot hält den Prozess am Leben. Die Update-Schleife des Kontos
        # läuft als eigene Aufgabe und startet erst nach der Anmeldung
        # (siehe start_account_services).
        await bot_client.run_until_disconnected()
    finally:
        # 关闭 DBOperations
        if db_ops and hasattr(db_ops, 'close'):
            await db_ops.close()
        # 停止调度器
        if scheduler:
            scheduler.stop()
        # 停止聊天信息更新器
        if chat_updater:
            chat_updater.stop()
        # 如果 RSS 服务在运行，停止它
        if 'rss_process' in locals() and rss_process.is_alive():
            rss_process.terminate()
            rss_process.join()


async def register_bot_commands(bot):
    """注册机器人命令"""
    # # 先清空现有命令
    # try:
    #     await bot(SetBotCommandsRequest(
    #         scope=types.BotCommandScopeDefault(),
    #         lang_code='',
    #         commands=[]  # 空列表清空所有命令
    #     ))
    #     logger.info('已清空现有机器人命令')
    # except Exception as e:
    #     logger.error(f'清空机器人命令时出错: {str(e)}')

    # Sichtbares Befehlsmenue bewusst auf zwei Eintraege reduziert:
    # Die Bedienung laeuft ueber Inline-Buttons. Alle uebrigen Befehle
    # funktionieren weiterhin (siehe handlers/bot_handler.py), werden aber
    # nicht mehr im Telegram-Menue angeboten.
    commands = [
        BotCommand(
            command='start',
            description=t('botcmd.start')
        ),
        BotCommand(
            command='help',
            description=t('botcmd.help')
        ),
    ]

    # Ohne Sprachcode registrieren, damit das Menue auch bei Telegram-Clients
    # mit anderer Oberflaechensprache erscheint; zusaetzlich fuer 'de'.
    for lang_code in ('', 'de'):
        try:
            result = await bot(SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(),
                lang_code=lang_code,
                commands=commands
            ))
            if result:
                logger.info(f'已成功注册机器人命令 (lang_code={lang_code or "default"})')
            else:
                logger.error(f'注册机器人命令失败 (lang_code={lang_code or "default"})')
        except Exception as e:
            logger.error(f'注册机器人命令时出错: {str(e)}')


if __name__ == '__main__':
    # 运行事件循环
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_clients())
    except KeyboardInterrupt:
        print("正在关闭客户端...")
    finally:
        loop.close()
