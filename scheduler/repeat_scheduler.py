import asyncio
import logging
import traceback

from telethon import TelegramClient

from models.models import get_session, ForwardRule

logger = logging.getLogger(__name__)

# Kürzerer Abstand ist gegenüber Telegram nicht sinnvoll und provoziert Sperren
MIN_INTERVAL_MINUTES = 1


class RepeatScheduler:
    """Schickt den zuletzt weitergeleiteten Beitrag in festem Abstand erneut.

    Pro Regel läuft eine eigene Aufgabe – dasselbe Muster wie im
    ``SummaryScheduler``. Welcher Beitrag gemeint ist, steht in
    ``ForwardRule.last_message_id`` und wird vom ``RepeatFilter`` gepflegt.
    """

    def __init__(self, user_client: TelegramClient, bot_client: TelegramClient):
        self.tasks = {}  # {rule_id: task}
        self.user_client = user_client
        self.bot_client = bot_client

    async def schedule_rule(self, rule):
        """Aufgabe für eine Regel anlegen, ersetzen oder entfernen."""
        try:
            if rule.id in self.tasks:
                self.tasks.pop(rule.id).cancel()
                logger.info(f'Wiederholung: alte Aufgabe für Regel {rule.id} beendet')

            if not rule.enable_repeat:
                return

            interval = max(int(rule.repeat_interval or 60), MIN_INTERVAL_MINUTES)
            self.tasks[rule.id] = asyncio.create_task(self._run(rule.id, interval))
            logger.info(f'Wiederholung: Regel {rule.id} läuft alle {interval} Minuten')
        except Exception as e:
            logger.error(f'Wiederholung: Regel {rule.id} konnte nicht geplant werden: {e}')
            logger.error(traceback.format_exc())

    async def _run(self, rule_id, interval):
        """Warten und wiederholen, bis die Aufgabe abgebrochen wird."""
        while True:
            try:
                await asyncio.sleep(interval * 60)
                await self._repeat_once(rule_id)
            except asyncio.CancelledError:
                logger.info(f'Wiederholung: Aufgabe für Regel {rule_id} beendet')
                break
            except Exception as e:
                logger.error(f'Wiederholung: Regel {rule_id} fehlgeschlagen: {e}')
                logger.error(traceback.format_exc())
                await asyncio.sleep(60)

    async def _repeat_once(self, rule_id):
        """Den gemerkten Beitrag einmal erneut senden."""
        session = get_session()
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule or not rule.enable_repeat or not rule.enable_rule:
                return
            if not rule.last_message_id:
                logger.info(f'Wiederholung: Regel {rule_id} hat noch keinen Beitrag zum Wiederholen')
                return

            client = self.bot_client if rule.use_bot else self.user_client
            target_id = int(rule.target_chat.telegram_chat_id)
            message_id = rule.last_message_id
        finally:
            session.close()

        entity = await self._resolve_target(client, target_id)
        if entity is None:
            logger.error(f'Wiederholung: Zielchat {target_id} nicht erreichbar')
            return

        original = await client.get_messages(entity, ids=message_id)
        if not original:
            logger.warning(
                f'Wiederholung: Beitrag {message_id} ist im Ziel nicht mehr vorhanden, '
                f'Regel {rule_id} wartet auf den nächsten weitergeleiteten Beitrag'
            )
            return

        # Als Kopie senden, nicht als Weiterleitung: kein "Weitergeleitet von"-Hinweis
        sent = await client.send_message(entity, message=original)
        logger.info(f'Wiederholung: Regel {rule_id} hat Beitrag {message_id} erneut gesendet')

        # Ab jetzt die frische Kopie wiederholen – so überlebt die Kette,
        # wenn ältere Beiträge gelöscht werden.
        if sent and getattr(sent, 'id', None):
            session = get_session()
            try:
                rule = session.query(ForwardRule).get(rule_id)
                if rule:
                    rule.last_message_id = sent.id
                    session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f'Wiederholung: neue Nachrichten-ID nicht gespeichert: {e}')
            finally:
                session.close()

    async def _resolve_target(self, client, target_id):
        """Zielchat auflösen – Kanäle brauchen oft das -100-Präfix."""
        candidates = [target_id]
        if not str(target_id).startswith('-100'):
            candidates.append(int(f'-100{abs(target_id)}'))
        if not str(target_id).startswith('-'):
            candidates.append(int(f'-{abs(target_id)}'))

        for candidate in candidates:
            try:
                return await client.get_entity(candidate)
            except Exception:
                continue
        return None

    async def start(self):
        """Aufgaben für alle Regeln mit eingeschalteter Wiederholung anlegen."""
        session = get_session()
        try:
            rules = session.query(ForwardRule).filter_by(enable_repeat=True).all()
            for rule in rules:
                await self.schedule_rule(rule)
            logger.info(f'Wiederholung: {len(rules)} Regel(n) eingeplant')
        except Exception as e:
            logger.error(f'Wiederholung: Start fehlgeschlagen: {e}')
            logger.error(traceback.format_exc())
        finally:
            session.close()

    def stop(self):
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
