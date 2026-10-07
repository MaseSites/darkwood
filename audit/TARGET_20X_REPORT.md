# 1 000 → 20 000 CHF in sechs Monaten: Zielchance neben Verlustchance

**Stand:** 07.10.2026 · **Reproduktion:** `python scripts/study_target_20x.py --paths 20000`
**Fenster:** 07.10.2026 bis 07.04.2027, 182 Tage · **Seed:** 20261007

Der Forschungsauftrag verlangt in Abschnitt 12 ausdrücklich keine ausgewählte
20×-Kurve, sondern eine Verteilung mit der Zielchance **neben** der
Verlustchance. Das ist hier gerechnet, mit 20 000 Pfaden aus den gemessenen
R-Werten des Journals, in Wochenblöcken gezogen.

**Alle Wahrscheinlichkeiten unten sind modellbedingt.** 20 000 synthetische
Pfade sind nicht 20 000 neue Marktphasen; das Monte-Carlo-Intervall deckt die
Ziehunsicherheit, nicht die Modellunsicherheit. Gestützt werden sie erst durch
Vorwärtsdaten, und davon gibt es acht Trades.

---

## 1. Die eine Zahl, die alles zusammenfasst

Bei 2,27 Trades am Tag über 182 Tage — **413 Trades** — verlangt das Ziel:

| Risiko je Trade | nötiges mittleres R | nötige Trefferquote¹ | Lücke zur Messung |
|---|---:|---:|---:|
| 0,5 % | **+1,456 R** | 87,25 % | +54,8 Pp |
| 1,0 % | **+0,728 R** | 61,47 % | +29,0 Pp |
| 2,0 % | **+0,364 R** | 48,58 % | +16,1 Pp |
| 3,0 % (harter Deckel) | **+0,243 R** | 44,29 % | +11,8 Pp |

¹ bei der gemessenen Auszahlung +1,816 R / −1,008 R über 2 734 Replay-Trades.
Gemessene Trefferquote: **32,48 %**.

Daneben zum Vergleich:

| Grösse | Wert |
|---|---:|
| Register-Champion | **−0,0340 R** |
| Gemessene Replay-Verteilung | **−0,0906 R** |
| Mittleres **geplantes** Chance-Risiko | +2,15 R |

Das mittlere geplante Chance-Risiko ist die Obergrenze **unter dem
festgelegten Auszahlungsschema** — was herauskäme, wenn jeder Trade sein Ziel
träfe und keiner seinen Stop. Die nötigen +0,243 R bei 3 % Risiko sind also
**11,3 %** dieser Obergrenze, nicht mehr als das physikalisch Mögliche.

**Das Ziel ist damit nicht arithmetisch ausgeschlossen.** Es verlangt bei 3 %
Risiko eine Trefferquote von 44,3 % gegen gemessene 32,5 % — eine Lücke von
11,8 Prozentpunkten. Das ist eine andere Aussage als beim alten Ziel, wo das
Verlangte das 2,3-fache des Möglichen war.

Jede dieser Zahlen ist durch Jensen eine **Untergrenze**: echte R-Werte
streuen, und `E[ln(1+fR)] < ln(1+f·E[R])`.

---

## 2. Zielchance und Verlustchance, 20 000 Pfade

| Szenario | Ziel am Ende | Ziel irgendwann | < Start | ≤ 500 | ≤ 200 | Liquidation | Median | CVaR 5 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **gemessen, 0,5 %** | 0,00 % | 0,00 % | 88,6 % | 0,1 % | 0,0 % | 0,0 % | 819 | 594 |
| **gemessen, 1 %** | 0,00 % | 0,00 % | 89,7 % | 26,1 % | 0,0 % | 0,0 % | 657 | 347 |
| **gemessen, 2 %** | 0,00 % | 0,00 % | 91,7 % | 75,8 % | 18,4 % | 0,0 % | 399 | 113 |
| **gemessen, 3 %** | 0,01 % | 0,01 % | 93,4 % | 89,8 % | **55,5 %** | 0,0 % | 224 | 35 |
| gemessen, 5 % *(nur Stress)* | 0,04 % | 0,12 % | 96,0 % | 97,0 % | **87,2 %** | 0,0 % | 56 | 3 |
| Hebel 1×, 1 % | 0,00 % | 0,00 % | 89,7 % | 26,1 % | 0,0 % | 0,0 % | 657 | 347 |
| Hebel 3×, 1 % | 0,00 % | 0,00 % | 89,7 % | 26,1 % | 0,0 % | 0,0 % | 657 | 347 |
| Hebel 5×, 1 % | 0,00 % | 0,00 % | 91,0 % | 28,8 % | 0,0 % | **37,1 %** | 639 | 336 |
| Hebel 10×, 1 % | 0,00 % | 0,00 % | 99,1 % | 79,4 % | 8,2 % | **98,3 %** | 387 | 153 |
| Hebel 15×, 1 % | 0,00 % | 0,00 % | 100,0 % | 99,9 % | 95,8 % | **100,0 %** | 59 | 10 |
| *Hypothese* +0,05 R | 0,00 % | 0,00 % | 73,9 % | 10,0 % | 0,0 % | 0,0 % | 808 | 427 |
| *Hypothese* +0,10 R | 0,00 % | 0,00 % | 50,8 % | 2,6 % | 0,0 % | 0,0 % | 994 | 525 |
| *Hypothese* +0,20 R | 0,00 % | 0,00 % | 10,1 % | 0,1 % | 0,0 % | 0,0 % | 1 501 | 793 |
| *Hypothese* +0,40 R | 0,00 % | 0,00 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 3 424 | 1 812 |
| Vorteil halbiert, Kosten ×1,5 | 0,00 % | 0,00 % | 88,7 % | 24,3 % | 0,0 % | 0,0 % | 670 | 354 |
| Korrelation erhöht (Streuung ×1,5) | 0,00 % | 0,00 % | 82,9 % | 44,1 % | 1,0 % | 0,0 % | 624 | 241 |
| Feed-/Orderausfall 10 % | 0,00 % | 0,00 % | 88,3 % | 19,4 % | 0,0 % | 0,0 % | 689 | 378 |

