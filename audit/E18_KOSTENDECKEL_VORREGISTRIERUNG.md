# E18 — Kostendeckel, vorregistriert

**Geschrieben am 19.10.2026, BEVOR der Out-of-Sample-Teil gerechnet wurde.**
Diese Datei existiert, damit die Auswahlregel nicht nachträglich zur
gefundenen Zahl passt.

---

## Die Beobachtung, die den Verdacht auslöst

Im Experimentregister stehen sechs Kostendeckel. Die Erwartung je Trade fällt
fast monoton, je lockerer der Deckel:

| Deckel | n | Mittel R | Anteil der Signale | R gesamt |
|---|---|---|---|---|
| 0,03 | 167 | +0,1052 | 10,0 % | +17,6 |
| 0,04 | 275 | +0,1148 | 16,5 % | +31,6 |
| 0,06 | 514 | +0,0394 | 30,9 % | +20,2 |
| 0,08 *(produktiv)* | 786 | +0,0360 | 47,2 % | +28,3 |
| 0,10 | 1057 | −0,0065 | 63,5 % | −6,9 |
| 0,12 | 1298 | +0,0135 | 78,0 % | +17,5 |

Das deckt sich mit einem unabhängig gemessenen Befund: **billige Trades sind
brutto besser** (+0,0561 R, Intervall ohne null, über zwölf Märkte).

**Warum das noch kein Ergebnis ist.** Sechs Werte zu probieren und den besten
zu nehmen, ist eine Auswahl aus sechs Vergleichen. Alle sechs Intervalle
schliessen die Null ein; bei 0,04 nur knapp ([−0,011, +0,241]), und mit
Bonferroni über sechs Vergleiche wird daraus etwa [−0,057, +0,287]. Ausserdem
sind diese Zahlen auf **derselben** Population gemessen, aus der der Deckel
gewählt würde.

---

## Die Regel, festgeschrieben

**Aufteilung.** Die 7.335 Replay-Fills werden **nach Zeit** geteilt, nicht
zufällig: die ersten 70 % der Kalenderspanne sind *Auswahlmenge*, die letzten
30 % sind **gesperrt** und werden genau einmal angefasst.

Zeitlich und nicht zufällig, weil eine zufällige Teilung Trades derselben
Woche auf beide Seiten legt — und ein gemeinsamer Wochenfaktor trägt gemessen
96,9 % der Struktur. Eine zufällige Teilung würde also die Antwort über die
Grenze schmuggeln.

**Kandidaten.** Genau die sechs Deckel oben, nichts dazwischen, nichts
daneben. Keine zweite Dimension.

**Auswahlregel, vor dem Rechnen festgelegt.** Gewählt wird der Deckel mit der
höchsten **Gesamtsumme in R** auf der Auswahlmenge — nicht die höchste
Erwartung je Trade.

Begründung: die Erwartung je Trade belohnt ein Verfahren, das fast nichts
nimmt. Bei Deckel 0,01 bliebe vielleicht ein einziger sehr guter Trade übrig,
und die Erwartung wäre spektakulär. Die Summe fragt nach dem, worauf es
ankommt: wie viel am Ende dasteht.

**Der Test.** Der *eine* so gewählte Deckel wird **einmal** auf der gesperrten
Menge gerechnet. Kein zweiter Lauf, keine Nachjustierung, kein „wir schauen
nur mal".

**Das Erfolgskriterium, vor dem Lauf.** Der gewählte Deckel gilt als
bestätigt, wenn auf der gesperrten Menge **beides** gilt:

1. Die Erwartung je Trade ist **grösser als die des produktiven Deckels 0,08**
   auf derselben gesperrten Menge. (Der richtige Vergleich ist gegen das, was
   das System ohnehin tut — nicht gegen null und nicht gegen alle Signale.)
2. Das **zwei-weg geclusterte** 95-%-Intervall dieser Differenz schliesst die
   Null aus.

Zwei-weg geclustert (Markt UND Zeit) und nicht nur nach Markt, weil am
19.10.2026 gemessen wurde, dass Markt-Clustering nur 0,682 der wahren Streuung
erfasst.

**Was ein Scheitern bedeutet.** Fällt eines der beiden Kriterien, ist der
Kostendeckel als Hebel erledigt und wird nicht erneut variiert. Kein „fast",
kein „mit mehr Daten vielleicht". Der produktive Deckel bleibt bei 0,08.

**Was ein Erfolg NICHT bedeutet.** Auch ein bestätigter Deckel erreicht die
20× nicht — die Schranke liegt bei +0,1851 R, und selbst +0,1148 ist knapp
die Hälfte bei einem Fünftel der Trades. Was er bedeuten würde, ist etwas
anderes und für dieses Projekt Neues: **die erste out-of-sample bestätigte
positive Kante nach Kosten.**

---

## Was vorher gemessen ist und beim Lesen dazugehört

* Erwartung der Gesamtpopulation: −0,0129 R, 95 % [−0,0513, +0,0387]
  (zwei-weg geclustert). Schliesst die Null ein.
* 124 eingetragene Arme; 12 schliessen die Null aus, **alle zwölf negativ**.
* Die Schranke für 20× in 182 Tagen: +0,1851 R bei N=312.
* Das Kostentor lehnt beim produktiven Deckel 48 % aller Signale ab und ist
  damit die bindendste Regel des Systems.
