"""Proxy-Konfiguration für die Telegram-Verbindung.

Damit lässt sich jede Instanz über eine eigene Ausgangs-IP betreiben – bei
mehreren Kundeninstanzen auf demselben Server der übliche Weg.

Konfiguriert wird über eine einzige Umgebungsvariable::

    PROXY_URL=socks5://benutzer:passwort@1.2.3.4:1080
    PROXY_URL=http://1.2.3.4:8080
    PROXY_URL=mtproxy://ee1603...secret@1.2.3.4:443

Wichtig: Gemeint ist eine **feste** Adresse je Instanz, kein rotierender
Proxy. Telegram bindet eine Anmeldung an einen stabilen Netzkontext; wechselnde
IPs führen zu Rückfragen, abgemeldeten Sitzungen und gesperrten Konten.
"""

import logging
import os
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)

# Von python-socks unterstützte Typen (Telethon nimmt sie als Dict entgegen)
SOCKS_TYPES = {
    'socks5': 'socks5',
    'socks5h': 'socks5',
    'socks4': 'socks4',
    'socks4a': 'socks4',
    'http': 'http',
    'https': 'http',
}

MTPROXY_SCHEMES = ('mtproxy', 'mtproto')


def describe(url):
    """Proxy-Angabe ohne Zugangsdaten beschreiben – für Logausgaben."""
    if not url:
        return 'kein Proxy'
    parsed = urlparse(url)
    return f'{parsed.scheme}://{parsed.hostname}:{parsed.port}'


def build_proxy(url=None):
    """Proxy-Einstellungen für ``TelegramClient`` bauen.

    Returns:
        (proxy, connection): ``proxy`` ist ein Dict (SOCKS/HTTP) oder ein Tupel
        (MTProxy); ``connection`` ist die passende Telethon-Verbindungsklasse
        oder None. Ohne Konfiguration ``(None, None)``.

    Raises:
        ValueError: bei unbrauchbarer Angabe – lieber sofort abbrechen, als
        unbemerkt mit der Server-IP zu arbeiten.
    """
    url = url if url is not None else os.getenv('PROXY_URL', '')
    url = (url or '').strip()
    if not url:
        return None, None

    parsed = urlparse(url)
    scheme = (parsed.scheme or '').lower()

    if not parsed.hostname or not parsed.port:
        raise ValueError(f'PROXY_URL braucht Host und Port: {describe(url)}')

    if scheme in MTPROXY_SCHEMES:
        # Beim MTProxy steht das Geheimnis an der Stelle des Benutzernamens
        secret = parsed.username or parsed.password
        if not secret:
            raise ValueError('MTProxy braucht ein Secret: mtproxy://<secret>@host:port')

        from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate
        logger.info(f'Telegram-Verbindung über MTProxy {describe(url)}')
        return (parsed.hostname, parsed.port, unquote(secret)), ConnectionTcpMTProxyRandomizedIntermediate

    if scheme not in SOCKS_TYPES:
        raise ValueError(
            f'PROXY_URL kennt das Schema "{scheme}" nicht. '
            'Erlaubt: socks5, socks4, http, mtproxy'
        )

    proxy = {
        'proxy_type': SOCKS_TYPES[scheme],
        'addr': parsed.hostname,
        'port': parsed.port,
        'rdns': True,
    }
    if parsed.username:
        proxy['username'] = unquote(parsed.username)
    if parsed.password:
        proxy['password'] = unquote(parsed.password)

    logger.info(f'Telegram-Verbindung über Proxy {describe(url)}')
    return proxy, None
