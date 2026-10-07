# Der reparierte FreqAI-Baseline-Vergleich

Lieferpunkt 5 des Forschungsauftrags: *„Reparierter vollständiger
FreqAI-Baseline-Vergleich oder dokumentierte konkrete Blockade."*

Stand: 07.10.2026. **Die Basislinie steht. Der FreqAI-Arm läuft.**

---

## 1. Was vorher kaputt war, und warum der alte Vergleich keiner war

Drei getrennte Defekte, alle drei behoben, alle drei so geartet, dass das
Ergebnis ohne sie plausibel aussah.

### 1.1 Der Backtest endete am Geld, nicht am Fenster

Der ursprüngliche Basislauf startete mit **1 000 USDT** und war nach 15 Wochen
bei 201,93 USDT. Danach reichte das Kapital nicht mehr für die Mindestgrösse,
und der Lauf handelte 16 Monate lang **nicht mehr**. Gemeldet wurden „2 425
Trades über 19 Monate".

Das ist keine Messung der Strategie, sondern eine Messung ihres
Kapitalverlaufs. Dieselbe Strategie macht im selben Fenster **15 624 Trades**,
wenn das Kapital nicht bindet — das Sechsfache. Behoben über
`config.measure.json` mit `dry_run_wallet: 1 000 000`: gross genug, dass die
Kapitalbindung nie greift, und damit misst der Lauf, was die Strategie tut,
statt was ihr Konto aushält.

### 1.2 Der FreqAI-Arm lief 45 Tage und 28 Trades

Der erste FreqAI-Lauf brach ab. Übrig blieben 28 Trades über 45 Tage gegen
eine Basislinie über 579 Tage. Zwei Läufe über verschiedene Fenster sind kein
Vergleich, egal wie sauber jeder einzelne ist.

### 1.3 `identifier` ist ein Cache-Schlüssel ohne die Konfiguration darin

Der zweite Anlauf kam bis **75 von 83 Folds** und brach dann ab: er traf auf
Modelle eines früheren Laufs, die unter anderen Einstellungen trainiert worden
waren — gemeldet als *„different features furnished by current strategy"*.

Das ist die Fehlermeldung. Der Defekt ist schlimmer: **vorher hatte er diese
Modelle stillschweigend wiederverwendet.** 74 Folds lang hat er fremde Modelle
benutzt und nichts gesagt. Erst als die Merkmalsliste sich so weit unterschied,
dass das Laden selbst scheiterte, wurde es sichtbar.

Dasselbe Problem hat dieses Projekt für seine eigenen Läufe mit
`journal/version.py::run_signature` gelöst: was einen Lauf verschieden macht,
gehört in den Schlüssel. Der `identifier` trägt jetzt den Label-Horizont und
die interne Teilung — `lgbm-h12-split0`.

### 1.4 Und die Teilung selbst war undicht

Unabhängig von den dreien: `make_train_test_datasets` ruft
`sklearn.train_test_split` mit `shuffle=False` auf — chronologisch, aber **ohne
Abstand**. Das letzte Trainingslabel reicht `label_period_candles` Kerzen in
die Validierung hinein, und genau diese Menge geht als `eval_set` an LightGBM.
Gemessen am 07.10.2026 mit `scripts/ft_label_boundary.py` an der installierten
Version 2026.9.

`test_size` steht jetzt auf 0. Damit entfällt `eval_set`, und die Auswahl
gehört in den äusseren, zeitlich korrekten Walk-forward. **Alte Läufe mit
`test_size > 0` bleiben als eingeschränkt markiert** — ein Parameter von heute
gibt keinen Lauf von gestern frei.

---

## 2. Die Basislinie, repariert

```bash
./.venv/Scripts/python.exe scripts/ft.py --measure backtesting \
    --strategy BaselineTrend --timerange 20250301-20261001
```

`BaselineTrend`, Spot, max. 2 offene Positionen, Einsatz 200 USDT,
Gebühr **0,1000 % je Seite** (freqtrade nimmt den schlechtesten
dokumentierten Satz der Börse, unterste Stufe).

| Kennzahl | Wert |
|---|---|
| Fenster | 2025-03-01 bis 2026-10-01 (579 Tage) |
| Trades | **15 624** (26,98/Tag) |
| Startkapital | 1 000 000 USDT |
| Endkapital | 994 214,70 USDT |
| **Absolut** | **−5 785,30 USDT** |
| **Gesamt** | **−0,58 %** |
| Expectancy je Trade | **−0,37 USDT** (Ratio −0,56) |
| Profit-Faktor | **0,35** |
| Sharpe (geschlossene Trades) | −196,81 |
| Sortino | −503,98 |
| SQN | −47,72 |
| p-Wert des mittleren Gewinns | **0** |
| Handelsvolumen | 6 249 344,72 USDT |
| Tage gewonnen / neutral / verloren | **34 / 19 / 526** |
| Längste Verlustserie | **102 Trades** |
| Bester Markt | SOL/USDT −0,16 % |
| Schlechtester Markt | ETH/USDT −0,21 % |
| Abgelehnte Einstiegssignale | 23 238 |

