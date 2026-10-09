# E4W — Die Maut fällt um Faktor 5, das Brutto nicht. Und es reicht trotzdem nicht.

Reproduktion:

```bash
python scripts/study_relative_value.py --hold 1    # E4V, zur Gegenprobe
python scripts/study_relative_value.py --hold 5    # E4W
```

Angemeldet als Arm **E4W** am 09.10.2026, vor dem ersten Lauf.
`total_comparisons` 52 → 55, Niveau 99,9091 %.

---

## 1. Woher die Frage kam, und sie stand vorher da

E4V hat gemessen: Brutto 5,20 bp/Tag gegen eine Maut von 7,15 bp/Tag. Der
Bericht hat ausdrücklich notiert, was die Arithmetik **nicht** ausschliesst:

> *„ein Signal mit deutlich grösserem Brutto oder deutlich kleinerem
> Umschlag — genau dort läge die nächste Frage, wenn sie jemand stellen
> will."*

Der Umschlag ist die Seite, die sich ohne neue Daten ändern lässt. Bei
wöchentlicher statt täglicher Umschichtung fällt die Maut auf ein Fünftel.

**Beide Vorzeichen wurden vorab angemeldet.** E4V hatte Reversion festgelegt
und verloren; es jetzt auf Momentum zu drehen wäre genau der Fehler, gegen den
die Vorabregistrierung existiert. Tägliche Reversion und wöchentliches
Momentum sind verschiedene Phänomene, und welches auf diesem Horizont trägt,
wusste ich nicht.

**Gegenprobe zuerst:** `--hold 1` reproduziert E4V auf die zweite Dezimale
(−12,43 bp/Tag). Der Umbau auf einen Horizontparameter hat die alte Rechnung
nicht verändert.

## 2. Was die kleinere Maut gebracht hat

| | Brutto | Maut | netto Reversion | netto Momentum |
|---|---|---|---|---|
| **E4V** täglich | 5,20 bp/Tag | **7,15 bp/Tag** | −12,35 | −1,95 |
| **E4W** wöchentlich | 6,72 bp/Tag | **1,44 bp/Tag** | −8,16 | **+5,28** |

**Die Maut fällt um Faktor 5. Das Brutto fällt nicht — es steigt leicht.**

Und damit ist die Tötungsbedingung, die ich vorab festgelegt hatte, **nicht
erfüllt**:

> *„Fällt das Brutto proportional zum Umschlag, ist die Sache erledigt — dann
> trägt der Querschnitt eine Information je Umschichtung und nicht je Zeit,
> und kein Horizont rettet sie."*

Es fällt nicht proportional. **Der Querschnitt trägt Information je Zeit.**
Das ist das erste Mal in diesem Projekt, dass eine Kostenreduktion nicht
sofort von einem schrumpfenden Brutto aufgefressen wird.

## 3. Und beide Tore fallen trotzdem

| Arm | netto | Intervall | |
|---|---|---|---|
| **E4W.1** Reversion | −8,20 bp/Tag | [−21,09; +3,26] | Null enthalten |
| **E4W.2** Momentum | **+5,33 bp/Tag** | [−6,21; +18,27] | Null enthalten |
| **E4W.3** Kontrolle | +19,75 bp/Tag | [−14,20; +61,86] | Null enthalten |

**Tor 1 verfehlt für alle drei.** Und der Grund ist nicht das Vorzeichen,
sondern die **Stichprobe**: 442 Umschichtungen statt 2 221 Tagen. Ein längerer
Horizont kauft eine kleinere Maut mit weniger unabhängigen Beobachtungen, und
das Intervall wird entsprechend breit — bei E4V war es 21 bp weit, hier 24 bp
bei einem fünfmal kleineren Effekt.

**Tor 2 verfehlt:** früher −9,33 bp/Tag, später +3,73, Verhältnis **−0,40×**.
Vorzeichenwechsel.

**Kein einzelner Markt trägt es:** jeden einmal ausgelassen, −4,99 bis −9,60
bp/Tag, grösste Verschiebung +3,21 bp (ohne AVAX).

## 4. Was die Zahl wert wäre, wenn sie echt wäre

Das ist die Rechnung, die den Fall abschliesst. **+5,33 bp/Tag** für echt
genommen, über das Zielfenster:

```
  (1 + 0,000533) ^ 182  =  1,102x   ->   1.000 CHF werden 1.102 CHF
```

**Das Ziel verlangt 20 000.** Der beste Punktschätzer, den dieser Querschnitt
hergibt — ein Punktschätzer, dessen Intervall die Null enthält und dessen
Vorzeichen zwischen den Fenstern kippt — ergäbe über sechs Monate **plus zehn
Prozent**.

Das ist die Grössenordnung, um die es hier geht. Nicht „noch nicht ganz", sondern
zwei Zehnerpotenzen.

## 5. Befund

**Negativ auf beiden Toren.** Und trotzdem der informativste negative Befund
seit E8, weil er eine Struktur verändert:

* **Die Maut ist auf diesem Horizont nicht mehr die bindende Grösse.** Sie
  fiel um Faktor 5, und das Brutto blieb. Alle früheren Befunde dieses
  Projekts endeten bei „die Maut ist grösser als das Signal" — dieser nicht.
* **Bindend ist jetzt die Stichprobe.** 442 Umschichtungen reichen nicht, um
  5 bp/Tag von Null zu trennen. Mehr Daten würden hier helfen, wo sie bei
  E4V nichts geholfen hätten.
* **Und es hilft nichts.** Selbst das volle Signal, für echt genommen, ist vom
  Ziel um den Faktor 180 entfernt.

**Was NICHT behauptet wird:** dass Momentum auf fünf Tagen funktioniert. Das
Intervall enthält die Null, das Vorzeichen kippt zwischen den Fenstern, und
derselbe Querschnitt hatte auf einem Tag das umgekehrte Vorzeichen. Beide
Vorzeichen waren vorab angemeldet, damit genau diese Versuchung nicht greift.

## 6. Grenzen

**Derselbe Überlebenden-Satz wie E4V.** Zwölf Märkte mit Kursen, während zu
jedem Zeitpunkt 232 bis 749 Perps handelbar waren. Ein positives Ergebnis wäre
hier kein Befund gewesen, sondern die Rechtfertigung für den Kursdownload —
und es ist keines geworden.

**Ein Horizont, nicht variiert.** Fünf Tage standen vorab fest. Dass 10 oder
20 Tage anders aussähen, ist möglich und jeweils ein eigener Vergleich. Was
diese Messung dazu sagt: die Maut wäre dort noch kleiner und die Stichprobe
noch dünner — der Engpass verschiebt sich weiter in die Richtung, die hier
schon bindet.

**Dollar-neutral ist nicht beta-neutral.** Unverändert offen aus E4s
`pitfalls_declared`.

**Die Kontrolle ist mitgewachsen.** +19,75 bp/Tag für einfaches Halten, auch
mit Intervall über Null. Dass sie grösser aussieht als beide aktiven Arme, ist
Krypto-Beta über 442 Fünftagesfenster und keine Aussage über eine Strategie.
