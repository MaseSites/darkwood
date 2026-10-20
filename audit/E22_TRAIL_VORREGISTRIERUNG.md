# E22 — Trailing-Ausstieg: „raus, sobald er dreht"

**Vorregistriert am 20.10.2026, bevor der Arm gerechnet wurde.**
Angemeldet auf Vorschlag des Nutzers nach dem ersten Trade des offenen
Plankontos.

---

## 1. Woher die Frage kommt

LTCUSDT short, 20.10., 13:30–14:25. Der Trade stand nach sechs Minuten
**+1.03 R im Gewinn**, drehte dann und starb in der 56. von 56 Minuten an
einem Docht. Ergebnis −1.2028 R.

Der Vorschlag: aussteigen, sobald sich der Trade dreht, statt bis zum Stop zu
warten. „Dann hätten wir halt nur 10 Franken plus gemacht, aber besser als
10 minus."

**Am echten Minutenpfad nachgerechnet** (nicht geschätzt — Kerzen von der
Börse, Trail folgt dem Tiefstkurs):

| Rückgabe G | Ausstieg | Ergebnis |
|---|---|---|
| 0.20 R | 13:36 bei 58.318 | **+0.631 R** |
| 0.30 R | 13:37 bei 58.347 | +0.531 R |
| 0.50 R | 13:38 bei 58.405 | +0.331 R |
| 0.75 R | 13:41 bei 58.477 | +0.081 R |
| 1.00 R | 13:45 bei 58.550 | −0.169 R |

Für **diesen** Trade stimmt es also. Die Frage ist, ob es im Mittel hilft.

## 2. Was schon gemessen ist, und was nicht

| Arm | Mechanismus | Ergebnis |
|---|---|---|
| E14 | Stop auf **Einstand** bei 1.0 / 0.5 R | gefallen, **monoton schlechter** je früher |
| E15 | Ziel auf 1 / 1.5 / 2 R herein | alle drei gefallen |
| E10 | schlusskurs-bestätigter Stop | Mittel besser, **grösster Verlust verdreifacht** |
| E3.3 | Stop + **2.0-ATR-Trail** | −0.0557 R [−0.1123, −0.0060], zuverlässig negativ |

**Die Lücke:** E14 zieht den Stop EINMAL auf den Einstand und lässt ihn dort.
E3.3 trailt in ATR-Einheiten und griff in 99 % der Fälle, ersetzte also die
Ziel-Tür. Ein Trail mit Rückgabe **in R des eigenen Stops**, der dem
Höchststand folgt, ist in dieser Form nie mit vollständiger Pfadsimulation
geprüft worden. E3 notiert selbst: *„Die 2,0 ATR sind vorab festgelegt und
wurden nicht nachjustiert. Ein anderer Trail-Abstand könnte besser
abschneiden."*

## 3. Ein Abkürzungsversuch, der gescheitert ist — und warum er hier steht

Um schnell zu antworten, habe ich den Trail aus `post_mortem.max_favourable_r`
geschätzt: Ausstieg bei `MFE − G`. Ergebnis: **+1.07 R je Trade** statt
−0.088 R, also eine Verzwölffachung.

**Das ist kein Ergebnis, sondern ein Artefakt**, und die Zahl war zu gut, um
sie zu glauben. `max_favourable_r` sagt, WIE WEIT der Kurs günstig lief, nicht
WANN. Die Rechnung unterstellt, er sei geradewegs bis zum Höchststand gelaufen
und erst dann um G zurückgekommen — der günstigste denkbare Pfad. Ein enger
Trail greift aber beim ERSTEN kleinen Rückschlag, lange vor dem Maximum.
84 % der Verlierer haben MFE > 0.1 R, also hat die Rechnung fast jeden
Verlierer „gerettet".

Festgehalten, damit niemand die Tabelle später findet und für eine Messung
hält. Nur ein neu simulierter Pfad entscheidet — dieselbe Lehre, die
`audit/E10_STOP_AUSLOESER.md` schon einmal aufgeschrieben hat.

## 4. Der Arm, vorab und unveränderlich

Neues Simulatorfeld `trail_giveback_r`, als Verallgemeinerung von
`breakeven_at_r`: der Stop folgt dem günstigsten erreichten Punkt im Abstand
`G * risk_price` und wird nie zurückgenommen.

**Zellen:** G ∈ {0.25, 0.50, 0.75, 1.00}. Vier Stück, nicht mehr — jede
weitere Zelle verschärft die Korrektur, ohne die Frage zu schärfen.

**Zwei Sicherungen, aus E3 übernommen:**
* Liquidation greift bei Berührung, nicht auf Schlusskurs. Die Börse wartet
  auf keinen.
* Der Trail darf den Stop nur in die günstige Richtung bewegen.

## 5. Die Tore, vorab

**TOR 1** — Das Bonferroni-korrigierte Intervall der Differenz zur Basis
schliesst null aus, auf `total_comparisons` des Registers (dann 77 statt 73,
weil vier Zellen hinzukommen). Zweiwegig geclustert nach Markt UND
7-Tage-Block.

**TOR 2** — Wiederholung in [0.5, 2.0] auf den 56 ungesehenen Märkten, sobald
E17 sie geliefert hat. Das Band wird nach Kenntnis des Ergebnisses nicht
geändert.

**ABSOLUT, nicht relativ:** Der Champion ist mit −0.0340 R negativ. Ein
kleinerer Verlust ist kein Gewinn. Der Arm muss über null liegen.

## 6. Der Schwanz, vorab erklärt

Berichtet werden immer, auch bei bestandenen Toren:
**grösster Einzelverlust**, Anteil der Trades, die vor dem Ziel abgeschnitten
wurden, und die mittlere Haltedauer.

Das ist die Lehre aus E10: dort verbesserte sich der Mittelwert und der
grösste Verlust verdreifachte sich. Ein Trail hat den umgekehrten Verdacht —
er dürfte den grössten Verlust senken und dafür die Gewinner köpfen. Genau
deshalb steht „Anteil vor dem Ziel abgeschnitten" hier VOR dem Lauf.

## 7. Was diesen Arm scheitern liesse, und es ist das Wahrscheinlichste

Wenn der Trail die Gewinner köpft. Die Auszahlung ist fest: Gewinner tragen
rund +1.48 R, Verlierer −1.05 R. Ein Trail, der die Verlierer auf −0.3 R
drückt und dafür jeden dritten Gewinner bei +0.6 R abschneidet, verliert mehr
als er rettet. E3.3 ist genau daran gescheitert (Trail greift in 99 %).

**Gerechnet wird erst, wenn E17 durch ist.** Der Replay liest `sim/broker.py`;
eine Änderung jetzt und ein Strang-Neustart danach verteilten zehn Stunden
Rechnung auf zwei Codestände.
