# CLAUDE.md – TelegramForwarderGerman (Forwarder, standalone)

Deutscher Fork von Heavrnl/TelegramForwarder (Telethon). Main-Bot = Betreiber-/Abrechnungs-Bot
(`MAIN_BOT=1`), Kunden bekommen je einen eigenen Container (`deploy_customer_bot.sh`,
`host_job_runner.py` auf dem VPS). Texte ausschließlich über `utils/i18n.t` + `lang/*.json`
(alle drei Dateien gleicher Schlüsselsatz, siehe `docs/i18n.md`).

## Betrieb

- VPS: `/root/TelegramForwarderGerman` (Main-Bot, Container `telegram-forwarder-bot`),
  Kunden unter `/root/customer_bots/customer-<id>/`.
- Main-Bot starten (hängt zusätzlich im SM-Netz für den BotFather-MCP):
  `docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d --build`
- Kunden-Container: `docker compose --env-file .env.compose up -d --build` im Kundenordner.

## Bot API 10.x im Projekt

- Farbige Buttons: `utils/buttons.py` (`styled_inline`, `styled_url`) – aktiv ab Telethon 1.45.
- HTML-Widgets (`sendWidget`): `utils/bot_api.py` (HTTP-API), `utils/widgets.py` (Jinja2,
  Vorlagen in `widgets/`). Immer Caption als Fallback mitgeben. Test: `scripts/widget_smoke_test.py`.
- Widget-Buttons öffnen den Bot per Deeplink `https://t.me/<bot>?start=sub_billing|menu_rules`
  (ausgewertet in `handlers/command_handlers.py::handle_start_command`).
- `scheduler/bot_api_updates.py` pollt `getUpdates` nur, damit die HTTP-API die Chats kennt
  (sonst `sendWidget` → „chat not found"); `widget_query` wird vorerst leer beantwortet.

## Automatische Bot-Anlage (BotFather über SM-Session + MCP)

- `services/botfather.py` spricht über `utils/mcp_client.py` mit dem telegram-mcp-Server
  (eigene Instanz `telegram-mcp-botfather`, eine dedizierte Session-Manager-Session).
- Env: `BOTFATHER_MCP_URL` (z. B. `http://telegram-mcp-botfather:8765/mcp`),
  `BOTFATHER_MCP_ACCOUNT` (Account-Label = Telefon ohne +, optional bei nur einer Session).
- Einstieg Kunde: Button „Bot automatisch anlegen" (`onboard_auto_create`, pay-first).
  Einstieg Admin: `/anlegen <kunden_id>` ohne Token.
- Niemals Netzwerk-Sessions (telegram-mcp :8765, Sessions 10/28/29/30/33–36) dafür verwenden:
  1 Session = 1 Client, Anti-Ban-Gesetz des Gruppennetzwerks.

## Live-ToDos

- [x] BotFather-MCP-Instanz auf dem VPS (`/root/mcp-session-adapter-botfather`, Port 127.0.0.1:8767,
      SM-Session 82). Session-Wechsel nur nach Abstimmung mit der Suite-Session (Session-Belegung!).
- [x] `BOTFATHER_MCP_URL` gesetzt, Main-Bot + Kunde 8427362165 neu gebaut (2026-11-10).
- [x] Hauptmenü + Onboarding als Widget mit Knöpfen (`handlers/widget_menu.py`, Deeplink `cb_<aktion>`),
      vom Nutzer im Client bestätigt.
- [ ] Knöpfe auch in den inneren Abläufen (Assistent, Regelkarte, Einstellungen) statt Inline-Buttons;
      dafür Callback-Builder so erweitern, dass Rückgabe (Text, Buttons) als Widget gesendet wird.
- [ ] Ein-Klick-Anlage mit Zweitkonto end-to-end testen (Username belegt → Suffix; Limit → Admin-Hinweis).
- [ ] Widget-Phase 2: `widget_query` im Poller fachlich auswerten (Aktionen direkt im Widget,
      z. B. Regel an/aus) statt nur leer zu bestätigen.
- [ ] `/setuserpic` für automatisch angelegte Bots (Upload über MCP prüfen).
- [ ] Session-Rotation: Bot-Zähler je SM-Session, automatisch nächste Session bei Limit 20.
