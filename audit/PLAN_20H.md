# Plan für zwanzig Stunden: nach draussen schauen

Angelegt 11.10.2026. Auftrag von Severin, wörtlich im entscheidenden Teil:
*„falls du der Meinung bist, dass es so nicht funktioniert, dann gehe ins
Internet, durchsuche das komplette Internet und finde neue Informationen, wie
man richtig tradet."*

Ich bin dieser Meinung, und zwar gemessen. Also wird das der Plan.

---

## Was vorher richtiggestellt werden musste

**Die +54 USDT sind nicht verdient.** Sie sind unrealisierter Buchgewinn auf
vier offenen Shorts. Realisiert über 21 geschlossene Trades: **−0,76 USDT**.
Mit zehnfacher Grösse wären daraus **−7,56** geworden, nicht +500.

**Und 760 CHF Einsatz bei 10× Hebel sind 10 % Risiko je Trade**, nicht „mehr
Gewinn". Gemessen am Median-Stop von 1,31 %:

| Risiko je Trade | Konto nach den sieben Verlusten | nötig zum Aufholen |
|---|---|---|
| 1 % (heute) | 93,2 % | +7,3 % |
| 3 % (harter Deckel in `risk.yaml`) | 80,8 % | +23,8 % |
| **10 %** | **47,8 %** | **+109 %** |

Grösse multipliziert die Erwartung. Die gemessene Erwartung ist negativ
(−0,0906 R über 2 734 Replay-Trades, Rest neben der Marktrichtung −0,20 R über
die 21 Live-Trades). Eine negative Zahl mal zehn ist eine grössere negative
Zahl. Das ist keine Vorsicht, das ist Arithmetik.

**Darum wird der Risiko-Deckel nicht angefasst.** Nicht, weil ich zögere,
sondern weil es die eine Änderung ist, von der sicher ist, dass sie schadet.

---

## Warum nach draussen und nicht noch eine Variante von innen

24 Experimentfamilien sind abgeschlossen, keine hat einen Kandidaten ergeben.
Das sind keine Versuche „derselben Sache": Einstiegsregeln, Ausstiegsregeln,
Kostenfilter, Querschnitt, Carry, Orderfluss, maschinelles Lernen,
Ausführung, Hebel, Stop-Weite, Trade-Zahl, Zeitebenen, Haltedauer. Jede ist
mit beiden Toren gemessen.

**Was dabei nie geprüft wurde: ob die Grundannahme stimmt.** Das System sucht
Struktur-Setups auf Krypto-Perpetuals im Stunden- bis Tagesbereich. Dass *in
dieser Nische* ein Vorteil zu holen ist, hat hier nie jemand belegt — es war
die Ausgangsannahme.

Die Frage für die nächsten zwanzig Stunden ist deshalb nicht „welcher Filter
noch", sondern:

> **Welche Handelsansätze haben belegbare, ausserhalb der Stichprobe
> geprüfte Evidenz — und welche davon sind mit den Daten, die wir haben,
> überhaupt testbar?**

---

## Die Regeln für diesen Block

Dieselben wie bisher, und sie gelten gerade jetzt:

1. **Kein Echtgeld, keine Order, keine Broker-Anbindung.**
2. **Risiko-Deckel unberührt.** 1 % bis Kalibrierung belegt, 3 % hart.
3. **Kein API-Budget ausgeben.**
4. **Den Papierhandel nicht anfassen.** Er ist die einzige wachsende Evidenz,
   und die Frage entscheidet sich bei 45–62 Trades, also um den 20.–27.10.
5. **Jede neue Vergleichszelle vorher anmelden**, mit Zellen und
   Abnahmekriterium, vor dem ersten Lauf.
6. **Beide Tore bleiben:** korrigiertes Intervall ohne Null *und*
   Replikation 0,5–2,0×.
7. **Nichts aus den letzten sieben Trades ableiten.** Auswahl nach dem
   jüngsten Ergebnis ist die Methode, mit der sich dieses Projekt schon
   mehrfach selbst einen Vorteil vorgerechnet hat.

## Die Phasen