### Quantile des Endkapitals, CHF

| Szenario | 5 % | 25 % | 50 % | 75 % | 95 % |
|---|---:|---:|---:|---:|---:|
| gemessen, 0,5 % | 632 | 735 | 819 | 916 | 1 080 |
| gemessen, 1 % | 392 | 530 | 657 | 822 | 1 142 |
| gemessen, 2 % | 143 | 260 | 399 | 622 | 1 198 |
| gemessen, 3 % | 48 | 118 | 224 | 435 | 1 154 |
| gemessen, 5 % *(Stress)* | 4 | 20 | 56 | 168 | 835 |
| Hebel 10×, 1 % | 185 | 289 | 387 | 510 | 746 |
| Hebel 15×, 1 % | 14 | 34 | 59 | 100 | 200 |
| *Hypothese* +0,20 R | 896 | 1 210 | 1 501 | 1 877 | 2 606 |
| *Hypothese* +0,40 R | 2 044 | 2 762 | 3 424 | 4 278 | 5 937 |

---

## 3. Was die Tabelle sagt

**Auf der gemessenen Verteilung ist die Zielchance null, bei jedem Risiko.**
Das 95-%-Quantil bei 1 % Risiko ist 1 142 CHF. Die besten fünf Prozent aller
Pfade enden also bei 14 % Gewinn, nicht bei 1 900 %.

**Mehr Risiko erhöht die Ruinchance schneller als die Zielchance.** Von 1 % auf
3 % steigt „unter 200 CHF" von 0,0 % auf **55,5 %**, während die Zielchance von
0,00 % auf 0,01 % steigt. Das ist kein Urteil, sondern was Log-Wachstum bei
negativem Drift tut: der Hebel wirkt auf beide Enden, und das untere ist näher.

**Selbst ein unterstellter Vorteil von +0,40 R je Trade erreicht das Ziel
nicht.** Der Median endet bei 3 424 CHF. Zum Einordnen: +0,40 R ist das
Zwölffache dessen, was der Register-Champion liefert — und mit umgekehrtem
Vorzeichen. Nötig wären +0,728 R bei 1 % Risiko.

### Der Hebel, und was er wirklich tut

**Bis 3× ändert er nichts.** Das ist kein Modellartefakt, sondern die Folge der
Konfiguration: bei stopbasiertem Sizing ist die Positionsgrösse durch
`Risiko / Stop-Abstand` bestimmt, und der Hebel steuert nur Margin und
Liquidationsabstand. `config/risk.yaml` wählt ihn so, dass die Liquidation
mindestens 2,5 Stop-Abstände dahinter liegt — darunter greift immer der Stop
zuerst.

Ab 5× kippt es, und zwar schnell:

| Hebel | Liquidationsabstand | in R des Median-Stops | Pfade mit Liquidation |
|---|---:|---:|---:|
| 1× | 99,500 % | 76,01 R | 0,0 % |
| 3× | 32,833 % | 25,08 R | 0,0 % |
| 5× | 19,500 % | 14,90 R | **37,1 %** |
| 10× | 9,500 % | 7,26 R | **98,3 %** |
| 15× | 6,167 % | 4,71 R | **100,0 %** |

Der Sprung von 3× auf 5× kommt nicht vom Median-Stop (1,309 %), sondern vom
**Rand der Stop-Verteilung**: das 95-%-Quantil liegt bei 5,38 %, und ein Stop
dieser Breite bei 5× Hebel bringt die Liquidation in Reichweite.

**Und die Zielchance bleibt bei jedem Hebel 0,00 %.** Der Hebel verschiebt
Kapital nicht nach oben, er verkürzt nur den Weg nach unten. Ein 10×-Lauf ist
kein Vorschlag, zehnmal das Konto zu riskieren — er ist die Messung, dass 98,3 %
der Pfade dabei mindestens einmal liquidiert werden.

