"""Automatischer Aufräumdienst für inaktive Kunden-Container.

Regel:

* 11 Tage nach Anlage ohne Aktivität → Warnung an den Admin
  (Testphase = 5 Tage + Nachfrist = 7 Tage = 12 Tage; Warnung 24h vorher)
* 12 Tage nach Anlage ohne Aktivität → Container stoppen + Ordner löschen

„Aktivität" bedeutet eines von:

* Datenbank des Kunden-Containers enthält mindestens eine Weiterleitungsregel
* Session-Datei ``sessions/user.session`` ist größer als ein leerer Neu-Login
* Abo ist bezahlt (paid_until in der Zukunft)

Ein ``/keep <id>``-Befehl setzt ``kept_until`` und schützt den Container so
lange davor.
"""

import asyncio
import logging
import os
import sqlite3
import traceback
from datetime import datetime, timedelta

from telethon import Button

from handlers.subscription import is_admin_user
from models.models import ManagedContainer, get_session
from utils.i18n import t

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60 * 60 * 6   # alle 6h prüfen
TRIAL_PLUS_GRACE_DAYS = 12             # 5 Tage Trial + 7 Tage Nachfrist
WARN_BEFORE_DAYS = 1                    # 24h vor Löschung warnen

DELETE_SCRIPT = os.getenv('DELETE_SCRIPT_PATH', '/root/delete_customer_bot.sh')
CUSTOMERS_DIR = os.getenv('CUSTOMERS_DIR', '/root/customer_bots')


def _today():
    return datetime.utcnow().date()


def _parse(iso_date):
    if not iso_date:
        return None
    try:
        return datetime.fromisoformat(iso_date).date()
    except Exception:
        return None


def _is_active_customer(customer_id):
    """Prüft, ob der Kunden-Container Aktivität zeigt."""
    path = f'{CUSTOMERS_DIR}/customer-{customer_id}'

    # 1) DB enthält Regeln?
    db_path = f'{path}/db/forward.db'
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path, timeout=2)
            try:
                cur = conn.execute('SELECT COUNT(*) FROM forward_rules')
                count = cur.fetchone()[0]
                if count and count > 0:
                    return True
                # Abo bezahlt?
                try:
                    cur = conn.execute(
                        'SELECT paid_until FROM subscription WHERE telegram_user_id = ?',
                        (customer_id,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        paid = _parse(row[0])
                        if paid and paid >= _today():
                            return True
                except sqlite3.OperationalError:
                    pass  # subscription-Tabelle existiert evtl. nicht
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f'Aktivitätsprüfung DB {customer_id} fehlgeschlagen: {e}')

    # 2) User-Session mit angemeldetem Konto?
    session_path = f'{path}/sessions/user.session'
    if os.path.exists(session_path):
        try:
            # Eine leere/neue Session ist ~28 KB; angemeldete Sessions sind größer
            size = os.path.getsize(session_path)
            if size > 40_000:
                return True
        except Exception:
            pass

    return False


class CleanupScheduler:
    def __init__(self, bot_client):
        self.bot_client = bot_client
        self._task = None
        self._stopped = False

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info('Container-Aufräumdienst: gestartet')

    def stop(self):
        self._stopped = True
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while not self._stopped:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f'Container-Aufräumdienst: Fehler im Tick: {e}')
                logger.error(traceback.format_exc())
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _tick(self):
        today = _today()
        session = get_session()
        try:
            rows = session.query(ManagedContainer).filter_by(deleted_at=None).all()
        finally:
            session.close()

        for row in rows:
            created = _parse(row.created_at)
            if not created:
                continue

            days_old = (today - created).days
            keep = _parse(row.kept_until)
            if keep and keep >= today:
                continue  # ausdrücklich vom Admin behalten

            if _is_active_customer(row.customer_id):
                continue  # aktiver Kunde – nichts tun

            if days_old >= TRIAL_PLUS_GRACE_DAYS:
                await self._delete(row.customer_id, row.container_name)
            elif days_old >= TRIAL_PLUS_GRACE_DAYS - WARN_BEFORE_DAYS and not row.warned_at:
                await self._warn(row.customer_id, row.container_name)

    async def _warn(self, customer_id, container_name):
        admins = _admin_ids()
        for admin_id in admins:
            try:
                await self.bot_client.send_message(
                    admin_id,
                    t('cleanup.warn', id=customer_id, name=container_name),
                    parse_mode='html',
                )
            except Exception as e:
                logger.warning(f'Cleanup-Warnung an {admin_id} fehlgeschlagen: {e}')

        session = get_session()
        try:
            row = session.query(ManagedContainer).get(customer_id)
            if row:
                row.warned_at = _today().isoformat()
                session.commit()
        finally:
            session.close()

    async def _delete(self, customer_id, container_name):
        ok, output = await _run_delete(customer_id)

        session = get_session()
        try:
            row = session.query(ManagedContainer).get(customer_id)
            if row:
                if ok:
                    row.deleted_at = _today().isoformat()
                session.commit()
        finally:
            session.close()

        admins = _admin_ids()
        for admin_id in admins:
            try:
                if ok:
                    await self.bot_client.send_message(
                        admin_id,
                        t('cleanup.deleted', id=customer_id, name=container_name),
                        parse_mode='html',
                    )
                else:
                    await self.bot_client.send_message(
                        admin_id,
                        t('cleanup.delete_failed', id=customer_id, output=output[-800:]),
                        parse_mode='html',
                    )
            except Exception as e:
                logger.warning(f'Cleanup-Meldung an {admin_id} fehlgeschlagen: {e}')


def _admin_ids():
    raw = os.getenv('ADMIN_USER_ID', '')
    ids = set()
    for part in raw.split(','):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                pass
    return ids


async def _run_delete(customer_id):
    if not os.path.exists(DELETE_SCRIPT):
        return False, f'Delete-Skript nicht gefunden: {DELETE_SCRIPT}'
    try:
        proc = await asyncio.create_subprocess_exec(
            'bash', DELETE_SCRIPT, str(customer_id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            return False, 'Delete-Timeout (>2 Minuten)'
        output = (stdout or b'').decode('utf-8', errors='replace')
        return proc.returncode == 0, output
    except Exception as e:
        logger.error(f'Delete fehlgeschlagen: {e}')
        return False, str(e)
