# Phase A — meine eigenen Zahlen geprüft

Stand: 05.10.2026. Geprüft gegen den Code und die gespeicherten Messdateien
dieses Projekts, nicht gegen die Erinnerung. Sieben Fragen, je ein Audit und
ein zweiter Durchgang, der den ersten widerlegen sollte; zwei Audits wurden
dabei in Details korrigiert und in ihrem Kern bestätigt.

**Kurzfassung: die Kritik am Bericht vom 05.10.2026 trifft zu.** Die zentrale
Zahl war falsch, weil eine Annahme nicht ausgesprochen war, und drei weitere
Zahlen sind schwächer belegt als sie klangen. Das Vorzeichen des Gesamtbefunds
ändert sich nicht — es wird schlechter, nicht besser.

---

## 1. Die 56,6 % waren falsch. Die Herleitung, offengelegt

### Woher die Zahl kam

Sie kam aus keiner Datei. Sie entstand als Ausdruck im Terminal und wurde nie
festgeschrieben — deshalb hielt nichts fest, welches Auszahlungsschema sie
voraussetzte. Das ist der eigentliche Defekt; die falsche Zahl ist nur seine
Folge.

Im Code steht `scripts/goal.py:176`:

```python
final = equity * (1 + risk_fraction * expectancy) ** trades
```

invertiert in `goal.py:186`:

```python
fraction = (growth ** (1.0 / trades) - 1.0) / expectancy
```

Daraus kommt die +0,322 R: `(20 ** (1/312) − 1) / 0,03 = 0,3215`. Diese Zahl
ist innerhalb ihres Modells korrekt und ist jetzt als Test festgenagelt
(`tests/test_target.py:test_required_mean_r_reproduces_the_committed_figure`).

### Was das Modell stillschweigend annahm

Der Schritt von +0,322 R auf „56,6 % Treffsicherheit" unterstellt, dass jeder
Gewinner **+1,371 R** bringt und jeder Verlierer **−1 R** kostet. Das wurde nie
gesagt. Nachgerechnet und als Test fixiert:

| Frage | Antwort | Test |
|---|---|---|
| Symmetrisch ±1 R, 3 % Risiko, 312 Trades → 20× | **66,75 %** | `test_symmetric_payout_needs_sixty_six_point_seven_five` |
| 56,6 % bei symmetrischer Auszahlung → | **2,99×**, also 2.990 CHF | `test_fifty_six_point_six_reaches_three_times_not_twenty` |
| Welche Gewinngrösse 56,6 % impliziert | **+1,371 R** | `test_the_unstated_assumption_was_a_win_of_one_point_three_seven_one_r` |
| Monatswachstum, das 20× verlangt | **64,75 %** | `test_the_monthly_growth_the_target_implies` |

Die Gegenrechnung im Prüfdokument stimmt also auf die angegebene Stelle. Der
Code liegt jetzt in `src/traidingbrain/learn/target.py`, 23 Tests.

### Welche Auszahlung tatsächlich gemessen ist

Nicht +1,371 R. Gemessen über die 3.300 gelabelten Signale des Champions:

| | gemessen | im Bericht unterstellt |
|---|---|---|
| Mittlerer Gewinner | **+1,5612 R** | +1,5026 R |
| Mittlerer Verlierer | **−1,0384 R** | −1,0000 R (glatt) |
| Trefferquote | 38,64 % | 38,6 % |

Der Verlierer ist **nicht** glatt −1 R: ein Stop wird mit Slippage gefüllt und
kann durchschlagen. Mit `Payout(win=1.5612, loss=1.0384)` verlangt 20× bei 3 %
Risiko und 312 Trades **61,8 %** — nicht 56,6 % und nicht 66,75 %.

### Drei Mängel, die das Modell behält

1. **Konstantes R ist optimistisch.** `E[ln(1+fR)] < ln(1+f·E[R])`, sobald R
   streut (Jensen). Jede geschlossene Formel hier ist eine **Untergrenze**.
   `shortfall_from_variance` misst den Abstand statt ihn zu verschweigen.
2. **312 Trades sind nicht 312 unabhängige Chancen.** Zwölf Märkte zu je 3 %
   geplantem Stop-Risiko summieren sich nominal auf 36 % gleichzeitiger
   Exposition. `goal.py` modelliert Gleichzeitigkeit **nicht** — bestätigt.
3. **Richtung ist nicht Trade.** Eine Vorzeichenprognose auf sieben Tage und
   ein mit Stop und Ziel gewonnener Trade innerhalb dieser sieben Tage sind
   verschiedene Ereignisse. Siehe §2.

