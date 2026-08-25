"""Abo-Verwaltung für den Kunden dieses Containers.

Ein Container = ein Kunde (per ``USER_ID`` in der ``.env``).
Der Admin (``ADMIN_USER_ID`` bzw. ``USER_ID`` wenn Admin=Kunde) ist immer
freigeschaltet – der Kunde hat 5 Tage Testphase und danach ein bezahltes Abo.

Zahlung läuft über Telegram Stars, siehe ``handlers/button/payment.py``.
"""

import logging
import os
from datetime import datetime, timedelta

from models.models import Subscription, get_session

logger = logging.getLogger(__name__)

TRIAL_DAYS = 5

# Preise: Stars → Tage
PACKAGES = [
    {'stars': 500, 'days': 30, 'label_key': 'sub.pkg.30d'},
    {'stars': 1350, 'days': 90, 'label_key': 'sub.pkg.90d'},
    {'stars': 5000, 'days': 365, 'label_key': 'sub.pkg.365d'},
]


def _today():
    return datetime.utcnow().date()


def _parse(iso_date):
    if not iso_date:
        return None
    try:
        return datetime.fromisoformat(iso_date).date()
    except Exception:
        return None


def is_admin_user(user_id):
    """Ist die Telegram-User-ID der Betreiber (Admin, dauerhaft freigeschaltet)?

    Wichtig: prüft **nicht** ``USER_ID`` – die ``USER_ID`` gehört dem Kunden
    dieses Containers und soll normal Abo-Regeln unterliegen. Nur wer in
    ``ADMIN_USER_ID`` (kommagetrennt möglich) steht, ist Betreiber und sieht
    keinen Abo-Button.
    """
    if not user_id:
        return False
    raw = os.getenv('ADMIN_USER_ID', '')
    if not raw:
        return False
    admin_ids = set()
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            admin_ids.add(int(part))
        except ValueError:
            pass
    return int(user_id) in admin_ids


def _load(session, user_id):
    return session.query(Subscription).filter_by(telegram_user_id=int(user_id)).first()


def ensure_trial(user_id):
    """Beim ersten Kontakt Testphase anlegen; danach ein No-op."""
    if is_admin_user(user_id):
        return
    session = get_session()
    try:
        sub = _load(session, user_id)
        if sub is None:
            sub = Subscription(
                telegram_user_id=int(user_id),
                trial_started_at=_today().isoformat(),
            )
            session.add(sub)
            session.commit()
            logger.info(f'Abo: Testphase gestartet für {user_id}')
    except Exception as e:
        session.rollback()
        logger.error(f'Abo: Testphase konnte nicht angelegt werden: {e}')
    finally:
        session.close()


def is_active(user_id):
    """True wenn Testphase noch läuft oder bezahlt."""
    if is_admin_user(user_id):
        return True
    session = get_session()
    try:
        sub = _load(session, user_id)
        if sub is None:
            return False
        today = _today()
        paid = _parse(sub.paid_until)
        if paid and paid >= today:
            return True
        trial_start = _parse(sub.trial_started_at)
        if trial_start:
            trial_end = trial_start + timedelta(days=TRIAL_DAYS)
            if today <= trial_end:
                return True
        return False
    finally:
        session.close()


def status(user_id):
    """Details für die UI: (state, days_left, paid_until, trial_end).

    state ∈ {'admin', 'trial', 'paid', 'expired', 'unknown'}
    """
    if is_admin_user(user_id):
        return {'state': 'admin', 'days_left': None, 'paid_until': None, 'trial_end': None}

    session = get_session()
    try:
        sub = _load(session, user_id)
        if sub is None:
            return {'state': 'unknown', 'days_left': None, 'paid_until': None, 'trial_end': None}

        today = _today()
        paid = _parse(sub.paid_until)
        trial_start = _parse(sub.trial_started_at)
        trial_end = (trial_start + timedelta(days=TRIAL_DAYS)) if trial_start else None

        if paid and paid >= today:
            return {
                'state': 'paid',
                'days_left': (paid - today).days,
                'paid_until': paid.isoformat(),
                'trial_end': trial_end.isoformat() if trial_end else None,
            }
        if trial_end and today <= trial_end:
            return {
                'state': 'trial',
                'days_left': (trial_end - today).days,
                'paid_until': None,
                'trial_end': trial_end.isoformat(),
            }
        return {
            'state': 'expired',
            'days_left': 0,
            'paid_until': paid.isoformat() if paid else None,
            'trial_end': trial_end.isoformat() if trial_end else None,
        }
    finally:
        session.close()


def activate(user_id, days, stars_paid=0):
    """Abo verlängern (oder neu setzen). Ab dem größeren von heute/paid_until."""
    if is_admin_user(user_id):
        return
    session = get_session()
    try:
        sub = _load(session, user_id)
        if sub is None:
            sub = Subscription(telegram_user_id=int(user_id), trial_started_at=_today().isoformat())
            session.add(sub)
            session.flush()

        today = _today()
        current = _parse(sub.paid_until)
        base = current if (current and current > today) else today
        sub.paid_until = (base + timedelta(days=int(days))).isoformat()
        sub.last_reminder = None
        sub.total_stars_paid = int(sub.total_stars_paid or 0) + int(stars_paid or 0)
        session.commit()
        logger.info(f'Abo: {user_id} bis {sub.paid_until} verlängert (+{days} Tage, {stars_paid} Stars)')
    except Exception as e:
        session.rollback()
        logger.error(f'Abo: Verlängerung fehlgeschlagen: {e}')
    finally:
        session.close()


def mark_reminder(user_id, tag):
    """Merken, welche Erinnerung schon geschickt wurde ('3d','1d','expired')."""
    session = get_session()
    try:
        sub = _load(session, user_id)
        if sub is None:
            return
        sub.last_reminder = tag
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f'Abo: Erinnerung {tag} konnte nicht gespeichert werden: {e}')
    finally:
        session.close()
