# Warum W1 — es ist nicht W1, und die Erklärung reicht trotzdem nicht

Reproduktion:

```bash
python scripts/probe_kline_latency.py --minutes 150
```

Gemessen 09.10.2026, 13:14–15:44 UTC. 283 Durchgänge, **1 415 Abrufe**,
BTCUSDT, fünf Zeitebenen, Reihenfolge je Durchgang gedreht.

Keine Vergleichszelle, also keine Anmeldung: dies ist eine Latenzmessung an
einem Endpunkt, kein Arm über Handelsergebnisse. `total_comparisons` bleibt
bei 55.

---

## 1. Die Frage

`audit/DATA_INTEGRITY_AUDIT.md` liess einen Satz offen stehen:

> **Offen:** warum W1. Dass es der erste Abruf jedes Zyklus ist, ist eine
> Beobachtung und keine Erklärung.

Am 09.10. lief der Papierhandel zwischen rund 08:20 und 10:43 UTC mit etwa
**47 % Fehlerquote**. Alle zwölf Märkte scheiterten wiederholt, und zwar
**ausschliesslich** an `fetch_ohlcv(..., W1)` — dem ersten Abruf jedes Zyklus
— mit einem ccxt-Timeout. Zwei Deutungen standen auf derselben Beobachtung:

1. **W1 ist teuer.** Eine Wochenkerze spannt über viele Rohkerzen. Aggregiert
   die Börse beim Abruf, wäre W1 systematisch langsamer — unabhängig von der
   Reihenfolge.
2. **W1 ist nur zuerst dran.** Dann zahlt der erste Abruf eines Zyklus den
   Verbindungsaufbau, und die Zeitebene ist gleichgültig.

Die Drehung der Reihenfolge ist der ganze Versuchsaufbau. Ohne sie messen
Reihenfolge und Zeitebene dasselbe, und jede Zahl bestätigt beide Deutungen.

## 2. Die Lesehilfe stand vor dem Ergebnis im Code

Wörtlich, aus `scripts/probe_kline_latency.py`, geschrieben um 13:13 UTC:

> *ist die Streuung über ZEITEBENEN deutlich grösser, trägt W1 eigene Kosten.
> Ist die Streuung über POSITIONEN grösser, zahlt der erste Abruf eines Zyklus
> und die Ebene ist gleichgültig. Sind beide klein, war der Ausbruch vom 09.10.
> keine Eigenschaft des Abrufs — und dann bleibt die Frage offen statt
> beantwortet.*

## 3. Das Ergebnis

**Nach Zeitebene** — 283 Abrufe je Ebene:

| Ebene | Median | p90 | max | Fehler |
|---|---|---|---|---|
| W1 | 370 ms | 417 ms | 840 ms | 0 |
| D1 | 368 ms | 404 ms | 526 ms | 0 |
| H4 | 369 ms | 414 ms | 547 ms | 0 |
| H1 | 370 ms | 410 ms | 519 ms | 0 |
| M15 | 370 ms | 415 ms | 821 ms | 0 |

**Nach Position im Durchgang** — 283 Abrufe je Position:

| Position | Median | p90 | max |
|---|---|---|---|
| **1** | **403 ms** | **442 ms** | 840 ms |
| 2 | 365 ms | 388 ms | 798 ms |
| 3 | 367 ms | 389 ms | 526 ms |
| 4 | 370 ms | 389 ms | 821 ms |
| 5 | 367 ms | 386 ms | 522 ms |

| Streuung der Mediane | |
|---|---|
| über Zeitebenen | **3 ms** |
| über Positionen | **37 ms** |

**Deutung 2, eindeutig.** Die Streuung über Positionen ist das Zwölffache der
Streuung über Zeitebenen. Eine Wochenkerze kostet **3 ms** mehr als eine
Viertelstundenkerze — auf einer Grundlast von 370 ms sind das 0,8 %, also
nichts. Der **erste** Abruf eines Zyklus kostet **36 ms** mehr als die
folgenden, gleichgültig welche Ebene er holt.

**W1 trug den Hut der Position 1.** Die Frage „warum W1" ist damit beantwortet,
und die Antwort lautet: nicht W1.

## 4. Und die Antwort erklärt den Ausbruch nicht

