#!/usr/bin/env bash
# Neuen Kunden-Container anlegen und starten.
#
# Aufruf:
#   deploy_customer_bot.sh <kunden_id> <bot_token>
#
# Voraussetzung: Repo liegt unter $TEMPLATE_DIR (Standard: /root/TelegramForwarderGerman).
# Neue Kunden landen in $CUSTOMERS_DIR/customer-<id>/ (Standard: /root/customer_bots).
# API_ID/API_HASH werden aus $TEMPLATE_DIR/.env kopiert (bleiben gleich für alle Kunden;
# das entspricht den offiziellen Telegram-Empfehlungen, mehrere Bots teilen dieselbe App).

set -eEuo pipefail

CUSTOMER_ID="${1:-}"
BOT_TOKEN="${2:-}"

TEMPLATE_DIR="${TEMPLATE_DIR:-/root/TelegramForwarderGerman}"
CUSTOMERS_DIR="${CUSTOMERS_DIR:-/root/customer_bots}"
BRANCH="${DEPLOY_BRANCH:-feature/button-ux}"

if [[ -z "$CUSTOMER_ID" || -z "$BOT_TOKEN" ]]; then
  echo "Nutzung: $0 <kunden_id> <bot_token>" >&2
  exit 2
fi

if ! [[ "$CUSTOMER_ID" =~ ^-?[0-9]+$ ]]; then
  echo "Fehler: kunden_id muss eine Zahl sein" >&2
  exit 2
fi

TARGET_DIR="$CUSTOMERS_DIR/customer-$CUSTOMER_ID"
CONTAINER_NAME="telegram-forwarder-customer-$CUSTOMER_ID"

echo "==> Ziel: $TARGET_DIR"
echo "==> Container: $CONTAINER_NAME"

if [[ -d "$TARGET_DIR" ]]; then
  echo "!! Ordner existiert bereits – bitte manuell prüfen und ggf. löschen." >&2
  exit 3
fi

# Werte aus dem Template holen (API-Credentials, ADMIN_USER_ID)
if [[ ! -f "$TEMPLATE_DIR/.env" ]]; then
  echo "!! Template-.env nicht gefunden: $TEMPLATE_DIR/.env" >&2
  exit 4
fi

# Letzten Wert je Key gewinnen lassen (kompatibel zu python-dotenv)
get_env() {
  local key="$1"
  grep -E "^${key}=" "$TEMPLATE_DIR/.env" | tail -n 1 | cut -d= -f2-
}

API_ID="$(get_env API_ID)"
API_HASH="$(get_env API_HASH)"
ADMIN_USER_ID="$(get_env ADMIN_USER_ID)"

if [[ -z "$API_ID" || -z "$API_HASH" ]]; then
  echo "!! API_ID / API_HASH fehlt in $TEMPLATE_DIR/.env" >&2
  exit 5
fi

echo "==> Clone Repo (Branch: $BRANCH)"
mkdir -p "$CUSTOMERS_DIR"
git clone --depth 1 --branch "$BRANCH" "$TEMPLATE_DIR" "$TARGET_DIR" >/dev/null

echo "==> .env schreiben"
cat > "$TARGET_DIR/.env" <<EOF
######### Pflicht #########
API_ID=$API_ID
API_HASH=$API_HASH

# Anmeldung läuft im Bot-Chat (mycode / mypass)
PHONE_NUMBER=

BOT_TOKEN=$BOT_TOKEN
USER_ID=$CUSTOMER_ID
ADMIN_USER_ID=$ADMIN_USER_ID

################ Optional ##################
LANGUAGE=de
TERMINAL_LOGIN=false
PROXY_URL=
ADMINS=
BOT_MESSAGE_DELETE_TIMEOUT=300
USER_MESSAGE_DELETE_ENABLE=false
DEFAULT_MAX_MEDIA_SIZE=15
DEFAULT_TIMEZONE=Europe/Berlin
CHAT_UPDATE_TIME=03:00
DATABASE_URL=sqlite:///./db/forward.db

AI_MODELS_PER_PAGE=10
KEYWORDS_PER_PAGE=10
PUSH_CHANNEL_PER_PAGE=10
SUMMARY_TIME_ROWS=10
SUMMARY_TIME_COLS=6
DELAY_TIME_ROWS=10
DELAY_TIME_COLS=6
MEDIA_SIZE_ROWS=10
MEDIA_SIZE_COLS=6
MEDIA_EXTENSIONS_ROWS=10
MEDIA_EXTENSIONS_COLS=6
RULES_PER_PAGE=20
DEFAULT_AI_MODEL=gemini-2.0-flash
DEFAULT_AI_PROMPT=Bitte den Sinn und die Formatierung beibehalten und den folgenden Text auf Deutsch umschreiben:
DEFAULT_SUMMARY_PROMPT=Bitte fasse die Nachrichten der letzten 24 Stunden zusammen.
DEFAULT_SUMMARY_TIME=07:00
SUMMARY_BATCH_SIZE=20
SUMMARY_BATCH_DELAY=2
RSS_ENABLED=false
UFB_ENABLED=false
EOF

chmod 600 "$TARGET_DIR/.env"

echo "==> docker compose: Projektname setzen (isoliert je Kunde)"
# COMPOSE_PROJECT_NAME → sonst würden alle Kunden dieselben Volumes teilen
cat > "$TARGET_DIR/.env.compose" <<EOF
COMPOSE_PROJECT_NAME=customer-$CUSTOMER_ID
EOF

echo "==> Container-Namen anpassen"
# docker-compose.yml (im Template) definiert vermutlich einen festen container_name.
# Um Kollisionen zu vermeiden, überschreiben wir per compose override.
cat > "$TARGET_DIR/docker-compose.override.yml" <<EOF
services:
  telegram-forwarder:
    container_name: $CONTAINER_NAME
EOF

echo "==> Build & Start"
cd "$TARGET_DIR"
docker compose --env-file .env.compose build 2>&1 | tail -5
docker compose --env-file .env.compose up -d

echo "==> Fertig: $CONTAINER_NAME läuft"
docker ps --filter "name=$CONTAINER_NAME" --format 'table {{.Names}}\t{{.Status}}'