**Phase A — Literatur, breit.** Was hat dokumentierte, out-of-sample geprüfte
Evidenz? Nach Familien getrennt gesucht, nicht als eine Suche. Jede Quelle mit
Datum, Methode und der Frage: wurde das nach Veröffentlichung noch getestet?

**Phase B — Filter auf Testbarkeit.** Für jeden Fund: brauchen wir Daten, die
wir nicht haben? Ein Ansatz, der ein Instrument oder eine Datenreihe verlangt,
die hier nicht beschaffbar ist, wird als blockiert notiert und nicht
weiterverfolgt.

**Phase C — Anmelden und messen.** Die aussichtsreichsten als Zellen in
`audit/EXPERIMENTS_NEXT.yaml`, `total_comparisons` entsprechend erhöhen, dann
rechnen.

**Phase D — Ehrlich berichten.** Auch und gerade, wenn nichts übrig bleibt.

---

## Protokoll

**Phase A angelaufen.** Acht Ansatzfamilien werden parallel durchsucht
(Zeitreihen-Momentum, Carry, Mikrostruktur, Querschnitt, Saisonalität,
Volatilität, Cross-Asset, und als achte die Meta-Frage: wie viel publizierte
Evidenz repliziert überhaupt). Jeder Fund wird anschliessend gegnerisch
geprüft — Quelle muss existieren und die behauptete Zahl enthalten, sonst
gilt er als widerlegt.

### Während die Suche läuft: drei Befunde am eigenen System

**1. Die Richtungsschieflage ist strukturell, nicht Regime.** Das System war
in der Gewinn- *und* der Verlustserie zu ~90 % short. Ursache ist Setup B
(`TrendlineFakeout`): es ist fest auf `Side.SHORT` verdrahtet und war in
**665 von 665** Replay-Trades short. Alle anderen Setups sind ausgewogen
(A 46 %, C 49 %, G 48,5 % short).

Das Spiegelbild — ein schwacher Bruch unter eine *steigende* Trendlinie — ist
nicht implementiert. **Es zu bauen wäre trotzdem falsch:** Setup B verliert
−0,0795 R über 665 Trades. Das Spiegelbild eines Verlustmusters ist kein
Kandidat.

**2. Setup E feuert und wird genommen — es steht nur nicht im Journal.** Erst
sah es aus, als hätte E nie gefeuert (null Trades im Journal über 2 752).
Nachgemessen an echten Kerzen: E feuert 29-mal auf 32 605 Balken und gewinnt
26 davon gegen frühere Setups — die Verdeckungs-These ist widerlegt. Der
Signalspeicher zeigt **445 genommene E-Signale** im Replay.

**3. Und das ist der eigentliche Fund: die Replay-Grundlage gehört zu einer
anderen Konfiguration als der laufenden.**

| | |
|---|---|
| Journal, 2 734 Replay-Trades | enthält Setup **C** (874 Trades), enthält **kein E** |
| laufende Konfiguration | `['A', 'B', 'E', 'F', 'G']` — C ist seit 04.10. aus |
| Signatur auf den Replay-Trades | **null von 2 734** tragen eine |

Jede Kennzahl, die dieses Projekt aus dem Replay zieht, stammt damit aus einem
System, das so nicht mehr läuft:

| Population | n | Mittel | σ | Treffer | t |
|---|---|---|---|---|---|
| wie berichtet (mit C) | 2 734 | −0,0906 R | 1,4061 | 32,5 % | **−3,37** |
| ohne C, näher am Laufenden | 1 862 | **−0,0631 R** | 1,3493 | 36,9 % | **−2,02** |

**Die Aussage „die genommene Population ist zuverlässig negativ" hängt an
t = −3,37 gegen eine korrigierte Schwelle von 3,317 — sie passiert also knapp.
Ohne Setup C ist es t = −2,02 und damit nicht belegt.** Und auch „ohne C" ist
noch nicht die laufende Konfiguration, weil E weiterhin fehlt.

σ ändert sich kaum (1,4061 → 1,3493), die Mächtigkeitsrechnung also auch nicht
nennenswert (41 → 38 Trades).

