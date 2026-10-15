# Telegram Stars – wie der Betreiber an sein Geld kommt

Der Forwarder nimmt Zahlungen über **Telegram Stars** entgegen (Währung `XTR`,
kein externer Zahlungsanbieter). Umgesetzt in `handlers/button/payment.py`
(Rechnung/Invoice) und `handlers/subscription.py` (Pakete + Abo-Verlängerung).

## Pakete

`handlers/subscription.py` → `PACKAGES`:

| Stars | Laufzeit |
|------:|----------|
| 500   | 30 Tage  |
| 1350  | 90 Tage  |
| 5000  | 365 Tage |

Der Kunde klickt im Bot ein Paket, Telegram zeigt die Stars-Rechnung, der Kunde
bezahlt direkt im Chat. `on_pre_checkout` bestätigt, `on_successful_payment`
verlängert `subscription.paid_until`.

## Wohin fließen die Stars?

Die bezahlten Stars landen auf dem **Stars-Guthaben des Bots, dem der
Bot-Token gehört** (der Account, der den Token bei `@BotFather` erstellt hat).

Auszahlung:

1. Guthaben in `@BotFather` → *Bot* → *Payments / Stars* einsehen.
2. Stars lassen sich über **Fragment** (fragment.com) in **TON** umwandeln.
3. Es gilt eine **Sperrfrist von ca. 21 Tagen** ab Zahlungseingang, bevor
   die jeweiligen Stars auszahlbar sind.
4. TON danach auf einer Börse in Fiat tauschen und abheben.

## WICHTIG: Monetarisierung und Bot-Eigentum

Es gibt zwei Wege, einen Kunden-Bot anzulegen:

- **`/anlegen <id> <token>` (Betreiber-Token):** Der Betreiber erstellt den Bot
  bei `@BotFather` selbst. → Die Stars landen auf **dem Betreiber-Account**.
  **Das ist der Weg für zahlende Kunden.**
- **`mybot <token>` (Kunden-Token):** Der Kunde bringt seinen eigenen Bot mit.
  → Die Stars landen auf **dem Account des Kunden**, NICHT beim Betreiber.
  Für Einnahmen ist dieser Weg ungeeignet.

**Empfehlung:** Für zahlende Kunden immer den `/anlegen`-Weg mit einem
Betreiber-eigenen Bot-Token verwenden. Den `mybot`-Weg nur für Fälle, in denen
der Kunde selbst zahlt bzw. keine Abo-Einnahme vorgesehen ist.
