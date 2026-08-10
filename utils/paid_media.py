"""Bezahlte Medien (Telegram Stars) lesen und weitergeben.

Ein bezahlter Beitrag trägt kein gewöhnliches ``photo``/``document``, sondern
``MessageMediaPaidMedia`` mit einer Liste ``extended_media``. Darin steht je
Eintrag entweder

* ``MessageExtendedMedia`` – der Beitrag wurde gekauft (oder das Konto gehört
  zum Kanal), die echte Datei liegt vor, oder
* ``MessageExtendedMediaPreview`` – nur die verpixelte Vorschau. Ohne Kauf gibt
  Telegram die Datei nicht heraus; daran lässt sich nichts umgehen.

Beim Weitergeben wird nicht die Originaldatei verlinkt, sondern neu
hochgeladen: Datei-Referenzen gelten nur für das Konto, das sie bekommen hat –
der Bot kann damit nichts anfangen.
"""

import logging
import os
import random

from telethon.tl.functions.messages import SendMediaRequest
from telethon.tl.types import (
    DocumentAttributeFilename,
    InputMediaPaidMedia,
    InputMediaUploadedDocument,
    InputMediaUploadedPhoto,
    MessageExtendedMedia,
    MessageMediaDocument,
    MessageMediaPaidMedia,
    MessageMediaPhoto,
)

logger = logging.getLogger(__name__)

# Telegram erlaubt höchstens zehn Dateien je bezahltem Beitrag
MAX_ITEMS = 10


def get_paid_media(message):
    """``MessageMediaPaidMedia`` der Nachricht oder None."""
    media = getattr(message, 'media', None)
    return media if isinstance(media, MessageMediaPaidMedia) else None


def accessible_items(paid):
    """Die Einträge, deren Datei wirklich vorliegt."""
    if not paid:
        return []
    return [
        item for item in (paid.extended_media or [])
        if isinstance(item, MessageExtendedMedia) and item.media is not None
    ]


def locked_count(paid):
    """Wie viele Einträge nur als Vorschau vorliegen."""
    if not paid:
        return 0
    return len(paid.extended_media or []) - len(accessible_items(paid))


def media_size(paid):
    """Gesamtgröße der zugänglichen Dateien in Byte."""
    total = 0
    for item in accessible_items(paid):
        inner = item.media
        doc = getattr(inner, 'document', None)
        if doc is not None:
            total += getattr(doc, 'size', 0) or 0
            continue
        photo = getattr(inner, 'photo', None)
        if photo is not None and getattr(photo, 'sizes', None):
            total += max((getattr(s, 'size', 0) or 0) for s in photo.sizes)
    return total


async def download(client, paid, temp_dir):
    """Zugängliche Dateien herunterladen.

    Returns:
        Liste von ``(pfad, innere_media)`` – die innere Media wird später
        gebraucht, um Dateityp und Eigenschaften zu übernehmen.
    """
    downloaded = []
    for index, item in enumerate(accessible_items(paid)):
        try:
            path = await client.download_media(item.media, temp_dir)
            if path:
                downloaded.append((path, item.media))
                logger.info(f'Bezahltes Medium {index + 1} geladen: {path}')
        except Exception as e:
            logger.error(f'Bezahltes Medium {index + 1} konnte nicht geladen werden: {e}')
    return downloaded


def _build_input(uploaded, inner):
    """Hochgeladene Datei in die passende Telegram-Struktur verpacken."""
    if isinstance(inner, MessageMediaPhoto) or getattr(inner, 'photo', None) is not None:
        return InputMediaUploadedPhoto(file=uploaded)

    doc = getattr(inner, 'document', None)
    mime = getattr(doc, 'mime_type', None) or 'application/octet-stream'
    attributes = list(getattr(doc, 'attributes', None) or [])
    if not any(isinstance(a, DocumentAttributeFilename) for a in attributes):
        attributes.append(DocumentAttributeFilename(file_name='datei'))

    return InputMediaUploadedDocument(file=uploaded, mime_type=mime, attributes=attributes)


async def send(client, entity, downloaded, caption, parse_mode, stars):
    """Dateien als bezahlten Beitrag senden.

    Returns:
        Die gesendete Nachricht oder None.

    Raises:
        Weiterleitung der Telegram-Fehler – der Aufrufer entscheidet, was er
        dem Nutzer zeigt (bezahlte Beiträge gehen nur in Kanäle).
    """
    if not downloaded:
        return None

    inputs = []
    for path, inner in downloaded[:MAX_ITEMS]:
        uploaded = await client.upload_file(path)
        inputs.append(_build_input(uploaded, inner))

    text, entities = '', None
    if caption:
        try:
            text, entities = await client._parse_message_text(caption, parse_mode)
        except Exception as e:
            logger.warning(f'Beschriftung konnte nicht formatiert werden, sende sie roh: {e}')
            text = caption

    result = await client(SendMediaRequest(
        peer=entity,
        media=InputMediaPaidMedia(stars_amount=int(stars), extended_media=inputs),
        message=text,
        entities=entities,
        random_id=random.randrange(-(2 ** 63), 2 ** 63),
    ))

    logger.info(f'Bezahlter Beitrag mit {len(inputs)} Datei(en) für {stars} Sterne gesendet')
    return client._get_response_message(None, result, entity)


def cleanup(downloaded):
    """Heruntergeladene Dateien entfernen."""
    for path, _ in downloaded:
        try:
            os.remove(path)
        except Exception as e:
            logger.warning(f'Temporäre Datei {path} blieb liegen: {e}')