**Was daran bemerkenswert ist, und was nicht.**

Nicht bemerkenswert: dass sie verliert. Das sagt dieses Projekt seit Monaten.

Bemerkenswert ist die **Verlässlichkeit**: 526 Verlusttage von 579, p-Wert des
mittleren Gewinns 0, Profit-Faktor 0,35, **kein einziger Markt positiv**. Das
ist kein Rauschen um die Null, aus dem sich mit etwas Glück ein Gewinner
heben liesse. Es ist eine Strategie, die zuverlässig genau so viel verliert,
wie die Maut kostet — und der beste Markt verliert 0,16 %.

Der alte Lauf mit 1 000 USDT las **−79,8 %**, dieser liest **−0,58 %**. Beide
sind richtig und sie messen Verschiedenes: der erste, was mit einem kleinen
Konto passiert (Kapitalbindung, Mindestgrössen, keine Erholung); der zweite,
was die Strategie je Trade tut. Für einen Vergleich zweier Strategien taugt
nur der zweite. Für die Zielrechnung mit 1 000 CHF ist der erste die Warnung.

---

## 3. Der FreqAI-Arm

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
./.venv/Scripts/python.exe scripts/ft.py --freqai --measure backtesting \
    --strategy FreqaiCostFiltered --freqaimodel LightGBMRegressor \
    --timerange 20250301-20261001
```

**Status: läuft.** Dasselbe Fenster, dasselbe Kapital, derselbe Einsatz,
dieselbe Gebühr — nur die Entscheidung kommt aus dem Modell.

Fortschritt zum Stand dieses Berichts: **46 von 83 Folds** auf dem ersten von
drei Märkten, rund 58 Sekunden je Fold (davon ~9 s LightGBM, der Rest
Merkmalsaufbau). Erwartete Gesamtdauer rund vier Stunden.

Dass er läuft, ist selbst ein Ergebnis: Defekt 1.3 war genau hier, und 46 Folds
ohne Cache-Kollision belegen, dass der Schlüssel jetzt trägt. Der vorige Lauf
war an dieser Stelle schon durch 74 Folds mit fremden Modellen gelaufen.

### Wie der Vergleich zu lesen sein wird

Vorab festgelegt, **bevor** die Zahl da ist:

1. **„Besser als die Basislinie" ist keine Abnahme.** Ein kleinerer Verlust ist
   kein Gewinn. Dieselbe Regel, die `ratchet.py::decide` für alle 18 Familien
   anwendet, gilt hier.
2. Die Abnahme ist **absolut positiv**, und zwar mit einem Intervall, das die
   Null ausschliesst — auf die angemeldete Vergleichszahl korrigiert.
3. Ein positiver FreqAI-Lauf wäre **ein** Lauf, keine Familie. Er bräuchte
   dieselbe Replikationsprüfung wie jeder andere Kandidat.
4. Die Zahl aus diesem Lauf ist **Replay**, nicht Forward. Sie wird nicht mit
   den 10 Vorwärts-Trades des Papierhändlers in einen Topf geworfen.

---

## 4. Was auch ein fertiger Vergleich nicht beantwortet

**Die Märkte sind drei, nicht zwölf.** FreqAI läuft hier auf BTC, ETH, SOL.
Das Paper-System handelt zwölf. Ein Ergebnis auf dreien ist eine Aussage über
die drei — die teuerste Lektion dieses Projekts, und sie gilt auch hier.

**Spot, nicht Perpetual.** `Trading Mode: Spot`. Kein Funding, keine
Liquidation, kein Hebel. Die Zielrechnung über 20× setzt Perpetuals voraus.

**Die Gebühr ist der schlechteste dokumentierte Satz** (0,1 % je Seite, unterste
Stufe). Das ist konservativ und bewusst so — aber es ist auch das Fünffache
dessen, was `audit/VENUE_KOSTEN_REPORT.md` auf der gemessenen Venue für BTC
findet (0,0005 % Taker-Runde). Ein Modell, das bei 0,2 % Runde verliert, kann
bei 0,001 % gewinnen. Dieser Lauf beantwortet das nicht, und es wäre ein
eigener Arm mit der gemessenen Gebühr — kein nachträgliches Herunterrechnen
dieser Zahlen.

**Die interne Teilung ist entfernt, nicht ersetzt.** `test_size: 0` schliesst
das Leck, lässt FreqAI aber ohne Early Stopping. Die Komplexität ist deshalb
vorab fixiert statt ausgewählt, und das ist die konservative Richtung — ein
Modell, das sich seine eigene Grösse aussucht, hätte dafür Daten gebraucht,
die es zeitlich korrekt nicht hat.