Hier muss der Bericht gegen sein eigenes Ergebnis argumentieren.

**Der ccxt-Standardzeitüberschreitung liegt bei 10 000 ms** (nachgesehen, nicht
erinnert: `ccxt.binance().timeout`). Gemessen wurde:

| | |
|---|---|
| Aufschlag der Position 1, Median | 36 ms |
| Aufschlag der Position 1, p90 | 54 ms |
| **schlechtester Einzelwert aus 1 415 Abrufen** | **840 ms** |
| **Schwelle, ab der ccxt abbricht** | **10 000 ms** |

Der schlechteste Abruf, den diese Messung in zweieinhalb Stunden gesehen hat,
liegt **um den Faktor zwölf** unter der Schwelle. Ein Aufschlag von 36 ms kann
keinen Abbruch bei 10 Sekunden auslösen.

**Schärfer noch: die Form passt nicht.** Ein Timeout ist ein Randereignis. Wäre
der Kaltstart der Mechanismus, müsste Position 1 einen **schwereren Rand**
tragen, nicht nur einen verschobenen Körper. Die Maxima sagen das Gegenteil:

| Position | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| max | 840 | 798 | 526 | 821 | 522 |

Position 1 hat den höchsten Einzelwert, aber die Positionen 2 und 4 liegen
dicht daneben. Der Kaltstart **verschiebt die Verteilung um 36 ms und fügt
keinen Rand hinzu**. Das ist nicht „zu wenig Evidenz" — das ist Evidenz
**gegen** den einzigen Mechanismus, den diese Messung sehen konnte.

## 5. Zwei unabhängige Messungen sagen: der Ausbruch wiederholt sich nicht

| Quelle | Umfang | Fehler |
|---|---|---|
| diese Messung, `urllib`, ein Markt | 1 415 Abrufe über 2,5 h | **0** |
| der Papierhandel selbst, `ccxt`, zwölf Märkte | **4 010 Zyklen** seit dem Ausbruch | **0** |

