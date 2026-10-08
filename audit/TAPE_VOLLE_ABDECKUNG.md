# Die volle Aufnahme — und sie nimmt dem Maker-Befund zwei Drittel

Reproduktion:

```bash
python scripts/study_tape_fills.py   --markets BTC,ETH,SOL
python scripts/study_taker_drift.py  --markets BTC,ETH,SOL
python scripts/study_cross_venue.py  --markets BTC,ETH
```

Grundlage: 11,00 h Venue-Aufnahme (Lighter) und 1,90 h Binance-Gegenaufnahme
mit selbstregelndem Takt. Gegen die 3,2 h, auf denen
`audit/TAPE_MAKER_BEFUND.md` steht.

---

## 1. Was die Aufnahme geworden ist

| Markt | Takt am Ende | Abfragen | Trades | Bücher | volle Seiten |
|---|---|---|---|---|---|
| BTC | **5,0 s** | 5 837 | 266 991 | 838 | 207 |
| ETH | 9,5 s | 2 651 | 118 919 | 838 | 85 |
| SOL | 26,7 s | 1 401 | 62 036 | 838 | 38 |
| XRP | 60 s | 426 | 5 136 | 838 | 4 |
| DOGE | 60 s | 424 | 1 555 | 838 | 3 |
| LINK | 60 s | 424 | 1 527 | 838 | 3 |

334 von 11 163 Abfragen (3,0 %) begannen nach einer Lücke. Wie viele Trades
dazwischen liegen, sagen diese Daten nicht — `trade_id` läuft global über alle
Märkte.

Binance, neu mit selbstregelndem Takt: **94,9 % Abdeckung** gegen 38,7 % beim
festen 30-Sekunden-Takt. 24 828 von 480 225 Trades durchgefallen, und das ist
hier eine echte Zahl, weil `a` pro Symbol läuft. Gemessene Rate: **35,1
Trades/s** je Markt — noch einmal höher als die 27,7 eine Stunde vorher.

## 2. Der Maker-Befund schrumpft auf 0,43×

`TAPE_MAKER_BEFUND.md` meldete **−0,195 bp** [−0,226; −0,162] bei 1 s auf
5 200 belegten Fills und nannte das den ersten Befund des Projekts, der beide
Tore passiert.

Auf 11 Stunden, 12 184 belegten Fills:

| Horizont | BTC, 11 h | | BTC, 3,2 h |
|---|---|---|---|
| 1 s | **−0,083 bp** [−0,123; −0,039] | Null aus | −0,195 [−0,226; −0,162] |
| 5 s | −0,033 bp [−0,121; **+0,059**] | spannt | −0,151 [−0,205; −0,098] |
| 30 s | −0,047 bp [−0,250; **+0,155**] | spannt | −0,158 [−0,305; −0,019] |
| 5 min | −0,378 bp [−0,850; **+0,111**] | spannt | −0,821 [−1,265; −0,396] |

**Verhältnis 0,43× — ausserhalb des Bandes 0,5–2,0.** Der Befund, der beide
Tore passierte, **fällt jetzt am zweiten Tor.** Und von vier Horizonten
schliesst nur noch einer die Null aus; vorher taten es alle vier.

Die Richtung hält und sie hält jetzt auf drei Märkten:

| Markt | belegte Fills | storniert | Markout 1 s |
|---|---|---|---|
| BTC | 12 184 (6,8 %) | 93,1 % | −0,083 [−0,123; −0,039] |
| ETH | 6 751 (3,9 %) | 96,0 % | −0,178 [−0,242; −0,095] |
| SOL | 4 464 (3,2 %) | 96,6 % | −0,417 [−0,506; −0,327] |

**23 399 belegte Fills** insgesamt gegen 5 200 vorher. Die Storno-Quote
bestätigt sich und ist eher höher: 93,1 bis 96,6 %.

### Was das für das Ziel heisst

| je Fill | CHF bei 200 CHF Position | Fills für 2 953 CHF | gestellte Orders |
|---|---|---|---|
| 0,195 bp | 0,0039 | 757 179 | 9,1 Mio |
| **0,083 bp** | **0,0017** | **1 778 916** | **21,4 Mio** |

## 3. Die Taker-Drift repliziert dagegen sauber

Dieselbe Münze, andere Seite — und diese Seite hält:

| Markt | 1 s | 5 s | 30 s | 5 min |
|---|---|---|---|---|
| BTC | **+0,086** [+0,077; +0,094] | +0,060 [+0,034; +0,085] | +0,046 [−0,021; +0,110] | +0,058 spannt |
| ETH | **+0,236** [+0,216; +0,255] | +0,147 [+0,100; +0,195] | +0,075 spannt | −0,272 spannt |
| SOL | **+0,300** [+0,275; +0,326] | +0,206 [+0,154; +0,257] | +0,268 [+0,136; +0,404] | −0,047 spannt |

BTC gegen die 3,2-h-Messung: **+0,078 → +0,086, Verhältnis 1,10×.** Im Band.
Und die Reversion repliziert ebenfalls: bei 30 s spannt das Intervall, bei
5 min kippt es.

**Der Kontrast ist selbst der Befund.** Zwei Messungen derselben
Mikrostruktur, eine replikiert bei 1,10×, die andere bei 0,43×. Der
Unterschied ist die Stichprobe:

* Die Taker-Drift rechnet über **alle 308 341 Trades** des Tapes.
* Der Maker-Markout rechnet über **beobachtete Buch-Orders**, alle 30 s
  abgetastet — eine Auswahl aus den Orders anderer Leute.

Genau das stand in `TAPE_MAKER_BEFUND.md` Abschnitt 6 als Vorbehalt: *„Das
Buch wird alle 30 s aufgenommen, also sind langlebige Orders
überrepräsentiert … Das verzerrt in dieselbe Richtung wie der Befund, und um
wie viel, sagt diese Aufnahme nicht."* **Jetzt sagt sie es: um mehr als die
Hälfte.** Der Vorbehalt war nicht Höflichkeit, er war die grössere Hälfte der
Zahl.

Der Faktor der Venue-Kosten wird damit 4,8× statt 5,1× in der permanenten
Lesart. Beide Lesarten bleiben stehen, wie beim letzten Mal:

```
  permanent gedacht (1s):    Faktor 4.8x
  revertierend (30s, Null):  Faktor bleibt 21x
```

## 4. Die Niveau-Differenz wechselt das Vorzeichen

| | Venue minus Binance |
|---|---|
| 3,2 h | **+0,342 bp** [+0,198; +0,475] |
| 11 h, BTC | **−0,504 bp** [−0,789; −0,246] |
| 11 h, ETH | **−1,236 bp** [−1,566; −0,907] |

Beide Intervalle schliessen die Null aus, und sie liegen auf
**entgegengesetzten Seiten**. Die Niveau-Differenz ist damit keine Eigenschaft
der beiden Börsen, sondern eine Momentaufnahme. Wer sie als Arbitrage-Spanne
liest, handelt gegen ein Vorzeichen, das sich innerhalb eines Tages dreht.

### Und eine Asymmetrie, die ich nicht auflösen kann

Die Kreuzkorrelation der Sekundenrenditen, beide Märkte gleich:

```
BTC   -1: +0.295   +0: +0.663   +1: +0.087
ETH   -1: +0.332   +0: +0.650   +1: +0.076
```

Maximum bei null, also laufen die Preise gleichzeitig. Aber der Versatz −1 ist
**3,4-mal** so gross wie +1, in beiden Märkten. Nach der Konvention des
Skripts heisst das: Binance läuft etwa eine Sekunde voraus.

**Oder die Uhren der beiden Börsen gehen um eine Sekunde auseinander.** Diese
Daten können das nicht trennen, und das stand als Warnung im Skript, bevor
diese Zahl existierte: *„Ein Versatz der Korrelation ist nicht automatisch ein
Vorlauf … Wer das auflösen will, braucht eine gemeinsame Referenzuhr — NTP-
gestempelte Empfangszeiten aus einem Streaming-Collector, nicht aus Polling."*

Es bleibt also bei zwei Lesarten und keiner Wahl. Wäre es ein echter Vorlauf,
wäre es die erste handelbare Grösse dieser Untersuchung — und genau deshalb
darf sie nicht nach Belieben gelesen werden.

## 5. Abdeckung, ehrlich genannt

Die gemeinsamen 1-Sekunden-Zellen liegen in **1 471 getrennten Blöcken** (BTC)
beziehungsweise 2 756 (ETH). Belegt sind 6,42 h von 24,15 h Spanne (26,6 %)
bzw. 5,89 h von 24,14 h (24,4 %). Gerechnet wird nur über belegte Zellen; die
Spanne ist keine Aufnahmedauer.