### Welche Prozentzahl welche Frage beantwortet

Der Bericht trug 69,9 %, 51,2 % und 56,6 % ohne zu sagen, welche welche ist:

| Zahl | Frage | Funktion |
|---|---|---|
| 69,83 % (1 h), 51,19 % (1 Woche) | **Kostendeckung** — zahlt die Maut | `breakeven_hit_rate` |
| 82,64 % (1 h, Binance Spot) | dieselbe Frage, teurere Börse | `breakeven_hit_rate` |
| 66,75 % / 61,8 % / 56,6 % | **Renditeziel** — erreicht 20× | `required_hit_rate` |

Das sind zwei verschiedene Anforderungen, und die höhere bindet.

---

## 2. Was „richtige Richtung" in diesem Projekt heisst

**Es ist die vorzeichenbehaftete, mautbereinigte Close-zu-Close-Rendite, ohne
jede Barriere.** `src/traidingbrain/learn/outlook.py:452`:

```python
target=float(np.sign(move) * np.max(0.0, abs(move) - cost))
```

mit `move = (closes[index + ahead] - closes[index]) / closes[index]`
(`outlook.py:437-443`). Kein `high`, kein `low`, kein Pfad.

**Die „50,0 %" sind nirgends gemessen.** Es gibt im ganzen Repository keine
Stelle, die `sign(prediction) == sign(move)` berechnet. `study_horizon.py:168`
sagte „Rangkorrelation von 0.004, also praktisch 50.0%" — das ist eine
Umformulierung, keine Rechnung. Die unbedingte Basisquote liegt bei 50,86 %
(5 h) und 50,72 % (10 h), was „50,0 %" plausibel macht und keine Messung
ersetzt.

**Und die beiden Welten widersprechen sich messbar.** Dieselben BTC-M15-Balken,
Close-Vorzeichen gegen Erstberührung einer Barriere:

| Horizont | Barriere | Ziel zuerst | Stop zuerst | Zeit | Übereinstimmung mit Close-Vorzeichen |
|---|---|---|---|---|---|
| 5 h | ±0,5 % | 41,52 % | 42,80 % | 15,67 % | **70,52 %** |
| 5 h | ±1,0 % | 25,34 % | 26,56 % | 48,10 % | **67,58 %** |
| 10 h | ±0,5 % | 46,45 % | 47,50 % | 6,05 % | **66,95 %** |
| 10 h | ±1,0 % | 35,88 % | 37,04 % | 27,09 % | **71,46 %** |

In 29 bis 33 % der Fälle sagen die beiden Labels auf derselben Kerze
Verschiedenes. Sie sind nicht umbenennbar.

**Ein echter Vermischungsfehler im Code.** `study_horizon.py:61` setzt
`HIT_RATE = 0.386` und bepreist damit die Maut einer barrierefreien
Richtungswette — aber 0,386 ist die Zielausstiegsquote *gelabelter Trades*,
also aus der Barrierenwelt, und eine Richtungswette hat per Definition kein
Limit-Ziel beim Ausstieg. Korrekt wäre der Ziel-Anteil 33,879 %, denn nur die
1.118 Ziel-Ausstiege zahlen Maker; die 157 positiven Zeit-Ausstiege zahlen
Taker (`labels.py:424`). Die verbaute Maut ist **0,12149 % statt 0,12314 %,
also 1,34 % zu niedrig.**

---

## 3. Die Maker-Füllungen sind nicht realistisch

Das ist der Befund, der die gemeldete Zahl am stärksten verschiebt, und er
korrigiert eine frühere Korrektur von mir. Ich hatte gesagt, Maker sei kein
ungeprüfter Hebel, weil die Einstiege LIMIT sind und schon Maker zahlen. Der
Code bucht Maker — aber er verdient es nicht:

- **3.219 von 3.300 Füllungen (97,5 %)** nehmen den Open-Zweig
  (`sim/broker.py:355`/`362`, `learn/labels.py:297`/`300`).
- Bei **3.175 davon (96,2 %)** ist `open` **numerisch identisch mit dem
  Limit**, und in 3.218 Fällen in der **allerersten Minute**, in der die Order
  lebt.
- Jede dieser Füllungen wird mit der Maker-Gebühr belastet
  (`broker.py:322-324`, `labels.py:396`).

