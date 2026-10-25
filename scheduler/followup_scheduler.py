"""Follow-ups an Testkunden + Empfehlungsprämien (nur Main-Bot, MAIN_BOT=1).

Zeitpunkt zählt ab Anlage des Kunden-Bots (``ManagedContainer.created_at``):

* Tag 1          → „Läuft alles?"
* Tag 3          → „Fehlt dir was?" + Freund einladen
* 1 Tag vor Ende → Testphase endet, Abo im eigenen Bot abschließen
* nach Ablauf    → „Was hat gefehlt?" (nur wenn nicht gekauft)

Pro Kunde wird jede Stufe nur einmal geschickt (``followup_stage``). Kunden,
die vor Einführung schon existierten, stehen auf ``legacy`` und bekommen nichts.

Empfehlungen: Kauft ein geworbener Kunde zum ersten Mal, bekommt der Werber die
Hälfte der gekauften Tage in seinem Kunden-Bot gutgeschrieben.
"""

import asyncio
import logging
import os
import sqlite3
import traceback
from datetime import datetime, timedelta

from handlers.followup import build_stage_message
from handlers.subscription import PACKAGES, TRIAL_DAYS
from models.models import ManagedContainer, Referral, Subscription, get_session
from scheduler.cleanup_scheduler import CUSTOMERS_DIR, _admin_ids, _parse, _subscription_paid_until
from utils.i18n import t

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60 * 60  # stündlich

STAGE_ORDER = {None: 0, 'd1': 1, 'd3': 2, 'end': 3, 'lost': 4}
FINAL_STAGES = ('lost', 'paid', 'legacy')


def _today():
    return datetime.utcnow().date()


def _due_stage(days_old):
    if days_old >= TRIAL_DAYS + 1:
        return 'lost'
    if days_old >= TRIAL_DAYS - 1:
        return 'end'
    if days_old >= 3:
        return 'd3'
    if days_old >= 1:
        return 'd1'
    return None


def _customer_db(customer_id):
    return f'{CUSTOMERS_DIR}/customer-{customer_id}/db/forward.db'


def _customer_subscription(customer_id):
    """(paid_until, total_stars, trial_started_at) aus der DB des Kunden-Bots."""
    path = _customer_db(customer_id)
    if not os.path.exists(path):
        return None, 0, None
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            row = conn.execute(
                'SELECT paid_until, total_stars_paid, trial_started_at '
                'FROM subscription WHERE telegram_user_id = ?', (customer_id,)).fetchone()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f'Abo von Kunde {customer_id} nicht lesbar: {e}')
        return None, 0, None
    if not row:
        return None, 0, None
    return _parse(row[0]), int(row[1] or 0), _parse(row[2])


def _main_stars(customer_id):
    """Im Main-Bot bezahlte Stars (Pay-first-Weg)."""
    session = get_session()
    try:
        sub = session.query(Subscription).filter_by(telegram_user_id=int(customer_id)).first()
        return int(sub.total_stars_paid or 0) if sub else 0
    finally:
        session.close()


def _is_paid(customer_id):
    today = _today()
    paid, _, _ = _customer_subscription(customer_id)
    main_paid = _subscription_paid_until(customer_id)
    return any(p and p >= today for p in (paid, main_paid))


def _days_for_stars(stars):
    for pkg in PACKAGES:
        if pkg['stars'] == stars:
            return pkg['days']
    base = PACKAGES[0]
    return stars * base['days'] // base['stars']


def _credit_days(customer_id, days):
    """Tage im Kunden-Bot gutschreiben (ab Abo- bzw. Testende). True bei Erfolg."""
    path = _customer_db(customer_id)
    if not os.path.exists(path):
        return False
    today = _today()
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            row = conn.execute(
                'SELECT paid_until, trial_started_at FROM subscription WHERE telegram_user_id = ?',
                (customer_id,)).fetchone()
            paid = _parse(row[0]) if row else None
            trial_start = _parse(row[1]) if row else None
            trial_end = trial_start + timedelta(days=TRIAL_DAYS) if trial_start else None
            base = max(d for d in (today, paid, trial_end) if d)
            new_until = (base + timedelta(days=days)).isoformat()
            if row:
                conn.execute('UPDATE subscription SET paid_until = ?, last_reminder = NULL '
                             'WHERE telegram_user_id = ?', (new_until, customer_id))
            else:
                conn.execute('INSERT INTO subscription (telegram_user_id, trial_started_at, paid_until, '
                             'total_stars_paid) VALUES (?, ?, ?, 0)',
                             (customer_id, today.isoformat(), new_until))
            conn.commit()
        finally:
            conn.close()
        logger.info(f'Empfehlung: Kunde {customer_id} +{days} Tage bis {new_until}')
        return True
    except Exception as e:
        logger.error(f'Gutschrift für Kunde {customer_id} fehlgeschlagen: {e}')
        return False