Die zweite Zeile ist der stärkere Beleg, und sie kostete nichts. Der
Fehlschlagzähler des Papierhandels steht auf **5 043** — genau dem Wert, den
`DATA_INTEGRITY_AUDIT.md` am Ende des Ausbruchs notierte („5 043 Fehlschläge
auf 46 096 Zyklen"). Inzwischen stehen 50 106 Zyklen da. Also 4 010 Zyklen
durch ccxt, auf allen zwölf Märkten, über alle fünf Ebenen — **ohne einen
einzigen neuen Fehlschlag**.

Die berichtete Quote von 10,06 % ist deshalb ein Durchschnitt über die
Geschichte und nicht der Zustand. Der Zustand ist null.

## 6. Was damit offen bleibt, und wie es jetzt richtig gestellt ist

**Vorher:** warum scheitert W1?
**Jetzt:** warum scheitert der erste Abruf eines Zyklus — und zwar in
Ausbrüchen von zweieinhalb Stunden, die sich in fünfeinhalb Stunden Ruhe nicht
andeuten?

Das ist Fortschritt, auch ohne Antwort: eine ganze Familie von Hypothesen ist
tot. W1 aggregiert nicht teuer, W1 nimmt keinen anderen Pfad, W1 liefert nicht
mehr Daten. Alle drei hätten sich in der Spalte „nach Zeitebene" zeigen müssen,
und dort stehen 3 ms.

**Und was ein Ruhe-Mass grundsätzlich nicht kann:** einen Rand auflösen, der
während der Messung abwesend war. Der Ausbruch ist das Ereignis, und er war
nicht da. Diese Messung schliesst den Kaltstart als Mechanismus aus; sie
findet den wirklichen nicht. Dafür bräuchte es eine Aufzeichnung **während**
eines Ausbruchs, also eine Wache, die beim Überschreiten einer Fehlerquote
Zeitstempel und Antwortzeiten mitschreibt — nicht eine Messung, die man startet,
wenn es vorbei ist.

## 7. Eine Folge, die ich ausdrücklich NICHT umgesetzt habe

Wenn Position 1 strukturell exponiert ist, liesse sich die Exposition
entfernen: ein billiger Aufwärm-Abruf vor dem eigentlichen Zyklus, oder eine
gehaltene Verbindung. Das ist naheliegend, klein und falsch — jetzt.

**Ein Zuverlässigkeits-Fix ist eine Strategieänderung.** Ein gescheiterter
Zyklus ist eine Entscheidung, die nicht getroffen wurde. Weniger Fehlschläge
heissen mehr Entscheidungen, heissen **andere Trades**. Die homogene
Vorwärtsstichprobe steht bei 11 Trades von 41 nötigen, und jede Änderung, die
verändert, welche Trades entstehen, setzt sie zurück — um 16 Tage, also über
den Stichtag des Ziels hinaus.

Und genau diese Änderung wäre **unsichtbar**: `run_signature` deckt
Startkapital, Setup-Liste, Kostendeckel, Signalzeitebene und
Ablehnungsversion. Ein Aufwärm-Abruf berührt keinen davon. Das ist dieselbe
Lücke, die zwei Stunden vorher die Stichprobe von 14 auf 11 korrigiert hat
(`audit/DIE_VORWAERTSSTICHPROBE.md`, Abschnitt 7) — nur würde sie diesmal in
die andere Richtung wirken: nicht ein Schnitt, den ich nachträglich finde,
sondern einer, den ich selbst verursache und nicht aufzeichne.

Der Kandidat steht also hier und wartet. Er wird umgesetzt, **nachdem** die
41 Trades beisammen sind, nicht davor. Und das Argument dafür ist jetzt
schwächer als vor dieser Messung: 36 ms sind kein Abbruch bei 10 Sekunden.

## 8. Grenzen dieser Zahlen

**Ein Markt, ein Client.** BTCUSDT statt zwölf, weil zwölf die Abrufrate
verdreifacht hätten, während der Papierhandel dieselbe IP benutzt. Und
`urllib` statt ccxt: gemessen ist der Endpunkt, nicht der Bibliothekspfad.
Scheiterte ccxt an etwas Eigenem — einer Verbindungsverwaltung, einem
Ratenbegrenzer — würde diese Messung es nicht sehen. Die 4 010
Fehlschlag-freien ccxt-Zyklen aus Abschnitt 5 schliessen diese Lücke
teilweise, aber auch sie sind aus der Ruhe.

**Der Endpunkt wurde geprüft, nicht angenommen** — und ich hatte ihn beim
ersten Nachsehen falsch. `config/settings.yaml` sagt `testnet: true`, und
`venue.build()` schickt einen Testnet-Client auf `demo-fapi.binance.com`.
Dieser Host **ist** messbar schlechter: 848 gegen 442 ms Median, Faktor 1,9 —
das Elffache des Positionseffekts und das 135-fache des Ebeneneffekts. Zwanzig
Minuten lang war das mein Ergebnis. Dann stand in `scripts/papertrade.py:105`
ausdrücklich `testnet=False`, mit einer Begründung daneben: Kerzen sind
öffentlich, nur Handel berührt ein Konto. Die Konfigurationszeile gilt dem
**Ausführer**, nicht den Daten. Die Messung traf den richtigen Host.

*Der Beinahe-Fehler ist aufschlussreicher als die Korrektur.* Was ich nie
variiert hatte — den Host — war die Grösse mit dem weitaus stärksten Effekt.
Dass sie hier konstant *richtig* war, ist Glück im Aufbau, nicht Verdienst.
Für die Stufe 8 auf dem Testnet gehört die Zahl trotzdem notiert: dort wird
jeder Abruf rund doppelt so lange brauchen.

**Die Rohwerte dieses Laufs existieren nicht.** Das Skript hat 1 415
Messungen in eine Zusammenfassung gerechnet und dann verworfen. Niemand kann
daran ein p99 nachrechnen oder den Rand anders schneiden als ich es getan
habe. Behoben für den nächsten Lauf — alle Einzelmessungen gehen jetzt nach
`data/probe_kline_latency.json` —, aber **für diesen Lauf nicht nachholbar**,
und die Tabellen in Abschnitt 3 sind deshalb Zeugnis und nicht Datensatz.
Dieser Bericht wird nicht nachträglich mit einem zweiten Lauf unterfüttert:
das wären andere Zahlen in derselben Tabelle.
