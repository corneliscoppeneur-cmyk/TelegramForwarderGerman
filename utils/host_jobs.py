"""Aufträge an den VPS-Host übergeben (Kunden-Bot anlegen/löschen).

Der Bot läuft im Container und hat bewusst keinen Docker-Zugriff. Stattdessen
legt er einen Auftrag als Datei in ``HOST_JOBS_DIR`` ab. Der Dienst
``host_job_runner.py`` auf dem Host führt ihn aus und schreibt das Ergebnis
zurück. Erlaubt sind nur die Aktionen ``deploy`` und ``delete``.
"""
import asyncio
import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)

HOST_JOBS_DIR = os.getenv('HOST_JOBS_DIR', '/app/hostjobs')
POLL_SECONDS = 2


def host_jobs_available():
    return os.path.isdir(HOST_JOBS_DIR)


async def run_host_job(action, args, timeout):
    """Auftrag einreichen und auf das Ergebnis warten. Gibt ``(ok, output)`` zurück."""
    job_id = uuid.uuid4().hex
    job_path = os.path.join(HOST_JOBS_DIR, f'{job_id}.job')
    done_path = os.path.join(HOST_JOBS_DIR, f'{job_id}.done')
    tmp_path = job_path + '.tmp'

    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump({'action': action, 'args': [str(a) for a in args]}, f)
        os.replace(tmp_path, job_path)
    except OSError as e:
        logger.error(f'Host-Auftrag konnte nicht angelegt werden: {e}')
        return False, f'Host-Auftrag konnte nicht angelegt werden: {e}'

    waited = 0
    while waited < timeout:
        if os.path.exists(done_path):
            try:
                with open(done_path) as f:
                    result = json.load(f)
            finally:
                try:
                    os.remove(done_path)
                except OSError:
                    pass
            return bool(result.get('ok')), result.get('output', '')
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS

    # Nicht abgeholt: Auftrag zurückziehen, damit er nicht später noch läuft
    try:
        os.remove(job_path)
    except OSError:
        pass
    return False, f'Keine Antwort vom Host-Dienst nach {timeout} s (läuft host_job_runner?)'