async def _bot_link(customer_id):
    """Link zum Kunden-Bot aus dessen .env (BOT_TOKEN → getMe)."""
    from handlers.onboarding import _bot_username_from_token
    env_path = f'{CUSTOMERS_DIR}/customer-{customer_id}/.env'
    try:
        with open(env_path, encoding='utf-8') as f:
            tokens = [line.split('=', 1)[1].strip() for line in f if line.startswith('BOT_TOKEN=')]
    except Exception:
        return None
    if not tokens:
        return None
    username = await _bot_username_from_token(tokens[-1])
    return f'https://t.me/{username}' if username else None


class FollowupScheduler:
    def __init__(self, bot_client):
        self.bot_client = bot_client
        self._task = None
        self._stopped = False

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info('Follow-ups: Scheduler gestartet')

    def stop(self):
        self._stopped = True
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while not self._stopped:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f'Follow-ups: Fehler im Tick: {e}')
                logger.error(traceback.format_exc())
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _tick(self):
        await self._send_followups()
        await self._reward_referrals()

    async def _send_followups(self):
        today = _today()
        session = get_session()
        try:
            rows = session.query(ManagedContainer).filter_by(deleted_at=None).all()
            todo = [(r.customer_id, r.created_at, r.followup_stage) for r in rows
                    if r.followup_stage not in FINAL_STAGES]
        finally:
            session.close()

        for customer_id, created_at, stage in todo:
            created = _parse(created_at)
            if not created:
                continue
            due = _due_stage((today - created).days)
            if due is None or STAGE_ORDER[due] <= STAGE_ORDER[stage]:
                continue

            # Gekauft → keine Kauf-Erinnerungen mehr, Follow-ups beenden.
            if due in ('end', 'lost') and _is_paid(customer_id):
                self._set_stage(customer_id, 'paid')
                continue

            bot_link = await _bot_link(customer_id) if due == 'end' else None
            text, buttons = build_stage_message(due, bot_link)
            try:
                await self.bot_client.send_message(
                    customer_id, text, buttons=buttons, parse_mode='html', link_preview=False)
                logger.info(f'Follow-ups: {due} an {customer_id} verschickt')
            except Exception as e:
                # Trotzdem weiterzählen, sonst jede Stunde ein neuer Versuch.
                logger.warning(f'Follow-ups: {due} an {customer_id} fehlgeschlagen: {e}')
            self._set_stage(customer_id, due)

    def _set_stage(self, customer_id, stage):
        session = get_session()
        try:
            row = session.query(ManagedContainer).get(customer_id)
            if row:
                row.followup_stage = stage
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f'Follow-ups: Stufe für {customer_id} nicht gespeichert: {e}')
        finally:
            session.close()

    async def _reward_referrals(self):
        session = get_session()
        try:
            open_refs = [(r.referred_id, r.referrer_id)
                         for r in session.query(Referral).filter_by(rewarded_at=None).all()]
        finally:
            session.close()

        for referred_id, referrer_id in open_refs:
            _, stars, _ = _customer_subscription(referred_id)
            stars = max(stars, _main_stars(referred_id))
            if stars <= 0:
                continue  # noch nichts gekauft

            days = max(1, _days_for_stars(stars) // 2)
            ok = _credit_days(referrer_id, days)
            self._mark_rewarded(referred_id, days)

            if ok:
                try:
                    await self.bot_client.send_message(
                        referrer_id, t('ref.reward.user', days=days), parse_mode='html')
                except Exception as e:
                    logger.warning(f'Empfehlung: Werber {referrer_id} nicht erreichbar: {e}')
            status = t('ref.reward.ok') if ok else t('ref.reward.manual')
            for admin_id in _admin_ids():
                try:
                    await self.bot_client.send_message(
                        admin_id,
                        t('ref.reward.admin', referrer=referrer_id, referred=referred_id,
                          days=days, status=status),
                        parse_mode='html')
                except Exception as e:
                    logger.warning(f'Empfehlung: Admin-Meldung fehlgeschlagen: {e}')

    def _mark_rewarded(self, referred_id, days):
        session = get_session()
        try:
            row = session.query(Referral).get(referred_id)
            if row:
                row.rewarded_at = _today().isoformat()
                row.reward_days = days
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f'Empfehlung: Prämie für {referred_id} nicht gespeichert: {e}')
        finally:
            session.close()