Wirtschaftlich ist das ein Markteinstieg, der als ruhende Order abgerechnet
wird. Nur **81 von 3.300 Füllungen (2,5 %)** werden überhaupt vom Test
`low < limit` entschieden; es gibt kein Queue-Modell und kein
Teilfüllungsmodell (`"volume"` und `"partial"` kommen in `src/traidingbrain/sim/`
nicht vor).

**Nachgerechnet:** bei Taker-Einstieg über alle 3.324 Signale verschlechtert
sich das Mittel um **+0,02753 R**, also von **−0,0340 R auf −0,0615 R**. Das
betrifft nicht einen Randfall, sondern praktisch die ganze Grundgesamtheit.

---

## 4. Zwei verschiedene gemessene Populationen, 0,058 R auseinander

| Population | n | Trefferquote | Mittel | Enthält |
|---|---|---|---|---|
| Gelabelte Signale (berichtet) | 3.300 | 38,64 % | **−0,0340 R** | keine Platzkonkurrenz, keine Liquidation, 48-h-Zeitschranke |
| Broker-Journal (gebucht) | 2.740 | 32,45 % | **−0,0918 R** | Platzkonkurrenz, Liquidation, keine Zeitschranke |

Der Abstand ist **0,058 R — grösser als jeder der sieben gemessenen und
verworfenen Hebel.** Welche der beiden das System beschreibt, das handeln
würde, ist nicht entschieden: keine gespeicherte Datei hält einen Broker-Lauf
der aktuellen M15-Konfiguration über dieselben vier Märkte mit aktiver
48-h-Zeitschranke. Die 157 positiven Zeit-Ausstiege erzeugen genau die 4,76
Prozentpunkte zwischen Ziel-Anteil 33,88 % und Trefferquote 38,64 %, also kann
der Unterschied ein Artefakt der Zeitschranke sein.

Berichtet wurde die bessere der beiden.

---

## 5. Die 0,004 ist schwächer belegt als sie klang

| Was der Bericht nahelegte | Was gemessen wurde |
|---|---|
| mehrere Märkte | **ein Markt** (BTCUSDT) |
| „jeder Horizont" | **zwei** (5 h und 10 h) |
| 34.400 Fälle | n ist um **33 % zu hoch** registriert |
| ein Ergebnis mit Unsicherheit | **kein Konfidenzintervall, keine Null-Verteilung auf ρ** |

`reporting/intervals.py` kann nur Mittelwerte; die Permutationsnull in
`evaluate.py:196` prüft den Mittelwert der gewählten Teilmenge, nicht ρ. Und es
gibt einen messbaren Zwischen-Fold-Confounder von **+0,0176 — das 4,5-fache
der berichteten Zahl.**

