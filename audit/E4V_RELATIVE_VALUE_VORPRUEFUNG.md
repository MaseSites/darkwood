# E4V — Der marktbereinigte Querschnitt trägt nichts, und beide Vorzeichen verlieren

Reproduktion:

```bash
python scripts/study_relative_value.py
```

Angemeldet als Arm **E4V** am 09.10.2026, vor dem ersten Lauf.
`total_comparisons` 50 → 52, Niveau 99,9038 %.

---

## 1. Zuerst eine Korrektur an mir selbst: E4 war nie entsperrt

Am 07.10.2026 habe ich E4 von `blockiert` auf `registriert_entsperrt`
gesetzt, weil `build_universe.py` die Punkt-in-Zeit-Tabelle liefert. **Das war
zu schnell.** Die Tabelle nennt, *welche* Symbole wann handelbar waren — sie
liefert keine *Kurse*.

Gemessen aus `data/universe/binance_um_perps.json` (1 062 Einträge, 138 mit
letztem Datentag):

| Stichtag | handelbare Perps |
|---|---|
| 01.06.2022 | 232 |
| 01.06.2023 | 256 |
| 01.06.2024 | 329 |
| 01.06.2025 | 514 |
| 01.06.2026 | **749** |

**Kurse liegen für zwölf Märkte auf der Platte.** Eine Querschnittsstudie
darauf ist keine Studie des Universums, sondern eine Studie der heute
liquidesten Überlebenden — also genau die *„nachträgliche Auswahl der
Gewinner-Coins"*, die E4s `acceptance` ausschliesst.

E4 steht deshalb wieder auf **`blockiert_an_preisen`**. Der echte Blocker sind
Tages- oder Stundenkerzen für das Punkt-in-Zeit-Universum, einschliesslich der
delisteten Symbole aus dem Archiv. Die Universumstabelle war Voraussetzung,
nicht der letzte Schritt.

## 2. Warum dieser Schirm trotzdem gerechnet wurde

Ein Schirm mit einer vorab festgelegten **Asymmetrie**:

* **Negativ ist aussagekräftig.** Die zwölf sind der liquideste, am stärksten
  überlebende Satz, den es gibt. Eine Methode, die dort nichts findet, wird
  durch mehr Symbole nicht besser.
* **Positiv wäre kein Befund**, sondern nur die Rechtfertigung für den
  Kursdownload — weil die Richtung der Survivorship-Verzerrung bei Long/Short
  nicht vorab bestimmt ist.

Er verbraucht **keine** von E4s sechs angemeldeten Zellen.

## 3. Aufbau, und was daran kausal ist

**Faktor** je Stichtag: Querschnittsmittel der Tagesrenditen **desselben**
Tages — am Schluss bekannt. **Beta** je Markt aus einem rückwärtigen Fenster
von 60 Tagen, das am Stichtag *endet*. Ein Beta aus dem ganzen Zeitraum wäre
der klassische Fehler an dieser Stelle: es kennt die Zukunft des Marktes.

**Residuum** = Rendite − β · Faktor. **Signal** = Rang des Residuums,
dollar-neutral, Haltedauer 1 Tag. **Vorzeichen stand vor dem Lauf fest:**
Long das *niedrigste* Residuum (Reversion).

**Kosten:** Taker 0,055 % je Seite auf den gemessenen Umschlag, plus Funding
je gehaltener Position (ein Long zahlt bei positiver Rate).

## 4. Das Ergebnis — 2 221 Tage

| Arm | brutto | Umschlag | Funding | **netto** | |
|---|---|---|---|---|---|
| **E4V.1** Residual-Reversion | −5,20 bp/Tag | 1,30 | −0,06 bp | **−12,43 bp/Tag** [−22,46; −1,33] | **Null AUS** |
| **E4V.2** gleichgewichtet halten *(Kontrolle)* | +20,73 bp/Tag | 1,00 | −2,70 bp | +12,53 bp/Tag [−16,20; +47,56] | Null enthalten |

**Das Intervall des Hauptarms schliesst die Null aus — auf der falschen
Seite.** Das angemeldete Signal verliert zuverlässig.

Die Kontrolle ist das, was sie sein soll: einfaches Halten der zwölf ist
Krypto-Beta und über 2 221 Tage auf diesem Niveau **nicht** von Null zu
unterscheiden.

