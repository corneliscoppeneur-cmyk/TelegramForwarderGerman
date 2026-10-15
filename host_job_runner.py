#!/usr/bin/env python3
"""Host-Dienst: führt Aufträge des Bot-Containers aus (Kunden-Bot anlegen/löschen).

Der Bot schreibt ``<id>.job`` nach ``hostjobs/``. Dieser Dienst läuft direkt
auf dem VPS (systemd, siehe ``forwarder-hostjobs.service``), führt nur die
erlaubten Skripte mit geprüften Argumenten aus und schreibt ``<id>.done``.
"""
import json
import os
import re
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.getenv('HOST_JOBS_DIR', os.path.join(BASE_DIR, 'hostjobs'))

CUSTOMER_ID_RE = re.compile(r'^-?\d{1,20}$')
BOT_TOKEN_RE = re.compile(r'^\d{5,20}:[A-Za-z0-9_-]{30,60}$')

# Aktion -> (Skript, Prüfregeln der Argumente, Timeout in Sekunden)
ACTIONS = {
    'deploy': ('deploy_customer_bot.sh', [CUSTOMER_ID_RE, BOT_TOKEN_RE], 900),
    'delete': ('delete_customer_bot.sh', [CUSTOMER_ID_RE], 300),
}


def log(msg):
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}', flush=True)


def write_result(job_id, ok, output):
    tmp = os.path.join(JOBS_DIR, f'{job_id}.done.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'ok': ok, 'output': output[-4000:]}, f)
    os.replace(tmp, os.path.join(JOBS_DIR, f'{job_id}.done'))


def run_job(job_id, path):
    try:
        with open(path) as f:
            job = json.load(f)
    except (OSError, ValueError) as e:
        write_result(job_id, False, f'Ungültiger Auftrag: {e}')
        return

    action = job.get('action')
    args = job.get('args') or []
    if action not in ACTIONS:
        write_result(job_id, False, f'Unbekannte Aktion: {action!r}')
        return

    script, rules, timeout = ACTIONS[action]
    if len(args) != len(rules) or not all(isinstance(a, str) and r.match(a) for a, r in zip(args, rules)):
        write_result(job_id, False, 'Ungültige Argumente')
        return

    # Kunden-ID ins Log, Token nie
    log(f'Auftrag {job_id}: {action} Kunde {args[0]}')
    try:
        proc = subprocess.run(
            ['bash', os.path.join(BASE_DIR, script), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, cwd=BASE_DIR,
        )
        output = proc.stdout.decode('utf-8', errors='replace')
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        ok, output = False, f'Timeout nach {timeout} s'
    log(f'Auftrag {job_id}: {"OK" if ok else "FEHLER"}')
    write_result(job_id, ok, output)


def main():
    os.makedirs(JOBS_DIR, mode=0o700, exist_ok=True)
    os.chmod(JOBS_DIR, 0o700)
    log(f'Host-Dienst gestartet, Ordner: {JOBS_DIR}')
    while True:
        for name in sorted(os.listdir(JOBS_DIR)):
            if not name.endswith('.job'):
                continue
            job_id = name[:-4]
            src = os.path.join(JOBS_DIR, name)
            running = os.path.join(JOBS_DIR, f'{job_id}.running')
            try:
                os.replace(src, running)  # Auftrag übernehmen
            except OSError:
                continue
            try:
                run_job(job_id, running)
            except Exception as e:  # Dienst darf nicht abstürzen
                write_result(job_id, False, f'Interner Fehler: {e}')
            finally:
                try:
                    os.remove(running)
                except OSError:
                    pass
        time.sleep(2)


if __name__ == '__main__':
    sys.exit(main())