Die **Schlussfolgerung** („kein nutzbarer Vorhersagewert") trägt trotzdem: 0,004
ist in jeder Lesart klein. Aber „0,004" als Eigenschaft des Systems ist nicht
belegt, und ich habe sie so verwendet.

---

## 6. Die Datenabdeckung ist kleiner als behauptet

Ich hatte „5 Jahre, 12 Märkte" nahegelegt. Gezählt:

- Die **5 Jahre gelten nur für Open Interest und Account-Ratio**, und nur für
  **4 von 12 Märkten**.
- **Keine** dieser Nicht-Preis-Quellen erreicht je eine gemessene
  Merkmalsmatrix — nur den LLM-Snapshot. **Das bestätigt die Lücke, die ich
  gemeldet hatte**, und ist der einzige Punkt, an dem meine Darstellung zu
  pessimistisch statt zu optimistisch war.
- **Herkunft ungeklärt:** 43.777 der 43.812 BTC-Zeilen in `data/derivatives/`
  und 100 % der ETH/SOL/XRP-Zeilen lassen sich keinem Skript dieses Repos
  zuordnen. `backfill_derivatives.py` fragt Bybit erst ab 2023-01-01 ab, die
  Daten beginnen 17 Monate früher. Kein Skript rundet `buy_ratio` auf vier
  Dezimalstellen, keines erzeugt `buy_ratio == 0.0`. **Ob das echte
  Venue-Daten, ein Fremdimport oder etwas anderes ist, kann ich aus dem Repo
  nicht entscheiden.** Bis das geklärt ist, darf keine dieser Zeilen in ein
  gemessenes Modell.
- 3.615 Nullen (49,6 %) in einer Funding-Datei; acht Dateien mit
  Millisekunden-Jitter beginnen 2020, die vier ohne Jitter am 2023-01-01.

---

## 7. Was die abgelehnten Signale belegen — und was nicht

Bestätigt: zu keinem der 9.472 abgelehnten Signale existiert ein Fill, eine
Gebühr oder eine Kontobewegung (`sim/plan.py:144` gibt `entry=None`,
`sim/engine.py:279` ruft `submit` nie). Die Auswertung ist kontrafaktisch.

Die **logische Lücke**, präzise: der Broker hat **einen** Platz
(`sim/broker.py:245`). Eine gelockerte Regel nimmt zusätzliche Trades, die
genommene Trades **verdrängen** — und ein Label, das jedes Signal isoliert
bewertet (`labels.py:7-15`), kann diese Verdrängung nicht enthalten. „Die Regel
hat recht" ist also belegt für *diese Signale einzeln bewertet*, nicht für
*das Konto mit gelockerter Regel*.

---

## 8. Die Portfoliorechnung — bestätigt, wie gemeldet

`SimBroker` hat einen hart kodierten Positionsplatz (`sim/broker.py:245`),
`max_open_positions` ist toter Konfigurationstext für Backtest und Paper, und
`scripts/goal.py` modelliert Gleichzeitigkeit nicht. Die berichtete Erwartung
ist ein Mittel über sequenzielle, nicht überlappende Trades.

---

## 9. Eine unabhängige Bestätigung des Kernbefunds

Am selben Tag in einem fremden Codebestand gemessen — Freqtrade 2026.9,
Binance **Spot**, EMA-Trendstrategie, 2.425 Trades über 19 Monate, nichts davon
mein Code:

| | USDT |
|---|---|
| Brutto | **+171,02** |
| Gebühren (0,1 % je Seite, 969.081 Umsatz) | **−969,08** |
| Netto | **−798,07** |

Die Einstiegslogik hatte einen **positiven** Bruttovorteil, und die Maut war
**5,7-mal grösser**. Das ist die unabhängigste Bestätigung, die dieses Projekt
für „die Kosten binden auf kurzen Horizonten" hat, und sie stammt aus Code, den
ich nicht geschrieben habe.

---

## 10. Korrigierte Gesamtlage

| Grösse | Bericht 05.10. | geprüft |
|---|---|---|
| Nötige Treffsicherheit für 20× | 56,6 % | **61,8 %** (gemessene Auszahlung), 66,75 % (symmetrisch) |
| Gemessene Richtungstreffsicherheit | „50,0 %" | **nicht gemessen**; Basisquote 50,8 % |
| Erwartung des Systems | −0,0340 R | **−0,0615 R** mit realistischem Einstieg, **−0,0918 R** im Broker-Journal |
| Maut 1 h | 0,1215 % | **0,1231 %** |
| Nicht-Preis-Daten | „5 Jahre, vorhanden" | 4 von 12 Märkten, Herkunft teils ungeklärt |

**Die Lücke ist grösser als gemeldet, nicht kleiner.** Gemeldet hatte ich 6,6
Prozentpunkte. Gegen eine nicht gemessene Richtungsquote und eine Erwartung von
−0,0615 R ist die ehrliche Aussage: die Lücke ist nicht beziffert, weil die
Zahl, gegen die sie zu beziffern wäre, nie gemessen wurde.

---

## Was daraus folgt

**Sofort zu beheben (Code):**

1. `study_horizon.py` — die Maut von 0,12149 auf 0,12314 korrigieren und die
   Prosa „also praktisch 50.0%" entfernen.
2. Die Richtungstreffsicherheit **wirklich messen**: `sign(prediction) ==
   sign(move)`, mit Intervall, über mehr als einen Markt.
3. Ein Konfidenzintervall und eine Null-Verteilung für ρ bauen; `intervals.py`
   kann nur Mittelwerte.
4. Einen Broker-Lauf der aktuellen Konfiguration mit aktiver 48-h-Zeitschranke
   über dieselben vier Märkte, um zu entscheiden, welche der beiden
   Populationen gilt.
5. Die Taker-Variante als registrierten Arm aufnehmen, nicht als Fussnote.

**Vor jedem Modell mit Nicht-Preis-Daten:** die Herkunft der Zeilen vor 2023
klären. Ein Modell auf Daten unbekannter Herkunft zu trainieren erzeugt eine
Zahl, die nichts bedeutet.

**Methodisch:** keine Prozentzahl mehr ohne das Auszahlungsschema daneben. Das
ist der Fehler, der diesen ganzen Bericht nötig gemacht hat, und `target.py`
ist der Mechanismus, der ihn verhindert — `payout_implied_by` macht eine
unausgesprochene Annahme sichtbar, bevor sie in einen Bericht gerät.