**Folge, und sie ist Arbeit statt Meinung:** der Replay muss unter der
laufenden Konfiguration neu gerechnet werden, sonst vergleicht der
Vorwärtslauf gegen eine Grundlinie, die es nicht mehr gibt.
`scripts/run_backtest.py --strategy guide-all` tut genau das und schreibt
weder ins Journal noch in den Signalspeicher — geprüft, bevor er gestartet
wurde, und das Journal ist zusätzlich gesichert.

### Vorab festgelegt: woran der Neulauf zu erkennen ist

Der Replay wird unter `guide-all` neu gerechnet, und `guide-all` heisst
geprüft *„der konfigurierte Pool"* und nicht *„alle Setups"*:
`GuidePool.for_config` filtert auf `enabled_setups(config)`, also
`['A', 'B', 'E', 'F', 'G']`.

**Das schreibe ich vor dem Lauf auf, damit ich hinterher nicht gegen das
Ergebnis prüfe:**

| Erwartung | woran erkennbar |
|---|---|
| Setup **C verschwindet** | 0 Trades mit `setup_key = C` |
| Setup **E erscheint** | > 0 Trades mit `setup_key = E`; der Signalspeicher zeigt 445 genommene E-Signale, also sollten es einige hundert sein |
| A, B, G bleiben **ähnlich** | Trade-Zahl je Setup innerhalb ±10 % des alten Laufs |
| Laufzeit | > 15 min je Markt, gemessen (der erste Versuch lief in ein `timeout`) |

**Bricht die dritte Zeile, ist der Neulauf nicht vergleichbar** — dann hat
sich zwischen den beiden Läufen mehr geändert als die Setup-Liste, und die
Differenz misst nicht, was sie messen soll. Das wäre selbst ein Befund und
kein Grund, die Zahl trotzdem zu nehmen.

**Was der Neulauf nicht leisten kann:** er sagt, was die *heutige*
Konfiguration über 2022–2026 getan hätte. Er sagt nichts darüber, ob die
Auswahl dieser Konfiguration — C aus, E dran — an denselben Daten getroffen
wurde, die ihn jetzt bewerten. Sie wurde es (C wurde am 04.10. nach einer
Messung an eben diesem Replay abgeschaltet). Der neue Replay ist damit
**keine unabhängige Stichprobe für die Frage „ist diese Konfiguration gut"**,
sondern nur eine ehrliche Grundlinie für den Vergleich mit dem Vorwärtslauf.
Das ist ein Unterschied, der leicht verlorengeht.

---

## Phase A abgeschlossen: 32 Agenten, 0 Ansätze überlebt

Acht Ansatzfamilien, jede eigenständig durchsucht, jeder ernstzunehmende Fund
anschliessend gegnerisch geprüft. **32 Agenten, 0 Fehler, 40 Minuten,
1 266 Werkzeugaufrufe.**

> **24 Ansätze geprüft. 0 haben die Prüfung überlebt.**

Und die Widerlegungen sind substanziell, nicht faul. Drei Beispiele:

* **TSMOM (Moskowitz/Ooi/Pedersen 2012):** alle vier Zitate existieren mit
  exakten Metadaten. Der Prüfer hat das Original im Volltext gelesen und
  festgestellt, dass *„signifikant für jedes der 58 Instrumente"* die
  Formulierung des **Abstracts** ist, die der eigene Fliesstext des Papiers
  widerlegt.
* **Vol-Targeting-Overlay:** zwei von vier Quellen verifizieren wörtlich, eine
  hat falsche Kennzahlen, und **die einzige Krypto-Quelle existiert nicht wie
  zitiert** — eine erfundene Zitation, gefangen.
* **Langsames Trendsignal mit Tickgrösse als Diskriminante:** Quelle echt und
  wörtlich korrekt — aber *der Diskriminant des Papiers ordnet unser gesamtes
  Universum der Schicht zu, in der es den Trend-Ertrag als verschwunden
  misst*, und eine direkte Messung auf den zwölf Perps bestätigt das.

### Was die acht Familien ergeben