### Tor 2: der negative Befund repliziert

| Fenster | n | netto |
|---|---|---|
| früher (bis 31.03.2026) | 2 030 | −11,67 bp/Tag [−24,06; +0,41] |
| später (ab 01.04.2026) | 191 | −20,55 bp/Tag [−36,54; −5,28] |

**Verhältnis +1,76× — im Band 0,5–2,0.**

### Kein einzelner Markt trägt es

Jeden Markt einmal ausgelassen, zwölf Wiederholungen:

| | Verschiebung |
|---|---|
| grösste Verbesserung | ohne LTC **+0,96 bp** |
| grösste Verschlechterung | ohne ATOM **−4,11 bp** |

Alle zwölf Varianten bleiben deutlich negativ (−11,47 bis −16,54 bp/Tag). Das
Ergebnis hängt an keinem einzelnen Markt — die Prüfung war vorab als zwingend
angemeldet.

## 5. Und das Spiegelbild verliert auch

Die naheliegende Reaktion auf ein negatives Vorzeichen ist, es umzudrehen:
wenn Reversion verliert, müsste Momentum gewinnen. **Das Vorzeichen nach dem
Ergebnis zu drehen wäre genau der Fehler, gegen den die Vorabregistrierung
existiert** — aber es braucht hier keinen zweiten Lauf, weil die Arithmetik
reicht:

```
  Brutto des Signals (Betrag):   5,20 bp/Tag
  Maut: Umschlag 1,30 × 5,5 bp = 7,15 bp/Tag

  Reversion (angemeldet):  -5,20 - 7,15 = -12,35 bp/Tag
  Momentum (Spiegelbild):  +5,20 - 7,15 =  -1,95 bp/Tag
```

**Die Maut ist grösser als das Brutto, also verlieren beide Vorzeichen.** Der
Querschnitt trägt 5,2 Basispunkte Information je Tag, und eine tägliche
Umschichtung kostet 7,2. Das ist dieselbe Struktur, die dieses Projekt schon
an fünf anderen Stellen gefunden hat: nicht die Richtung ist das Problem,
sondern dass die Richtung kleiner ist als der Weg zu ihr.

**Eine No-Trade-Zone** steht in E4s `requirements` und ist hier bewusst nicht
implementiert: sie überspringt Tage, an denen das erwartete Brutto die Maut
nicht deckt. Bei einem Signal mit negativem Brutto führt das gegen Null, nicht
ins Positive. Sie kann ein falsches Vorzeichen nicht retten, nur seltener
bezahlen.

## 6. Die Entscheidung, die daraus folgt

Nach der vorab festgelegten Asymmetrie: **negativ auf dem Überlebenden-Satz
heisst, E4 bleibt blockiert und der grosse Kursdownload unterbleibt.**

Konkret eingespart: Tages- oder Stundenkerzen für 232 bis 749 Symbole über
mehrere Jahre, plus die Archivbeschaffung für 138 delistete. Das ist der
grösste Einzelbau, der im Forschungsplan noch offenstand, und er ist durch
eine Messung von einer Minute Laufzeit nicht mehr zu rechtfertigen.

## 7. Grenzen

**Ein Horizont, ein Signal.** Haltedauer 1 Tag, Rang des Residuums. Andere
Horizonte und andere Residualsignale sind nicht geprüft; jeder wäre ein
eigener Vergleich. Was die Arithmetik in Abschnitt 5 **nicht** ausschliesst,
ist ein Signal mit deutlich grösserem Brutto oder deutlich kleinerem Umschlag
— genau dort läge die nächste Frage, wenn sie jemand stellen will.

**Dollar-neutral ist nicht beta-neutral.** Diese Falle steht in E4s
`pitfalls_declared` und bleibt offen: die Gewichte summieren sich zu null in
Dollar, nicht im Beta. Ein Restbeta würde im Brutto mitlaufen.

**Zwölf korrelierte Märkte sind nicht zwölf Beobachtungen.** Das Intervall ist
über die Zeitreihe der Portfoliorenditen gerechnet, nicht über Markt-Paare —
das war vorab festgelegt.

**Die Beta-Fensterlänge von 60 Tagen** stand vor dem Lauf fest und wurde nicht
variiert. Ein zweiter Wert wäre ein zweiter Vergleich.
