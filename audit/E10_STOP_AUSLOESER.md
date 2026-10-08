# E10 — Ein Stop, der auf einen Schlusskurs wartet, kauft nichts und zahlt am Rand

Reproduktion:

```bash
python scripts/study_stop_trigger.py --markets BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOGEUSDT,BNBUSDT,LTCUSDT,DOTUSDT,ATOMUSDT
```

Angemeldet als Arm E10 am 09.10.2026, vor dem ersten Lauf.
`total_comparisons` 49 → 50, Niveau 99.9000 %.

---

## 1. Woher die Frage kam

Aus einer Zeile im Protokoll des laufenden Papierhandels:

> *„Stop von einem Docht geholt (1 Kerze); die Kerze schloss wieder auf der
> richtigen Seite."*

Das Journal zählt das selbst — `post_mortem.stopped_by_wick`, für alle 2 749
Trades. Nachgesehen:

| | n | Anteil |
|---|---|---|
| Trades im Stop | 1 864 | 67,8 % aller Trades |
| **davon vom Docht geholt, Kerze schloss zurück** | **967** | **51,9 % der Stops, 35,2 % aller Trades** |
| sauber gestoppt | 897 | 48,1 % der Stops |

**Die grösste einzelne Population dieses Projekts, die noch nie als eigene
Politik geprüft wurde.** E3 hat Ausgangs-*Politiken* geprüft (24-Stunden-Uhr,
2,0-ATR-Trail), `study_widen_stop.py` die *Weite* des Stops. Beide lassen den
**Auslöser** unangetastet: der Stop greift bei Berührung. Ein
schlusskurs-bestätigter Stop lässt den Stop, wo er ist, und verlangt eine
Bestätigung. Das ist eine dritte Sache.

## 2. Die Rechnung, die hier nicht gilt

Aus dem Journal lässt sich ausrechnen:

```
  Summe aller R                  -237.7
  Summe der 967 Docht-Stops      -977.3
  Ohne sie:   +739.7 auf 1.782 Trades  =  +0.4151 R je Trade
  Mit ihnen:  -237.7 auf 2.749 Trades  =  -0.0865 R je Trade
```

**Diese Zahl ist bedeutungslos**, und sie steht hier nur, damit niemand sie
später findet und für ein Ergebnis hält. Man darf die Verlierer nicht
entfernen und den Rest behalten. Ein anderer Stop-Auslöser verändert den Pfad
**aller** Trades — auch der 2 256, die ihr Ziel erreichten. Nur ein neu
simulierter Pfad entscheidet.

## 3. Zwei Sicherungen, vorab angemeldet

**Liquidation greift in beiden Armen bei Berührung.** Die Börse wartet auf
keinen Schlusskurs. Ohne das wäre der Arm eine Fiktion, in der man Verluste
aussitzt, die ein echtes Konto nicht aussitzen kann — und der Hebel ist so
gesetzt, dass die Liquidation nur 2,5 Stop-Abstände hinter dem Stop liegt.

**Die Verlustverteilung wird berichtet, nicht nur der Mittelwert.** Ein Stop,
der wartet, kann mehr als 1 R verlieren. Anteil unter −1 R, schlimmster
Einzelverlust und Zahl der Liquidationen gehören in den Bericht.

Diese zweite Sicherung hat den Ausgang entschieden. Siehe Abschnitt 4.

## 4. Das Ergebnis — 7 255 gepaarte Fälle, 12 Märkte

Dieselbe Population wie E3, auf identischen Einstiegen gepaart.

| | Mittel | Haltezeit | unter −1 R | **schlimmster** | 5 %-Quantil |
|---|---|---|---|---|---|
| **E10.1** Stop bei Berührung | −0,0205 R | 14,4 h | 55,0 % | **−1,890 R** | −1,075 R |
| **E10.2** Stop bei Schlusskurs | −0,0141 R | 15,9 h | 50,6 % | **−6,841 R** | **−1,528 R** |

**Gepaarte Differenz: −0,0064 R [−0,0297; +0,0161] — Null enthalten.**

Ausgänge:

| | stop | ziel | zeit | **liquidation** |
|---|---|---|---|---|
| E10.1 | 4 059 | 2 256 | 940 | **0** |
| E10.2 | 3 698 | 2 478 | 1 071 | **8** |

### Beide Tore gefallen

**Tor 1 verfehlt:** das Intervall der gepaarten Differenz enthält die Null,
und der Punktschätzer ist sogar leicht **negativ**.

**Tor 2 verfehlt:** früher −0,0071 R, später +0,0038 R, Verhältnis **−0,54×**
gegen das Band 0,5–2,0. Negativ heisst Vorzeichenwechsel, nicht ein kleines
Mass.

### Und der Rand ist der eigentliche Befund

Der Mittelwert sieht minimal besser aus (−0,0141 gegen −0,0205) — und das
Intervall sagt, dass das nichts ist. Was dafür bezahlt wird, steht rechts:

* Der schlimmste Einzelverlust wächst von **−1,89 auf −6,84 R**, also das
  **3,6-fache**. Bei 1 % Risiko je Trade ist das ein Konto-Einschlag von 6,8 %
  aus einem einzigen Trade — mehr als die harte 3-%-Grenze des Systems
  überhaupt zulässt. Der geplante Verlust wäre nicht mehr der Höchstverlust.
* Das 5 %-Quantil fällt von −1,075 auf **−1,528 R**.
* **Acht Liquidationen**, die die Basis vermieden hat. Jede davon ist der
  Verlust der ganzen Margin, nicht ein Stop.

Hätte ich nur den Mittelwert berichtet, wären +0,0064 R eine Verbesserung
gewesen. Die vorab festgelegte Randberichterstattung ist der Grund, dass die
Antwort eindeutig ist.

## 5. Was es trotzdem beiträgt

**Die bestehende Politik ist zum zweiten Mal messbar besser als die
Alternative.** E3 hat das für zwei Ausgangs-Politiken gezeigt, E10 für den
Auslöser. Das macht das System nicht profitabel, aber es schliesst eine
weitere Richtung, in die zu optimieren wäre — und es ist die Richtung, die ein
Mensch beim Lesen der Nachbetrachtungen zuerst vorschlagen würde, weil 35,2 %
eine grosse Zahl ist.

**Warum der Docht-Stop trotz 35,2 % nichts hergibt:** die Kerze, die
zurückschliesst, sagt nichts darüber, wohin der Preis danach geht. Ein
bestätigter Stop verhindert 361 Stops (4 059 → 3 698) und gewinnt 222 Ziele
(2 256 → 2 478) — aber er verschiebt auch 131 Trades in den Zeitausgang und
kauft diese Verbesserung mit einem Rand, der dreieinhalbmal so weit reicht.

## 6. Grenzen

**Die Bestätigung hängt an der Signalzeitebene.** Gemessen auf M15: der Stop
wartet also bis zu 15 Minuten. Auf H1 wäre der Rand schwerer, auf M1 wäre der
Arm fast die Basis. Die Zeitebene ist nicht variiert worden, und ein anderer
Wert wäre ein neuer Vergleich.

**Die acht Liquidationen sind eine Untergrenze.** Sie entstehen aus dem Hebel,
den das Signal selbst trug (1,0 bis 10,0). Ein Konto, das näher am Maximum
arbeitet, hätte mehr.

**Gebühren wie im Broker:** Einstieg Maker, Ausstieg Taker, ausser am Ziel.
Ein bestätigter Stop verlässt zum Schlusskurs und zahlt Taker — das ist in den
Zahlen enthalten.
