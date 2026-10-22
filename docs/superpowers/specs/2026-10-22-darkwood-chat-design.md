# Darkwood Terminal — Chat mit dem Bot

Stand: 2026-10-22 · Status: Entwurf zur Freigabe · Branch: `layout`

## 1. Zweck

Der Eigentümer will im Darkwood Terminal mit dem Bot sprechen können: Fragen zur
Lage stellen und Trades vorschlagen. Der Bot sieht dabei alles, was das Terminal
zeigt, prüft jeden Trade-Vorschlag und **nimmt ihn an oder lehnt ihn ab**. Ein
angenommener Vorschlag wird nach einem Klick als **Papier-Order** ausgeführt.

Ziel laut Eigentümer: „das, was am sichersten tradet". Der Chat ist eine
Bedienoberfläche, keine neue Strategie. Er macht das System nicht profitabler;
die gemessene Erwartung je Trade liegt bei [−0.087; +0.059] R (7'335
Replay-Trades). Der Chat sagt das, statt Profit zu versprechen.

### Entscheidungen des Eigentümers (22.10.2026)

| Frage | Antwort |
|---|---|
| Was heisst „angenommen"? | Ein Papier-Trade wird möglich. |
| Wann wird ausgeführt? | Erst nach Klick auf **Ausführen**. |
| Wer antwortet? | Claude über das Abo des Eigentümers (Claude-CLI), kein API-Schlüssel. |
| Wo im Terminal? | Ausklappbares Seitenfeld rechts, über allen Ansichten. |
| Wer urteilt? | Die festen Regeln des Bots. Claude darf warnen, nie freigeben. |

### Ausdrücklich nicht enthalten

- Keine Änderung der Bot-Einstellungen (`plan.yaml`, `risk.yaml`, `settings.yaml`).
- Kein Eingriff in Trades oder Konto des Bots (Plankonto, Papierkonto).
- Kein echtes Geld, keine Börse, keine Schlüssel.
- Keine Änderung am Entscheidungscode (`decision_version` bleibt gleich).

## 2. Aufbau

Fünf Teile, jeder mit einer Aufgabe:

| Teil | Aufgabe | Ort |
|---|---|---|
| Seitenfeld | Chat-Oberfläche, Prüfkarten, Ausführen-Knopf | `dashboard/static/terminal-chat.{js,css}`, Einbindung in `terminal.html` |
| Lagebild | sammelt, was der Bot „sieht", nur lesend | `api/chat/lagebild.py` |
| Sprecher | Claude über die CLI: Antwort + optional Vorschlag im festen Format | `api/chat/sprecher.py` |
| Regelprüfung | festes Urteil angenommen/abgelehnt, Regel für Regel | `api/chat/pruefung.py` |
| Endpunkte + Verlauf | `/api/terminal/chat/*`, Speicher des Verlaufs | `api/chat/router.py`, `data/chat.sqlite` |

`api/terminal.py` hat 1'463 Zeilen; der Chat bekommt darum ein eigenes Paket
`api/chat/` und wird nur per Router eingehängt.

### Ablauf

```
Nachricht  →  Lagebild sammeln  →  Sprecher (Claude): Antwort + ggf. Vorschlag
           →  Regelprüfung: angenommen / abgelehnt, je Regel mit Wert
           →  Prüfkarte im Chat  →  Klick „Ausführen"
           →  Neuprüfung mit aktuellem Kurs  →  Papier-Order (order_oeffnen)
```

## 3. Lagebild

Ein Objekt, gebaut aus den Funktionen, die die Terminal-Endpunkte schon benutzen
(keine zweite Herleitung):

- **Blick des Nutzers:** Markt und Zeitebene, die das Seitenfeld mitschickt.
- **Score** des Markts: Richtung, long/short-Anteil, Bewertung, Regime, Karten
  (`/score/{symbol}`).
- **Kurs:** letzter Preis, Mark, Funding (`/head/{symbol}`).
- **Setups** auf D1, H4, H1 für den Markt, mit Einstieg und Stop.
- **Konten:** Plankonto (Stand, offene Positionen) und manuelles Papierkonto.
- **Letzte Trades** des Markts aus dem Journal (Anzahl, Treffer, R).
- **Kalender:** schwere Termine in 24 h.
- **Bot-Einstellungen** (lesend): Margin, Hebel, Risikodeckel, Zeitebenen.

Jedes Feld trägt seine Quelle. Fehlt eine Quelle, steht dort `unbekannt`,
nie ein Ersatzwert.

## 4. Sprecher (Claude über die CLI)

- Transport wie `brain/subscription.py`: Aufruf der installierten `claude`-CLI als
  Unterprozess, Umgebung über `_cli_environment()`, Zeitlimit.
