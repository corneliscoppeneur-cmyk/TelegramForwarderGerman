#!/usr/bin/env python3
"""Smoke-Test für HTML-Widgets (Bot API 10.4).

Schickt eine kleine Test-Karte per ``sendWidget`` in den Privatchat mit dem Bot.
Der Empfänger muss den Bot schon einmal gestartet haben (/start).

Aufruf (im Container oder lokal, BOT_TOKEN aus der Umgebung/.env):
    python scripts/widget_smoke_test.py <chat_id>

Nur Standardbibliothek, damit es überall läuft. Der Token wird nie ausgegeben.
"""
import json
import os
import sys
import urllib.error
import urllib.request
import zlib

HTML = """<style>
body{margin:0;padding:14px 14px 16px}
h3{margin:0 0 4px;font-size:17px}
.meta{color:var(--tg-theme-hint-color);font-size:13px;margin-bottom:10px}
.bar{height:8px;border-radius:4px;background:var(--tg-theme-secondary-bg-color);overflow:hidden;margin-bottom:12px}
.fill{height:100%;width:62%;background:var(--tg-theme-button-color)}
.row{display:flex;gap:8px}
button{flex:1}
</style>
<h3>🧪 Widget-Test</h3>
<div class="meta">Bot API 10.4 · gerendert in deiner Chat-Optik · Schema: <span id="s">…</span></div>
<div class="bar"><div class="fill"></div></div>
<div class="row">
  <button onclick="TelegramWidget.openTelegramLink('https://t.me/{bot}?start=menu_rules')">Bot öffnen</button>
  <button onclick="TelegramWidget.HapticFeedback.impactOccurred('medium')">Haptik</button>
</div>
<script>
document.getElementById('s').textContent = TelegramWidget.colorScheme;
TelegramWidget.onEvent('themeChanged', function(){document.getElementById('s').textContent = TelegramWidget.colorScheme;});
TelegramWidget.ready();
</script>"""

CAPTION = ('🧪 <b>Widget-Test</b>\n'
           'Siehst du nur diesen Text, unterstützt dein Telegram-Client noch keine Widgets.')


def _load_env_token():
    token = os.getenv('BOT_TOKEN')
    if token:
        return token
    for path in ('.env', os.path.join(os.path.dirname(__file__), '..', '.env')):
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    if line.startswith('BOT_TOKEN='):
                        token = line.split('=', 1)[1].strip()
        except OSError:
            pass
    return token


def call(token, method, **params):
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=json.dumps(params).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8', errors='replace'))


def main():
    if len(sys.argv) != 2:
        print('Nutzung: widget_smoke_test.py <chat_id>')
        return 2
    chat_id = sys.argv[1]
    token = _load_env_token()
    if not token:
        print('BOT_TOKEN fehlt (Umgebung oder .env)')
        return 2

    me = call(token, 'getMe')
    if not me.get('ok'):
        print('getMe fehlgeschlagen:', me.get('description'))
        return 1
    bot = me['result']['username']

    html = HTML.replace('{bot}', bot)
    raw = html.encode('utf-8')
    packed = len(zlib.compress(raw, 9))
    print(f'Bot @{bot} · HTML {len(raw)} Bytes · zlib {packed} Bytes (Limit 32768 / 4096)')

    res = call(token, 'sendWidget', chat_id=chat_id, html=html, caption=CAPTION, parse_mode='HTML')
    if res.get('ok'):
        msg = res['result']
        print('OK – Nachricht', msg.get('message_id'), '· widget-Feld vorhanden:', 'widget' in msg)
        return 0
    print('FEHLER', res.get('error_code'), res.get('description'))
    return 1


if __name__ == '__main__':
    sys.exit(main())
