"""Kleiner Zugriff auf den globalen Schlüssel-Wert-Speicher ``bot_config``.

Damit lassen sich Einstellungen wie der Vermietungstext im Bot ändern, ohne
die ``.env`` anzufassen oder neu zu starten.
"""

import logging

from models.models import get_session, BotConfig

logger = logging.getLogger(__name__)


def get_config(key, default=None):
    """Wert zu einem Schlüssel lesen (oder ``default``)."""
    session = get_session()
    try:
        row = session.query(BotConfig).get(key)
        return row.value if row and row.value is not None else default
    except Exception as e:
        logger.error(f'bot_config lesen fehlgeschlagen ({key}): {e}')
        return default
    finally:
        session.close()


def set_config(key, value):
    """Wert setzen (legt den Schlüssel bei Bedarf an)."""
    session = get_session()
    try:
        row = session.query(BotConfig).get(key)
        if row:
            row.value = value
        else:
            session.add(BotConfig(key=key, value=value))
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f'bot_config schreiben fehlgeschlagen ({key}): {e}')
        return False
    finally:
        session.close()
