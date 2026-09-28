#!/usr/bin/env bash
# Kunden-Container stoppen und Ordner löschen.
#
# Aufruf:
#   delete_customer_bot.sh <kunden_id>
#
# Löscht:
#   /root/customer_bots/customer-<id>/
#   docker compose Projekt customer-<id>

set -eEuo pipefail

CUSTOMER_ID="${1:-}"
CUSTOMERS_DIR="${CUSTOMERS_DIR:-/root/customer_bots}"

if [[ -z "$CUSTOMER_ID" ]]; then
  echo "Nutzung: $0 <kunden_id>" >&2
  exit 2
fi

if ! [[ "$CUSTOMER_ID" =~ ^-?[0-9]+$ ]]; then
  echo "Fehler: kunden_id muss eine Zahl sein" >&2
  exit 2
fi

TARGET_DIR="$CUSTOMERS_DIR/customer-$CUSTOMER_ID"
CONTAINER_NAME="telegram-forwarder-customer-$CUSTOMER_ID"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "!! Ordner existiert nicht: $TARGET_DIR" >&2
  exit 3
fi

echo "==> Container stoppen: $CONTAINER_NAME"
cd "$TARGET_DIR"
if [[ -f .env.compose ]]; then
  docker compose --env-file .env.compose down -v 2>&1 | tail -5 || true
else
  docker compose down -v 2>&1 | tail -5 || true
fi

# Falls docker compose down ihn nicht erwischt hat (z. B. wegen zerbrochenem
# Projekt), Container direkt entfernen.
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "==> Container hart entfernen"
  docker rm -f "$CONTAINER_NAME" >/dev/null || true
fi

echo "==> Ordner löschen: $TARGET_DIR"
cd /
rm -rf "$TARGET_DIR"

echo "==> Fertig. Kunden-Container $CONTAINER_NAME entfernt."
