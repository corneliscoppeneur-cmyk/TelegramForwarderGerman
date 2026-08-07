import logging

from filters.base_filter import BaseFilter
from models.models import get_session, ForwardRule

logger = logging.getLogger(__name__)


class RepeatFilter(BaseFilter):
    """Merkt sich den zuletzt im Zielchat erzeugten Beitrag.

    Die Wiederholung in ``scheduler/repeat_scheduler.py`` schickt genau diesen
    Beitrag in festem Abstand erneut. Läuft nach dem Versand und ändert am
    Nachrichtenfluss nichts.
    """

    async def _process(self, context):
        rule = context.rule

        if not getattr(rule, 'enable_repeat', False):
            return True

        if not context.forwarded_messages:
            return True

        last = context.forwarded_messages[-1]
        message_id = getattr(last, 'id', None)
        if not message_id:
            return True

        session = get_session()
        try:
            db_rule = session.query(ForwardRule).get(rule.id)
            if db_rule:
                db_rule.last_message_id = message_id
                session.commit()
                logger.info(f'Wiederholung: Regel {rule.id} merkt sich Nachricht {message_id}')
        except Exception as e:
            session.rollback()
            logger.error(f'Wiederholung: Nachricht konnte nicht gemerkt werden: {e}')
        finally:
            session.close()

        return True