- Eingabe: Systemtext (Rolle, Regeln, Verbot zu urteilen), Lagebild als JSON,
  letzte 10 Nachrichten des Verlaufs, neue Nachricht.
- Ausgabe als JSON mit zwei Feldern:
  - `antwort`: Text an den Nutzer.
  - `vorschlag`: `null` oder `{symbol, side, margin_usd, leverage, sl, tp}`;
    fehlende Felder `null`.
  - `bedenken`: Liste kurzer Warnungen (optional).
- Ungültiges JSON: genau **eine** Nachfrage mit zitiertem Fehler (wie
  `subscription.py`). Danach Antwort ohne Vorschlag und ohne Karte.
- Claude kennt das Urteil nicht vorab und kann es nicht setzen. Ein Feld wie
  „angenommen" in seiner Antwort wird ignoriert.

## 5. Regelprüfung

Reine Funktion: `pruefe(vorschlag, lagebild, config) -> Urteil`. Kein
Sprachmodell, keine Seiteneffekte.

| # | Regel | Grenze heute | Quelle |
|---|---|---|---|
| 1 | Stop vorhanden, Stop und Ziel auf der richtigen Seite | Pflicht | Logik aus `order_oeffnen` |
| 2 | Nicht gegen das Gesamtbild | Score-Richtung = Vorschlagsrichtung | `setups.require_agreement` |
| 3 | Setup auf einer Handelszeitebene aktiv | D1, H4 oder H1, gleiche Richtung | `setups.timeframes` |
| 4 | Risiko je Trade | ≤ 1.5 % des manuellen Kontos; darüber wird die Margin **gekürzt**, nicht abgelehnt | Plan-Risikodeckel `risk_cap_share` |
| 5 | Kosten im Verhältnis zum Risiko | ≤ 8 % | `limits.max_cost_fraction_of_risk`, Kosten mit `KOSTEN_ROUNDTRIP` wie bei manuellen Orders |
| 6 | Positionsdeckel | 5 offen, 1 je Markt, 2 je Richtung | `RiskLimits.check` |
| 7 | Verlustbremsen | Tag 25 %, Woche 50 %, Pause nach 8 Verlusten | `RiskLimits.check` |
| 8 | Hebel | ≤ 10× | `risk.leverage.max` |

- **Konto für Regeln 4, 5, 7:** das manuelle Papierkonto, weil dort die Order landet.
  Es hat bisher **keinen Kontostand** (`manual_paper.sqlite` kennt nur Positionen).
  Der Chat legt ihn fest als **Start 1'000 USD plus realisierte Ergebnisse der
  geschlossenen manuellen Positionen**, gleicher Start wie das Plankonto. Der Wert
  steht in der Konfiguration des Chats, nicht im Code verstreut.
- **Positionen für Regel 6:** offene Positionen des Bots **und** des manuellen
  Kontos zusammen, damit der Chat den Deckel des Bots nicht umgeht.
- **Fehlender Stop:** Die Prüfung setzt den Stop des aktiven Setups ein und
  markiert ihn als `vom Bot vorgeschlagen`. Gibt es kein Setup, bleibt Regel 1
  verletzt.
- **Unbekannt:** Fehlt die Grundlage einer Regel, ist ihr Ergebnis `unbekannt`,
  und `unbekannt` zählt als verletzt.
- **Urteil:** angenommen genau dann, wenn keine Regel verletzt oder unbekannt ist.
  Jede Regel liefert `{name, status: erfuellt|verletzt|unbekannt, wert, grenze}`.
- **Hinweis bei Ablehnung:** je verletzter Regel ein Satz, was sich ändern müsste.

Die Regelwerte werden aus der laufenden Konfiguration gelesen (`config_offen/`),
nicht in den Chat kopiert.

## 6. Ausführen

- Angenommene Prüfkarte erhält eine `karte_id` und läuft nach
  `execution.proposal_ttl_seconds` (900 s) ab.
- Klick → `POST /api/terminal/chat/ausfuehren/{karte_id}`:
  1. Karte existiert, nicht abgelaufen, nicht schon ausgeführt (sonst 409).
  2. Lagebild neu holen, **Regelprüfung neu** laufen lassen.
  3. Kursabweichung seit Prüfung > `execution.max_price_drift_bps` (15 bp) → nicht
     ausführen, Grund zurückgeben.
  4. Sonst `order_oeffnen(OrderWunsch)` → Zeile in `data/manual_paper.sqlite`.
  5. Karte als ausgeführt markieren (einmalig, auch bei Doppelklick).
- Nie Schreibzugriff auf `data/plan_paper.sqlite`, `journal.sqlite` oder `config*/`.

## 7. Endpunkte und Speicher

