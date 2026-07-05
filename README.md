![img](images/logo/png/logo-title.png)

<h3><div align="center">Telegram Weiterleiter | Telegram Forwarder</div>

---

<div align="center">

[![Docker](https://img.shields.io/badge/-Docker-2496ED?style=flat-square&logo=docker&logoColor=white)][docker-url] [![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-4CAF50?style=flat-square)](https://github.com/Heavrnl/TelegramForwarder/blob/main/LICENSE)

[docker-url]: https://hub.docker.com/r/heavrnl/telegramforwarder

</div>

> 📌 **Hinweis:** Diese deutsche Version wurde vom Original-Repository [Heavrnl/TelegramForwarder](https://github.com/Heavrnl/TelegramForwarder) kopiert und übersetzt. Alle Credits am Original-Autor.

## 📖 Einleitung
Telegram Weiterleiter ist ein leistungsfähiges Werkzeug zur Nachrichtenweiterleitung. Sobald dein Account einem Kanal oder einer Gruppe beigetreten ist, können Nachrichten aus dem angegebenen Chat in andere Chats weitergeleitet werden — der Bot muss dem Kanal/der Gruppe nicht selbst beitreten, um Nachrichten mitzulesen. Einsetzbar für Feed-Bündelung mit Filter, Benachrichtigungen, Sammlung von Inhalten und mehr — auch bei Weiterleitungs-/Kopiersperre. Zusätzlich lassen sich Nachrichten dank Apprise an Messenger, E-Mail, SMS, Webhooks, APIs und viele weitere Plattformen verteilen.

## ✨ Funktionen

- 🔄 **Multi-Quellen-Weiterleitung**: Weiterleitung von mehreren Quellen an definierte Ziele
- 🔍 **Stichwortfilter**: Whitelist- und Blacklist-Modus
- 📝 **Regex-Matching**: Reguläre Ausdrücke für Zieltexte
- 📋 **Inhaltsänderung**: Verschiedene Wege, Nachrichteninhalt anzupassen
- 🤖 **KI-Verarbeitung**: Anbindung an KI-APIs verschiedener Anbieter
- 📹 **Medienfilter**: Filtern nach Medientyp
- 📰 **RSS-Abonnement**: RSS-Feeds unterstützt
- 📢 **Multi-Plattform-Push**: Push über Apprise an viele Plattformen

## 📋 Inhaltsverzeichnis

- [📖 Einleitung](#-einleitung)
- [✨ Funktionen](#-funktionen)
- [🚀 Schnellstart](#-schnellstart)
  - [1️⃣ Vorbereitung](#1️⃣-vorbereitung)
  - [2️⃣ Umgebung konfigurieren](#2️⃣-umgebung-konfigurieren)
  - [3️⃣ Dienst starten](#3️⃣-dienst-starten)
  - [4️⃣ Update](#4️⃣-update)
- [📚 Benutzung](#-benutzung)
  - [🌟 Grundlegende Beispiele](#-grundlegende-beispiele)
  - [🔧 Spezielle Szenarien](#-spezielle-szenarien)
- [🛠️ Funktions-Details](#️-funktions-details)
  - [⚡ Filter-Ablauf](#-filter-ablauf)
  - [⚙️ Einstellungen](#️-einstellungen)
    - [Haupteinstellungen](#haupteinstellungen)
    - [Medieneinstellungen](#medieneinstellungen)
  - [🤖 KI-Funktionen](#-ki-funktionen)
    - [Konfiguration](#konfiguration)
    - [Eigene Modelle](#eigene-modelle)
    - [KI-Verarbeitung](#ki-verarbeitung)
    - [Zusammenfassung nach Zeitplan](#zusammenfassung-nach-zeitplan)
  - [📢 Push-Funktion](#-push-funktion)
    - [Einstellungen](#einstellungen)
  - [📰 RSS-Abonnement](#-rss-abonnement)
    - [RSS aktivieren](#rss-aktivieren)
    - [RSS-Dashboard aufrufen](#rss-dashboard-aufrufen)
    - [Nginx-Konfiguration](#nginx-konfiguration)
    - [RSS-Konfigurationsverwaltung](#rss-konfigurationsverwaltung)
    - [Spezielle Einstellungen](#spezielle-einstellungen)
    - [Hinweise](#hinweise)

- [🎯 Sonderfunktionen](#-sonderfunktionen)
  - [🔗 Link-Weiterleitung](#-link-weiterleitung)
- [📝 Befehlsliste](#-befehlsliste)
- [💐 Danksagung](#-danksagung)
- [☕ Spende](#-spende)
- [📄 Lizenz](#-lizenz)



## 🚀 Schnellstart

### 1️⃣ Vorbereitung

1. Telegram API-Zugangsdaten holen:
   - Rufe https://my.telegram.org/apps auf
   - Erstelle eine App und notiere `API_ID` und `API_HASH`

2. Bot-Token holen:
   - Sprich mit @BotFather und lege einen Bot an
   - Notiere den `BOT_TOKEN` des Bots

3. Benutzer-ID holen:
   - Sprich mit @userinfobot, um deine `USER_ID` zu erhalten

### 2️⃣ Umgebung konfigurieren

Neuen Ordner anlegen
```bash
mkdir ./TelegramForwarder && cd ./TelegramForwarder
```
Lade die [**docker-compose.yml**](https://github.com/Heavrnl/TelegramForwarder/blob/main/docker-compose.yml) aus dem Repo in den Ordner.

Anschließend die **[.env.example](./.env.example)** herunterladen oder kopieren, Pflichtfelder ausfüllen und in `.env` umbenennen
```bash
wget https://raw.githubusercontent.com/Heavrnl/TelegramForwarder/refs/heads/main/.env.example -O .env
```



### 3️⃣ Dienst starten

Erststart (Verifizierung nötig):

```bash
docker-compose run -it telegram-forwarder
```
Mit STRG+C den Container verlassen.

`docker-compose.yml` anpassen: `stdin_open: false` und `tty: false` setzen.

Im Hintergrund starten:
```bash
docker-compose up -d
```

### 4️⃣ Update
Hinweis: Für `docker-compose` muss der Repo-Quelltext nicht geklont werden — außer du willst selbst bauen. Sonst reicht im Projektordner:
```bash
docker-compose down
```
```bash
docker-compose pull
```
```bash
docker-compose up -d
```
## 📚 Benutzung

### 🌟 Grundlegende Beispiele

Angenommen, du abonnierst die Kanäle "TG News" (https://t.me/tgnews) und "TG Read" (https://t.me/tgread), willst aber uninteressante Inhalte filtern:

1. Neue Telegram-Gruppe/-Kanal anlegen (z. B. "My TG Filter")
2. Bot als Admin hinzufügen
3. In der **neu erstellten** Gruppe/Kanal senden:
   ```bash
   /bind https://t.me/tgnews  oder  /bind "TG News"
   /bind https://t.me/tgread  oder  /bind "TG Read"
   ```
4. Verarbeitungsmodus festlegen:
   ```bash
   /settings
   ```
   Wähle die Regel des jeweiligen Kanals und passe sie nach Wunsch an.
   
   Details siehe [🛠️ Funktions-Details](#️-funktions-details)

5. Sperrwörter hinzufügen:
   ```bash
   /add Werbung Promo 'das ist Werbung'
   ```

6. Wenn das Format weitergeleiteter Nachrichten stört (überflüssige Zeichen), Regex nutzen:
   ```bash
   /replace \*\*
   ```
   Entfernt alle `**` aus Nachrichten.

> Hinweis: Diese Änderungsbefehle wirken nur auf die zuerst gebundene Regel — im Beispiel "TG News". Um "TG Read" anzupassen: erst `/settings(/s)` → "TG Read" wählen → "Aktuelle Regel anwenden". Oder `/add_all(/aa)`, `/replace_all(/ra)` etc. für alle Regeln gleichzeitig.

Damit erhältst du gefilterte und formatierte Kanalnachrichten.

### 🔧 Spezielle Szenarien

#### 1. Manche Kanalnachrichten haben eingebettete Links, die einen Bestätigungs-Dialog auslösen (z. B. NodeSeek-Ankündigungen)

Originalformat der Kanalnachricht:
```markdown
[**Post-Titel**](https://www.nodeseek.com/post-xxxx-1)
```
Auf die Weiterleitungsregel des Kanals **nacheinander** anwenden:
```plaintext
/replace \*\*
/replace \[(?:\[([^\]]+)\])?([^\]]+)\]\(([^)]+)\) [\1]\2\n(\3)
/replace \[\]\s*
```
Ergebnis-Format — Link ohne Zwischen-Dialog anklickbar:
```plaintext
Post-Titel
(https://www.nodeseek.com/post-xxxx-1)
```

---

#### 2. Nutzernachrichten schöner formatieren

**Nacheinander** ausführen:
```plaintext
/r ^(?=.) <blockquote>
/r (?<=.)(?=$) </blockquote>
```
Danach Nachrichtenformat auf **HTML** setzen — Nutzernachrichten wirken deutlich sauberer:

![Beispielbild](https://i.postimg.cc/TKrjXf7t/163c7534e1ac62980f4f414e829d67be.jpg)

---

#### 3. Regeln synchronisieren

Im **Einstellungsmenü** "Regel-Sync" aktivieren und **Ziel-Regel** wählen. Alle Aktionen auf der aktuellen Regel spiegeln sich zur Ziel-Regel.

Nützlich bei:
- Änderungen sollen nicht im aktuellen Fenster erfolgen
- Mehrere Regeln gleichzeitig anpassen

Soll die aktuelle Regel nur zur Synchronisation dienen, "Regel aktiv" auf **Nein** setzen.

---

#### 4. Weiterleitung an "Gespeicherte Nachrichten" (Saved Messages)
> Nicht empfohlen — umständlich
1. In einer beliebigen vom Bot verwalteten Gruppe/Kanal:
   ```bash
   /bind https://t.me/tgnews  dein_Benutzername (Anzeigename)
   ```

2. Neue Regel anlegen und einstellen:
   - **Sync aktivieren**, Ziel = **Weiterleitungsregel an Gespeicherte Nachrichten**
   - **Weiterleitungsmodus** = **"Nutzermodus"**
   - **Regel deaktivieren** ("Regel aktiv" auf Aus)

Anschließend kannst du in anderen Regeln die Saved-Messages-Regel mitverwalten — alle Änderungen wandern in die Saved-Messages-Regel.


## 🛠️ Funktions-Details

### ⚡ Filter-Ablauf
Zuerst die Reihenfolge der Nachrichtenfilter verstehen (Klammern = Optionen in den Einstellungen):

![img](https://i.postimg.cc/Bjx5G4Yp/IMG-4076.jpg)



### ⚙️ Einstellungen
| Haupt-Einstellungen | KI-Einstellungen | Medien-Einstellungen |
|---------|------|------|
| ![img](https://i.postimg.cc/68dVNtjj/IMG-4077.jpg) | ![img](https://i.postimg.cc/pmDQtRG1/IMG-4078.jpg) | ![img](https://i.postimg.cc/dh8RKwHX/IMG-4079.jpg) |

#### Haupteinstellungen
Erklärung der Optionen:
| Option | Beschreibung |
|---------|------|
| Aktuelle Regel anwenden | Nach Auswahl gelten Stichwort- (`/add`, `/remove_keyword`, `/list_keyword` …) und Ersetzungsbefehle (`/replace`, `/list_replace` …) inkl. Import/Export für die aktuelle Regel |
| Regel aktiv | Wenn an, ist die Regel aktiv, sonst deaktiviert |
| Stichwort-Modus | Umschalten zwischen Black-/Whitelist; da beide getrennt verarbeitet werden, muss manuell umgeschaltet werden. Alle Stichwort-Aktionen beziehen sich auf den hier gewählten Modus — für Whitelist-Änderungen erst auf Whitelist stellen |
| Absender-Name und -ID mit filtern | Wenn an, werden Absender-Name und -ID mit in den Filter einbezogen (nicht in die Nachricht eingefügt) — nützlich, um bestimmte Nutzer gezielt zu filtern |
| Verarbeitungsmodus | Bearbeiten/Weiterleiten. Bearbeiten ändert die Original-Nachricht direkt; Weiterleiten sendet die verarbeitete Nachricht ans Ziel. Hinweis: Bearbeiten geht nur, wenn du Admin bist und die Nachricht aus einem Kanal stammt oder du selbst in einer Gruppe gesendet hast |
| Filter-Modus | Nur Blacklist / Nur Whitelist / Erst Black dann White / Erst White dann Black. Da beide Listen getrennt gespeichert werden, freie Wahl |
| Weiterleitungsmodus | Nutzer- oder Bot-Modus. Nutzer-Modus verwendet den User-Account zum Senden, Bot-Modus den Bot-Account |
| Ersetzungsmodus | Wenn an, werden hinterlegte Ersetzungsregeln auf die Nachricht angewendet |
| Nachrichtenformat | Markdown oder HTML — greift beim finalen Senden. Standard Markdown reicht meistens |
| Vorschau-Modus | Ein/Aus/Original-Übernahme. An zeigt Vorschau für den ersten Link; Standard folgt dem Original |
| Original-Absender / -Link / Sendezeit | Wenn an, werden diese Infos beim Senden angehängt. Standard aus, Vorlagen im Menü "Weitere Einstellungen" |
| Verzögerte Verarbeitung | Holt den Nachrichten-Inhalt nach der eingestellten Verzögerung erneut, dann Verarbeitung — nützlich bei Kanälen, die Nachrichten oft nachbearbeiten. Werte in `config/delay_time.txt` |
| Original löschen | Löscht die Original-Nachricht — vorher Rechte prüfen |
| Zum-Kommentar-Button | Fügt unter der weitergeleiteten Nachricht einen Button zur Kommentarsektion ein — sofern das Original einen Kommentar-Bereich hat |
| Zu anderen Regeln synchronisieren | Synchronisiert Aktionen der aktuellen Regel zu anderen Regeln — außer "Regel aktiv" und "Sync aktiv" |

#### Medieneinstellungen
| Option | Beschreibung |
|---------|------|
| Medientyp-Filter | Wenn an, werden nicht ausgewählte Medientypen gefiltert |
| Ausgewählte Medientypen | Zu **blockierende** Typen. Hinweis: Telegram klassifiziert fest — Bild (photo), Dokument (document), Video (video), Audio (audio), Sprachnachricht (voice). Alles, was nicht in die anderen Kategorien fällt, wird als "Dokument" gezählt: .exe, .zip, .txt etc. |
| Mediengrößen-Filter | Wenn an, werden Medien über der eingestellten Größe gefiltert |
| Max. Mediengröße | In MB, weitere Werte in `config/media_size.txt` |
| Bei Übergröße Hinweis senden | Sendet Hinweis, wenn Medien wegen Größe gefiltert wurden |
| Datei-Endungs-Filter | Filter nach Dateiendung |
| Endungs-Filter-Modus | Black/Whitelist |
| Ausgewählte Endungen | Zu filternde Endungen, Erweiterung in `config/media_extensions.txt` |
| Text durchlassen | Wenn an, wird bei Medien-Filter nicht die ganze Nachricht blockiert — der Text wird trotzdem weitergeleitet |

#### Weitere Einstellungen

Das Menü "Weitere Einstellungen" bündelt gängige Befehle für die direkte Bedienung im UI:
- Regel kopieren
- Stichwörter kopieren
- Ersetzungsregeln kopieren
- Stichwörter löschen
- Ersetzungsregeln löschen
- Regel löschen

Löschen von Stichwörtern, Ersetzungsregeln und Regeln kann auch andere Regeln betreffen.

Auch eigene Vorlagen konfigurierbar: Nutzerinfo, Zeit, Original-Link.
| Option | Beschreibung |
|---------|------|
| Blacklist invertieren | Wenn an, wird Blacklist wie Whitelist behandelt. Im Modus "Erst White dann Black" wird die Blacklist zur zweiten Whitelist |
| Whitelist invertieren | Wenn an, wird Whitelist wie Blacklist behandelt. Im Modus "Erst White dann Black" wird die Whitelist zur zweiten Blacklist |

Kombiniert mit "Erst X dann X" ermöglicht das mehrstufige Black-/Whitelists. Beispiel: Nach Blacklist-Invertierung wirkt die Blacklist im "Erst White dann Black" als zweite Whitelist — nützlich, um bestimmte Nutzer zu beobachten und dabei spezielle Stichwörter herauszufiltern.



### 🤖 KI-Funktionen

Eingebaute KI-Anbindung an große Anbieter — hilft bei:
- Automatischer Übersetzung fremdsprachiger Inhalte
- Geplanter Zusammenfassung von Gruppennachrichten
- Intelligenter Werbefilterung
- Automatischem Tagging
....
  
#### Konfiguration

1. `.env` mit deiner KI-API füllen:
```ini
# OpenAI API
OPENAI_API_KEY=your_key
OPENAI_API_BASE=  # optional, Standard = offizielle API

# Claude API
CLAUDE_API_KEY=your_key

# Weitere unterstützte APIs …
```

#### Eigene Modelle

Modellname nicht dabei? Ergänze ihn in `config/ai_models.json`.

#### KI-Verarbeitung

In KI-Prompts sind folgende Platzhalter verfügbar:
- `{source_message_context:N}` — die letzten N Nachrichten aus dem Quell-Chat
- `{target_message_context:N}` — die letzten N Nachrichten aus dem Ziel-Chat
- `{source_message_time:N}` — Nachrichten der letzten N Minuten aus dem Quell-Chat
- `{target_message_time:N}` — Nachrichten der letzten N Minuten aus dem Ziel-Chat

Prompt-Beispiel:

Vorbedingung: KI-Verarbeitung an, danach nochmal Stichwortfilter, "#nicht_weiterleiten" als Filter-Stichwort ergänzen
```
Dies ist ein Nachrichten-Aggregationskanal, der aus mehreren Quellen speist. Prüfe, ob die neue Meldung inhaltlich schon vorkam. Falls ja: nur "#nicht_weiterleiten" zurückgeben. Sonst gib die neue Meldung im Originaltext und Original-Format zurück.
Du darfst nur "#nicht_weiterleiten" oder den Originaltext der neuen Meldung zurückgeben.
Bisherige Meldungen: {target_message_context:10}
Neue Meldung:
```

#### Zusammenfassung nach Zeitplan

Bei aktivierter Zeitplan-Zusammenfassung fasst der Bot zur eingestellten Zeit (Standard 7 Uhr morgens) die letzten 24 Stunden zusammen.

- Weitere Zeitpunkte in `config/summary_time.txt`
- Standard-Zeitzone in `.env`
- Prompt anpassbar

> Hinweis: Zusammenfassungen kosten viel API-Budget — nur nach Bedarf aktivieren.

### 📢 Push-Funktion

Neben interner Telegram-Weiterleitung ist Apprise integriert — damit lassen sich Nachrichten an Messenger, E-Mail, SMS, Webhooks, APIs und vieles mehr verteilen.

| Push-Haupt-UI | Push-Sub-UI |
|---------|------|
| ![img](https://i.postimg.cc/jDz6rtgB/IMG-4080.jpg) | ![img](https://i.postimg.cc/K1n7yxq6/IMG-4081.jpg) |

#### Einstellungen

| Option | Beschreibung |
|---------|------|
| Nur zu Push-Ziel weiterleiten | Überspringt den Weiterleitungs-Filter und geht direkt zum Push-Filter |
| Medien-Sendemodus | Zwei Modi:<br>- Einzeln: Jede Datei separat pushen<br>- Gebündelt: Alle Dateien in einer Nachricht<br>Welcher Modus passt, hängt vom Ziel-Dienst ab |

### Push-Konfiguration hinzufügen
Vollständige Plattform- und Format-Liste: [Apprise Wiki](https://github.com/caronc/apprise/wiki)

**Beispiel: Push via ntfy.sh**

*   Ziel: Topic `my_topic` auf ntfy.sh
*   Laut Apprise Wiki: `ntfy://ntfy.sh/dein_topic`
*   Config-URL entsprechend:
    ```
    ntfy://ntfy.sh/my_topic
    ```



## 📰 RSS-Abonnement

Integriert: Telegram-Nachrichten zu RSS-Feed umwandeln — Kanäle/Gruppen als Standard-RSS für Reader nutzbar.

### RSS aktivieren

1. In `.env` konfigurieren:
   ```ini
   # RSS-Konfiguration
   # RSS an/aus (true/false)
   RSS_ENABLED=true
   # Basis-URL für RSS; leer = Default (z. B. https://rss.example.com)
   RSS_BASE_URL=
   # Basis-URL für RSS-Medien; leer = Default (z. B. https://media.example.com)
   RSS_MEDIA_BASE_URL=
   ```
2. In `docker-compose.yml` auskommentieren:
   ```
    # Für RSS-Nutzung folgendes einkommentieren
     ports:
       - 9804:8000
   ```
3. Neustart:
   ```bash
   docker-compose restart
   ```
> Hinweis: Alt-Nutzer müssen mit neuer `docker-compose.yml` neu deployen: [docker-compose.yml](./docker-compose.yml)
### RSS-Dashboard aufrufen

Browser: `http://deine_server_adresse:9804/`

### Nginx-Konfiguration
```
 location / {
        proxy_pass http://127.0.0.1:9804;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
```

### RSS-Konfigurationsverwaltung

Interfaces:

| Login | Dashboard | Neu/Bearbeiten |
|---------|------|------|
| ![img](https://i.postimg.cc/NyB6sSSN/IMG-4082.png) | ![img](https://i.postimg.cc/d7w2sppH/IMG-4083.jpg) | ![img](https://i.postimg.cc/hJcLD66Z/IMG-4084.jpg) |


### Erklärung "Neu/Bearbeiten"-Interface
| Option | Beschreibung |
|---------|------|
| Regel-ID | Vorhandene Weiterleitungsregel wählen, für die der RSS-Feed erzeugt wird |
| Bestehende Config kopieren | Bestehende RSS-Config in dieses Formular kopieren |
| Feed-Titel | Titel des Feeds |
| Auto-Fill | Erzeugt den Titel automatisch aus dem Namen des Quell-Chats |
| Feed-Beschreibung | Beschreibung |
| Sprache | Platzhalter, aktuell ohne Funktion |
| Max. Einträge | Max. Anzahl RSS-Einträge, Default 50 — bei medienlastigen Quellen an Plattenplatz anpassen |
| KI für Titel/Inhalt | Wenn an: KI extrahiert Titel und Inhalt und richtet das Format aus. KI-Modell im Bot konfigurieren — unabhängig von der "KI-Verarbeitung"-Option im Bot. Wenn an, schließt es die anderen Optionen unten aus |
| KI-Extraktions-Prompt | Prompt für die Extraktion — bei eigener Definition **muss** die KI folgendes JSON zurückgeben: `{ "title": "Titel", "content": "Inhalt" }` |
| Auto-Titel-Extraktion | Extrahiert Titel per vorgegebenem Regex |
| Auto-Inhalts-Extraktion | Extrahiert Inhalt per vorgegebenem Regex |
| Markdown → HTML | Wandelt Telegram-Markdown mittels Bibliothek in Standard-HTML. Für Custom-Verarbeitung im Bot `/replace` nutzen |
| Custom-Regex für Titel | Eigener Regex für Titel-Extraktion |
| Custom-Regex für Inhalt | Eigener Regex für Inhalts-Extraktion |
| Priorität | Ausführungsreihenfolge — kleinere Zahl = höhere Prio. Regex läuft von hoch zu niedrig, **das Ergebnis eines Regex ist der Input des nächsten**, bis alle durch sind |
| Regex-Test | Testet Regex gegen Zieltext |

### Sonder-Hinweise
- Nur "Auto-Titel" an, "Auto-Inhalt" aus → Inhalt enthält die komplette Telegram-Nachricht inkl. extrahiertem Titel
- Alle Optionen leer → die ersten 20 Zeichen werden Titel, Rest = Original als Inhalt


### Spezielle Einstellungen
Bei `RSS_ENABLED=true` in `.env` kommt in den Bot-Einstellungen zusätzlich `Nur zu RSS weiterleiten` — an: Nachricht durchläuft alle Filter, stoppt nach RSS-Filter, keine Weiterleitung/Bearbeitung mehr.


### Hinweise

- Kein Passwort-Reset — Zugangsdaten sicher aufbewahren

## 🎯 Sonderfunktionen

### 🔗 Link-Weiterleitung

Schicke dem Bot einen Nachrichten-Link — die Nachricht wird in den aktuellen Chat weitergeleitet, egal ob Weiterleitungs-/Kopiersperre aktiv (das Projekt selbst umgeht ohnehin diese Sperren).

### 🔄 Zusammenspiel mit Universal Forum Block
> https://github.com/heavrnl/universalforumblock

Sofern `.env` entsprechend konfiguriert: In einem bereits gebundenen Chat `/ufb_bind <forum_domain>` verwenden — 3-fache Sperr-Synchronisation. `/ufb_item_change` wechselt zwischen: Startseiten-Stichwort / Startseiten-Nutzername / Inhaltsseiten-Stichwort / Inhaltsseiten-Nutzername.

## 📝 Befehlsliste

```bash
Befehlsliste

Basis
/start - Start
/help(/h) - Diese Hilfe anzeigen

Bindung und Einstellungen
/bind(/b) <Quell-Chat-Link/-Name> [Ziel-Chat-Link/-Name] - Quell-Chat binden
/settings(/s) [Regel-ID] - Weiterleitungsregeln verwalten
/changelog(/cl) - Changelog anzeigen

Regel-Verwaltung
/copy_rule(/cr)  <Quell-Regel-ID> [Ziel-Regel-ID] - Alle Einstellungen einer Regel kopieren
/delete_rule(/dr) <Regel-ID> [Regel-ID] [Regel-ID] ... - Regeln löschen
/list_rule(/lr) - Alle Regeln auflisten

Stichwort-Verwaltung
/add(/a) <Stichwort> [Stichwort] ["Stich wort"] ['Stich wort'] ... - Normales Stichwort hinzufügen
/add_regex(/ar) <Regex> [Regex] [Regex] ... - Regex-Stichwort hinzufügen
/add_all(/aa) <Stichwort> [Stichwort] [Stichwort] ... - Stichwort in alle im aktuellen Kanal gebundenen Regeln hinzufügen
/add_regex_all(/ara) <Regex> [Regex] [Regex] ... - Regex-Stichwort in alle Regeln
/list_keyword(/lk) - Alle Stichwörter listen
/remove_keyword(/rk) <Stichwort> ["Stich wort"] ['Stich wort'] ... - Stichwort löschen
/remove_keyword_by_id(/rkbi) <ID> [ID] [ID] ... - Stichwort per ID löschen
/remove_all_keyword(/rak) <Stichwort> ["Stich wort"] ['Stich wort'] ... - Aus allen im aktuellen Kanal gebundenen Regeln löschen
/clear_all_keywords(/cak) - Alle Stichwörter der aktuellen Regel löschen
/clear_all_keywords_regex(/cakr) - Alle Regex-Stichwörter der aktuellen Regel löschen
/copy_keywords(/ck) <Regel-ID> - Stichwörter aus Regel kopieren
/copy_keywords_regex(/ckr) <Regel-ID> - Regex-Stichwörter aus Regel kopieren
/copy_replace(/crp) <Regel-ID> - Ersetzungsregeln aus Regel kopieren
/copy_rule(/cr) <Regel-ID> - Alle Einstellungen aus Regel kopieren (Stichwörter, Regex, Ersetzung, Medien etc.)

Ersetzungsregeln
/replace(/r) <Regex> [Ersetzung] - Ersetzungsregel hinzufügen
/replace_all(/ra) <Regex> [Ersetzung] - Ersetzungsregel für alle Regeln hinzufügen
/list_replace(/lrp) - Alle Ersetzungsregeln listen
/remove_replace(/rr) <Nr.> - Ersetzungsregel löschen
/clear_all_replace(/car) - Alle Ersetzungsregeln der aktuellen Regel löschen
/copy_replace(/crp) <Regel-ID> - Ersetzungsregeln aus Regel kopieren

Import/Export
/export_keyword(/ek) - Stichwörter der aktuellen Regel exportieren
/export_replace(/er) - Ersetzungsregeln der aktuellen Regel exportieren
/import_keyword(/ik) <Datei mitschicken> - Stichwörter importieren
/import_regex_keyword(/irk) <Datei mitschicken> - Regex-Stichwörter importieren
/import_replace(/ir) <Datei mitschicken> - Ersetzungsregeln importieren

RSS
/delete_rss_user(/dru) [Benutzername] - RSS-Nutzer löschen

UFB
/ufb_bind(/ub) <Domain> - UFB-Domain binden
/ufb_unbind(/uu) - UFB-Domain lösen
/ufb_item_change(/uic) - UFB-Sync-Typ wechseln

Hinweise
• Klammer = Kurzform
• Spitze Klammern <> = Pflicht
• Eckige Klammern [] = optional
• Import-Befehle brauchen eine Datei
```

## 💐 Danksagung

- [Apprise](https://github.com/caronc/apprise)
- [Telethon](https://github.com/LonamiWebs/Telethon)
- [Heavrnl/TelegramForwarder](https://github.com/Heavrnl/TelegramForwarder) — Original-Projekt, aus dem diese deutsche Version kopiert und übersetzt wurde

## ☕ Spende

Wenn dir dieser Fork hilft — ein Kaffee ist willkommen:

**USDT TON (GRAM):**

```text
UQDMN4wzKquYDQoGpnofjeB1oQd1gUQEhm9KIAxaRJjZRv4K
```

> Diese Spende-Adresse gehört zum deutschen Fork. Für den ursprünglichen Autor siehe das Original-Repository [Heavrnl/TelegramForwarder](https://github.com/Heavrnl/TelegramForwarder).


## 📄 Lizenz

Dieses Projekt steht unter der [GPL-3.0](LICENSE)-Lizenz — Details siehe [LICENSE](LICENSE).