---

## 4. Was diese Rechnung nicht kann

**Sie erfindet keinen Vorteil.** Gezogen wird aus gemessenen R-Werten mit
negativem Mittel. Jedes Szenario mit `Vorteil +x R` ist eine **Hypothese** und
trägt den unterstellten Wert im Namen. Kein Arm von 87 im Register hat ein
Intervall, das die Null ausschliesst.

**Replay und Vorwärts sind getrennt.** Dieser Lauf nutzt die 2 734
Replay-Trades. Die acht Vorwärts-Trades sind zu wenige für eine eigene
Verteilung (`--source live` verlangt mindestens acht Wochenblöcke und bricht
darunter ab, statt eine Zahl zu liefern).

**Drei Grössen fehlen im Modell und sind als offen markiert:**

1. **Gleichzeitigkeit.** Die Simulation zieht Trades sequenziell. Das echte
   System hält bis zu zwei Positionen gleichzeitig, und gemeinsame Verluste
   treffen härter als die Blockziehung abbildet. Szenario „Streuung ×1,5" ist
   eine Näherung dafür, keine Modellierung.
2. **Gap-Risiko über den Stop hinaus.** Gemessen füllen **83 %** der Stops
   schlechter als −1 R, Median 1,079 R, Maximum **2,527 R**. Das steckt in den
   gezogenen R-Werten drin. Ein Gap, das grösser ist als alles Beobachtete,
   steckt nicht drin.
3. **Laufende Kosten.** Heute 0 CHF, weil nur lokale Ressourcen und freie
   Archive benutzt werden. Bei 1 000 CHF Startkapital ist das keine Fussnote:
   **50 CHF im Monat wären 300 CHF über sechs Monate, also 30 % des Kapitals.**
   Jeder bezahlte Dienst gehört in diese Zeile, bevor er läuft.

---

## 5. Eine Datenkorrektur, die diese Rechnung erst möglich gemacht hat

Der erste Lauf meldete bei **1× Hebel** 25,2 % liquidierte Pfade. Das ist
unmöglich — bei 1× müsste der Preis auf null fallen.

Die Ursache war ein Defekt im gespeicherten Journal: `max_adverse_r` wurde über
alle Kerzen gelesen, die den Trade *überlappen*, also einschliesslich der
Bewegung **nach dem Ausstieg** in der Abschlusskerze und **vor dem Einstieg** in
der Eröffnungskerze. Gemessen: Werte bis **147,88 R** auf einem Trade, der nach
`bars_held = 1` bei −0,036 R ausgestoppt wurde; **25,3 %** der ausgestoppten
Trades über 1,6 R, was ein bei −1 R geschlossener Trade nicht erlebt haben kann.

`journal/postmortem.py` ist korrigiert: es liest nur noch die vollständig
inneren Kerzen und bindet die Ränder an Einstiegs- und Ausstiegspreis. Zwei
Tests halten beide Ränder fest. Die gespeicherten Zeilen stammen von davor, also
arbeitet die Simulation mit einer Schranke, die den Ausgang nutzt statt des
Feldes:

> Ein Trade, der **nicht** ausgestoppt wurde, hat seinen Stop nie erreicht —
> also unter 1 R Gegenbewegung. Einer, der **ausgestoppt** wurde, erreichte ihn
> genau, plus die Slippage, die im realisierten R steht.

Das ist keine Schätzung, sondern das, was der Ausgang zulässt.

---

## 6. Die Entscheidung

**Kein Szenario auf der gemessenen Verteilung erreicht das Ziel.** Die beste
Zielchance über alle gemessenen Risikoprofile ist **0,04 %**, und sie gehört zum
5-%-Risiko-Stressarm, der zugleich in **87,2 %** der Pfade unter 200 CHF fällt.

**Das Ziel ist deshalb nicht als unmöglich zu bezeichnen, sondern als
unbelegt.** Es verlangt bei 3 % Risiko +0,243 R je Trade — 11,3 % der Obergrenze
unter dem geplanten Auszahlungsschema, und 11,8 Prozentpunkte Trefferquote über
dem Gemessenen. Ob ein Arm das liefert, entscheidet E0–E7 und nicht diese
Simulation.

**Was diese Simulation entscheidet, ist etwas anderes und Nützliches:** Der
Hebel ist kein Weg dorthin. Er lässt die Zielchance bei null und bringt ab 5×
die Liquidation in Reichweite. Und mehr Risiko ist ebenfalls kein Weg: es
bewegt die Ruinchance um Grössenordnungen und die Zielchance um Hundertstel
eines Prozents.

**Die harte Grenze von 3 % bleibt, und die Rechnung stützt sie**, statt sie nur
zu erben: bei 3 % fallen bereits 55,5 % der Pfade unter 200 CHF, ohne dass die
Zielchance messbar steigt.
