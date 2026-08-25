"""Erinnerungen an das Abo-Ende schicken.

Läuft einmal täglich und prüft, wie viele Tage der Kunde noch hat:

* 3 Tage vorher  → freundliche Erinnerung
* 1 Tag vorher   → letzte Erinnerung
* abgelaufen     → Hinweis, dass die Weiterleitung pausiert

Jede Erinnerung wird nur einmal je Ablauf-Datum verschickt
(``Subscription.last_reminder``).
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta

from handlers.subscription import is_admin_user, mark_reminder
from models.models import Subscription, get_session
from utils.i18n import t

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60 * 60 * 6  # alle 6 Stunden schauen


class SubscriptionScheduler:
    def __init__(self, bot_client):
        self.bot_client = bot_client
        self._task = None
        self._stopped = False

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info('Abo-Erinnerungen: Scheduler gestartet')

    def stop(self):
        self._stopped = True
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while not self._stopped:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f'Abo-Erinnerungen: Fehler im Tick: {e}')
                logger.error(traceback.format_exc())
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _tick(self):
        today = datetime.utcnow().date()
        session = get_session()
        try:
            subs = session.query(Subscription).all()
        finally:
            session.close()

        for sub in subs:
            if is_admin_user(sub.telegram_user_id):
                continue

            try:
                paid = datetime.fromisoformat(sub.paid_until).date() if sub.paid_until else None
            except Exception:
                paid = None
            if paid is None:
                continue

            days_left = (paid - today).days

            if days_left == 3 and sub.last_reminder != '3d':
                await self._send(sub.telegram_user_id, t('sub.remind.3d'), '3d')
            elif days_left == 1 and sub.last_reminder not in ('1d', 'expired'):
                await self._send(sub.telegram_user_id, t('sub.remind.1d'), '1d')
            elif days_left < 0 and sub.last_reminder != 'expired':
                await self._send(sub.telegram_user_id, t('sub.remind.expired'), 'expired')

    async def _send(self, user_id, text, tag):
        try:
            from telethon import Button
            await self.bot_client.send_message(
                int(user_id),
                text,
                parse_mode='html',
                buttons=[[Button.inline(t('menu.btn.billing'), 'sub_billing')]],
            )
            mark_reminder(user_id, tag)
            logger.info(f'Abo-Erinnerungen: {tag} an {user_id} verschickt')
        except Exception as e:
            logger.warning(f'Abo-Erinnerungen: {tag} an {user_id} fehlgeschlagen: {e}')