| Familie | Befund |
|---|---|
| Zeitreihen-Momentum | Beste Belegbasis, Zerfall gemessen: Sharpe des schnellsten Signals 0,84 → 0,12, des langsamsten 0,70 → 0,40 ± 0,26. Krypto-TSMOM wirkt nur long-only als Markt-Timing — **genau der gehebelte Beta-Befund aus E8**. |
| Carry | Echtes, grosses Phänomen (>10 % p.a.) — und die Nachprüfung ist negativ: die Autoren selbst zeigen, dass der Spot-ETF den Carry um 36–97 % des Mittelwerts gesenkt hat. Deckt sich mit E6. |
| Mikrostruktur | Leer. Was gross ist, ist **gleichzeitig statt vorhersagend** (Cont/Kukanov/Stoikov sagen das selbst); was prognostiziert, hat **negatives** Out-of-Sample-R² (−0,37 bis −0,10); was funktioniert, lebt auf Sekunden. |
| Querschnitt | Ein Überlebender — der in zwölf Large Caps nicht überlebt. Size, Volumen, Illiquidität entstehen in Micro-Caps und verschwinden bei Beschränkung auf grosse Coins. |
| Saisonalität | Robuste Muster nur in **Volatilität und Liquidität**, nicht in Renditen. Der meistzitierte Befund (Monday-Effekt) hält laut Müller 2024 „nicht in Daten nach 2015". |
| Volatilität | Gründungsbefund dreifach zerlegt; beim Markt-Faktor ist die gemanagte Kombination out-of-sample **schlechter** als die ungemanagte. |
| Cross-Asset | Systematisch durchgemessen: 141 Prädiktoren × 4 Horizonte, unsere FRED-Serien als eigene Kategorie, out-of-sample R² **negativ** gegen einen Random Walk. 5,6 % signifikant — die nominale Rate. |
| Metawissenschaft | Siehe unten. Der eigentliche Befund. |

### Der härteste Befund betrifft nicht eine Strategie, sondern diese Suche

Reproduktion:

```bash
python scripts/study_trial_budget.py
```

Bailey, Borwein, López de Prado und Zhu geben die *Minimum Backtest Length*:
wer `N` Konfigurationen ausprobiert und die beste nimmt, bekommt allein aus
Rauschen ein In-Sample-Sharpe von `E[max_N]/sqrt(T)`.

Selbst implementiert und **gegen beide Stützpunkte des Papiers geprüft**
(N = 7 → 1,92 Jahre, N = 45 → 5,00 — beide exakt getroffen):

| gezählt als | N | nötige Jahre | bei ~5 Jahren Daten |
|---|---|---|---|
| nur die Familien | 24 | 3,92 | im Budget |
| nachrechenbare Zellen | **59** | **5,47** | **über dem Budget** |
| die Arme | **87** | **6,16** | **über dem Budget** |
| behauptete Versuche | **124** | **6,79** | **über dem Budget** |

**Bei fünf Jahren Daten trägt diese Reihe 45 unabhängige Versuche.** Drei von
vier Zählweisen liegen darüber.

> **Die Suche hat die Datenlänge überholt.** Jeder weitere positive Fund auf
> denselben fünf Jahren ist a priori verdächtig — unabhängig davon, wie das
> Bonferroni-Intervall aussieht. Bonferroni korrigiert die Fehlerrate eines
> Tests; es verlängert nicht die Reihe.

**Die Gegenrichtung, die dazugehört:** `N` ist die Zahl *unabhängiger*
Versuche, und Varianten derselben Idee zählen weniger als eine ganze. Die
effektive Zahl liegt zwischen 24 und 124 und ist hier **nicht gemessen**. Was
die Rechnung trotzdem sagt: schon bei 45 ist das Budget aufgebraucht, und 45
liegt mitten in dieser Spanne.

### Was daraus folgt

**Nicht:** dass es keine Kante gibt. Die Rechnung sagt nichts über die Welt,
sie sagt etwas über diese Datenreihe und diese Suche.

**Sondern:** eine positive Zahl auf *diesen* fünf Jahren ist kein Beleg mehr.
Der Vorwärtslauf ist deshalb nicht nur die beste verbleibende Evidenzquelle —
er ist die **einzige**, die überhaupt noch etwas belegen kann, weil er Daten
erzeugt, auf denen noch nicht gesucht wurde.

Das ist zugleich die unabhängige Begründung dafür, ihn nicht anzufassen.