| Methode | Pfad | Inhalt |
|---|---|---|
| `POST` | `/api/terminal/chat/nachricht` | `{text, symbol, timeframe}` → `{antwort, bedenken, karte?}` |
| `POST` | `/api/terminal/chat/pruefen` | Formular-Modus ohne Claude: `{symbol, side, margin_usd, leverage, sl?, tp?}` → `{karte}` |
| `POST` | `/api/terminal/chat/ausfuehren/{karte_id}` | → `{ausgefuehrt, order?, grund?}` |
| `GET` | `/api/terminal/chat/verlauf` | letzte 50 Nachrichten mit Karten |
| `GET` | `/api/terminal/chat/status` | Claude erreichbar / angemeldet / nicht installiert |

`data/chat.sqlite`: Tabellen `nachrichten` (Zeit, Rolle, Text) und `karten`
(Vorschlag, Urteil je Regel, Kurs bei Prüfung, Ablauf, ausgeführt, Order-ID).

Die neuen Endpunkte liegen im geteilten Bereich `api/` und werden im Pull Request
für den Kollegen genannt. Sie lesen Bot-Daten nur.

## 8. Oberfläche

Im Darkwood-Stil des Terminals (Blau-Schwarz `#060910`, Zahlen in Monospace,
keine Schatten). Entwurf vom 22.10.2026 als Vorlage.

- Knopf **Bot fragen** in der Kopfzeile; Seitenfeld 380 px rechts, Ansicht
  dahinter bleibt bedienbar; unter 768 px Vollbild.
- Kopf: Blick des Nutzers (`BTC/USDT · H4 · Manuell 1'000 USD`) und Claude-Status.
- Nachrichten: Nutzer rechts, Bot links; unter Bot-Antworten die Quellen.
- Prüfkarte: Vorschlag in einer Zeile, Urteil gross, acht Regeln mit
  ✓ / ✕ / ? und Wert. Angenommen: Bedenken, Countdown, **Ausführen**. Abgelehnt:
  kein Knopf, Hinweis was sich ändern müsste.
- Schalter **Formular** für die Prüfung ohne Claude.
- Antwortzeit 10–30 s: sichtbarer Zustand „Claude denkt …", Eingabe bleibt möglich.
- Design-Skills beim Bau: `ui-ux-pro-max`, `emil-design-eng`, `anti-slop-ajonai`
  (Entscheidungsblatt vorher, `scripts/check.mjs` nachher).

## 9. Fehlerfälle

| Fall | Verhalten |
|---|---|
| CLI fehlt / nicht angemeldet / Zeitlimit | Status zeigt es; Nachricht bekommt einen klaren Satz; Formular-Modus bleibt nutzbar |
| Claude liefert ungültiges JSON zweimal | Antwort ohne Vorschlag, keine Karte |
| Datenquelle fehlt | betroffene Regel `unbekannt` → abgelehnt |
| Karte abgelaufen / Kurs > 15 bp bewegt | nicht ausgeführt, Grund auf der Karte |
| Doppelklick | genau eine Order |
| Zahl in Claudes Text weicht vom Lagebild ab | Karte zeigt nur Zahlen der Prüfung |

## 10. Tests

Zuerst geschrieben, dann der Code (`tests/test_chat_*.py`):

1. Je Regel ein Fall erfüllt und ein Fall verletzt.
2. Fehlende Daten → `unbekannt` → abgelehnt.
3. Risiko über 1.5 % → Margin gekürzt, Urteil nicht wegen Regel 4 abgelehnt.
4. Gegenprobe: Regeln 6 und 7 urteilen wie `RiskLimits.check` mit denselben Eingaben.
5. Claude-Attrappe behauptet „angenommen" für einen regelwidrigen Vorschlag →
   Urteil bleibt abgelehnt.
6. Ausführen: abgelaufene Karte, Kursabweichung > 15 bp, Doppelklick.
7. Trennung: nach Ausführen sind `plan_paper.sqlite` und `journal.sqlite`
   byte-gleich; die Order steht nur in `manual_paper.sqlite`.
8. Sprecher: Attrappe in allen Tests, aber ein Test gegen die echte
   Antwortform von `subscription.py` (`_unwrap`), damit die Attrappe die reale
   Form hat.
9. Formular-Modus funktioniert ohne CLI.
10. Browser: Feld öffnen, Frage stellen, Vorschlag prüfen, ausführen, Order
    erscheint unter Positionen.

## 11. Erfolgskriterien

- Ein regelwidriger Vorschlag wird nie angenommen, egal wie er formuliert ist.
- Jede Ablehnung nennt Regel und Zahl.
- Ein angenommener Vorschlag wird erst nach Klick und erneuter Prüfung ausgeführt.
- Konto und Einstellungen des Bots bleiben unverändert.
- Ohne Claude bleibt die Prüfung über das Formular nutzbar.
