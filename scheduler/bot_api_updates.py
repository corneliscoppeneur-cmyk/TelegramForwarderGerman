"""Long-Poll der Bot-HTTP-API (``getUpdates``) neben der Telethon-Session.

Warum: Die HTTP-Bot-API kennt einen Chat erst, wenn ihre eigene Server-Session
ein Update daraus gesehen hat. Läuft der Bot nur über Telethon (MTProto),
antwortet ``sendWidget`` mit „chat not found". Dieser Poller hält die
HTTP-Session warm, damit Widgets an alle Nutzer gehen, die dem Bot schreiben.

Nebeneffekt: ``widget_query``-Updates (Buttons mit ``TelegramWidget.request``)
kommen hier an. Aktuell werden sie nur leer beantwortet (Bot API verlangt eine
Antwort binnen 15 s); echte Aktionen folgen in Phase 2.

Alle fachlichen Nachrichten verarbeitet weiterhin Telethon – Updates hier
werden nicht ausgewertet, nur bestätigt (Offset).
"""
import asyncio
import logging

from utils import bot_api

logger = logging.getLogger(__name__)

LONG_POLL_SECONDS = 50
RETRY_SECONDS = 15
ALLOWED_UPDATES = ['message', 'widget_query']


class BotApiUpdatesPoller:
    def __init__(self):
        self._task = None
        self._offset = None

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name='bot-api-updates')
            logger.info('Bot-API-Poller gestartet (getUpdates, hält HTTP-Session für Widgets warm)')

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _run(self):
        while True:
            try:
                updates = await bot_api.call(
                    'getUpdates', http_timeout=LONG_POLL_SECONDS + 15,
                    offset=self._offset, limit=100, timeout=LONG_POLL_SECONDS,
                    allowed_updates=ALLOWED_UPDATES,
                )
                for upd in updates or []:
                    self._offset = upd['update_id'] + 1
                    query = upd.get('widget_query')
                    if query:
                        await self._answer_widget_query(query)
            except asyncio.CancelledError:
                raise
            except bot_api.BotApiError as e:
                if e.code == 409:
                    # Webhook gesetzt oder zweiter Poller – hier nichts zu tun
                    logger.warning(f'Bot-API-Poller gestoppt: {e.description}')
                    return
                logger.warning(f'Bot-API-Poller: {e}')
                await asyncio.sleep(RETRY_SECONDS)
            except Exception as e:
                logger.warning(f'Bot-API-Poller: {type(e).__name__}: {e}')
                await asyncio.sleep(RETRY_SECONDS)

    @staticmethod
    async def _answer_widget_query(query):
        """Widget-Anfrage leer bestätigen (Phase 2: echte Aktionen)."""
        try:
            logger.info(f"Widget-Query {query.get('data')!r} von {query.get('from', {}).get('id')}")
            await bot_api.call('answerWidgetQuery', widget_query_id=query['id'])
        except Exception as e:
            logger.debug(f'answerWidgetQuery fehlgeschlagen: {e}')
