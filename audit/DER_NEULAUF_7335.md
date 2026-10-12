# Der Neulauf: 7.335 Trades, und die Erwartung liegt in ±0,09 R um Null

**Stand 12.10.2026.** 12 Märkte, 2022–2026, Konfiguration wie sie läuft
(Setups A, B, E, F, G; Kadenz M15; Kostendeckel 0,08). Entscheidungsstempel
`e218664b39c8`, alle zwölf Marktergebnisse aus demselben Stand.
Skript `scripts/replay_all_markets.py`, Auswertung
`scripts/eval_replay_rerun.py`, Daten `data/replay_fills/`.

---

## 1. Das Kriterium, das vor dem Lauf stand

| Zeile | | |
|---|---|---|
| C verschwindet | 0 C-Trades (vorher 872) | **erfüllt** |
| E erscheint | 256 E-Trades (vorher 0) | **erfüllt** |
| A, B, G innerhalb ±10 % | siehe unten | **gebrochen** |
| Laufzeit > 15 min je Markt | min 1.189 s, max 33.707 s | **erfüllt** |

Die Vorregistrierung sagte zur dritten Zeile:

> „Bricht die dritte Zeile, ist der Neulauf **nicht vergleichbar** — dann hat
> sich zwischen den beiden Läufen mehr geändert als die Setup-Liste, und die
> Differenz misst nicht, was sie messen soll. Das wäre selbst ein Befund und
> kein Grund, die Zahl trotzdem zu nehmen."

Sie bricht, und zwar zweifach.

**Erstens ein Fehler der Vorregistrierung.** Sie verglich gegen „den alten
Lauf", ohne zu bemerken, dass der alte Lauf im Journal **vier** Märkte
umfasst und der neue zwölf. Über die vollen Populationen ist der Vergleich
sinnlos. Das ist mein Fehler beim Anmelden, nicht ein Befund über das System.

**Zweitens, und das ist der Befund.** Auf den vier gemeinsamen Märkten
gerechnet, also in der einzigen Form, in der die Zeile beantwortbar ist:

| Setup | alt | neu | Delta | Toleranz |
|---|---|---|---|---|
| A | 1.061 | 768 | **−27,6 %** | gebrochen |
| B | 665 | 837 | **+25,9 %** | gebrochen |
| G | 132 | 97 | **−26,5 %** | gebrochen |
| C | 872 | 0 | −100 % | wie geplant |
| E | 0 | 42 | — | wie geplant |

**Alle drei stabilen Setups brechen die Toleranz**, und die Ursache steht in
derselben Tabelle eine Zeile tiefer:

| Zeitebene | alt | neu |
|---|---|---|
| H1 | 1.517 | **592** (−61 %) |
| M15 | 542 | **830** (+53 %) |
| H4 | 559 | 256 |
| D1 | 116 | 77 |

**Die Kadenz hat sich geändert.** Der alte Lauf entschied stündlich, der neue
alle fünfzehn Minuten. Damit wird der M15-Chart viermal so oft befragt, M15-
Setups feuern häufiger und gewinnen den einen Platz öfter — was die
H1-Setups aushungert. Das ist kein Defekt, sondern eine am 09.10. bewusst
behobene Lücke; es macht nur den Vergleich kaputt.

**Folge: die Differenz −0,0906 → −0,0331 R misst nicht die Abschaltung von
Setup C.** Sie misst C-Abschaltung *und* Kadenzwechsel *und* E-Zuschaltung,
verknotet. Die Zahl steht hier, weil die Vorregistrierung verlangt, sie zu
nennen und **nicht** als Konfigurationsvergleich zu lesen.

---

## 2. Was ohne jeden Vergleich gilt

Der Neulauf ist für sich eine Aussage über das System, **wie es heute läuft**.
Dafür braucht er keine Grundlinie.

| | |
|---|---|
| Trades | **7.335** über 12 Märkte, vier Jahre |
| Mittel | **−0,0129 R** je Trade |
| korrigiertes Intervall (Bonferroni, 61 Vergleiche) | **[−0,0868; +0,0594]** |
| Breite | **0,1462 R** |
| Block | 19, 24.401 Ziehungen, Rand belegt |

**Die Erwartung dieses Systems liegt innerhalb von ±0,09 R um Null.**

Das ist die schärfste Schranke, die dieses Projekt je hatte, und sie beendet
zwei Streitpunkte gleichzeitig.

### 2.1 „Die genommene Population ist zuverlässig negativ" — gilt nicht

Diese Aussage hing an t = −3,37 gegen eine korrigierte Schwelle von 3,317,
also knapp, gemessen über vier Märkte, H1-Kadenz, mit Setup C. Ohne C war es
t = −2,02 und damit nicht belegt.

Unter der laufenden Konfiguration über zwölf Märkte: **das Intervall enthält
die Null.** Das System ist nicht nachweisbar ein Verlierer.

### 2.2 Es ist genauso nachweisbar kein Gewinner

Dieselbe Zeile, andere Richtung. 7.335 Trades, und die Null liegt drin. Bei
einer Intervallbreite von 0,146 R ist das keine Frage fehlender Mächtigkeit
mehr — es ist eine gemessene Nullaussage.

### 2.3 Und damit ist die Zielfrage entschieden

`audit/ZIEL_30_10_GERECHNET.md` rechnet aus, dass 12.000 → 15.000 bis zum
30.10. **+6,75 R je Trade** verlangt.

Die **Obergrenze** des Intervalls ist +0,0594 R.

$$\frac{6{,}75}{0{,}0594} \approx \mathbf{114}$$

**Das Ziel liegt Faktor 114 über der Obergrenze dessen, was dieses System
nachweislich kann.** Das ist keine Lücke, die eine Positionsgrösse, ein
Hebel, ein Zeitfilter oder eine Setup-Auswahl schliesst — alle vier ändern
nur, wie viele Trades es gibt oder wie gross sie sind, und das Intervall ist
in R gemessen, also grössenunabhängig.

---

## 3. E12 ist damit abgeschlossen

Die Wochenend-Studie hatte ihre Suchseite auf dem alten Lauf und wartete auf
die Replikation. Die liegt jetzt vor — und der Kadenz-Wächter im Skript hat
sie **verweigert**, aus genau dem Grund aus Abschnitt 1: zwei Läufe mit
verschiedener Entscheidungskadenz sind keine Replikation.

Was sich trotzdem sagen lässt, Zelle für Zelle:

### E12.1 Wochenende — Richtung stabil, Null enthalten

| | alt (4 Märkte, H1) | neu (12 Märkte, M15) |
|---|---|---|
| Sa/So | −0,0956 R (n=516) | −0,0319 R (n=1.488) |
| Mo–Fr | −0,0207 R (n=2.218) | **+0,0270 R** (n=5.847) |
| Differenz | −0,0749 R | −0,0589 R |
| Intervall | [−0,3247; +0,1919] | [−0,2373; +0,1241] |

Beide enthalten die Null. **Aber das Verhältnis der Differenzen ist 0,79×**
— innerhalb des Tors 0,5–2,0, das für eine Replikation gefordert war.

Der Effekt hat also zwei Konfigurationsänderungen überlebt (Kadenz *und*
Setup-Liste), was für sich bemerkenswert ist. Formal bestanden hat er nicht,
und das Tor bleibt verweigert — ein Verhältnis, das zufällig im Fenster
liegt, ersetzt keine gültige Replikation. Als **Richtungsbefund** ist es das
Konsistenteste, was E12 hergegeben hat.

Dazu der Nebenbefund, ebenfalls stabil: der Wochenendanteil der Trades liegt
bei **20,3 %** (alt 18,9 %) gegen 28,6 % Kalender. Das System meidet das
Wochenende weiter, und der Mechanismus ist in
`audit/E12_DIE_UHR.md` ausgemessen — engere Stops, feste Gebühr, Kostendeckel.

### E12.2 Funding-Stunde — geschlossen, negativ

Verhältnis **0,29×**, ausserhalb des Tors, und die neue Differenz ist
−0,0077 R bei einem Intervall von [−0,1646; +0,1497]. Das ist nichts, und es
ist zweimal nichts.

### E12.3 Viertelstundenmarke — erstmals messbar, und negativ

Auf dem alten Lauf war die Zelle nicht entscheidbar: 500 Trades auf `:00`
gegen **zwei** auf einer Viertelstunde, weil die H1-Kadenz den M15-Chart nur
zur Stunde befragte.

Der neue Lauf hat die Besetzung, die die Frage braucht:

| | n | Mittel brutto | unter −1R |
|---|---|---|---|
| `:00` | 649 | +0,0429 R | 61,5 % |
| `:15` / `:30` / `:45` | **2.821** | −0,0109 R | 61,6 % |
| andere Minuten (Limit-Fills) | 147 | *ausgeschlossen* | |

Differenz **+0,0537 R**, Intervall **[−0,1871; +0,2953]** — Null enthalten,
Rand belegt.

**Der Viertelstunden-Effekt aus Kim/Hansen (arXiv:2607.09426) zeigt sich in
unseren Trades nicht als Gruppenunterschied.** Das ist ein saubereres Nein
als vorher: die Zelle ist jetzt richtig besetzt, nicht zu klein.

Was es nicht ausschliesst, und das stand vorher da: die Mechanik des Papiers
ist Orderfluss-Imbalance beim Viertelstunden-Open. Dafür braucht es ein
Trade-Tape, und das hat dieses Buch nicht. Ein Nullergebnis hier schliesst
aus, dass der Effekt bei uns als Gruppenunterschied sichtbar ist — nicht,
dass er existiert.

---

## 4. Was dieser Lauf im Unterschied zum letzten kann

Der Lauf vom 11.10. nachmittags ging sechs Stunden durch und lieferte
Textzusammenfassungen. Dieser liefert pro Trade eine Zeile:

* **7.335 Fills** mit Setup, Zeitebene, Seite, Zeitstempeln, Brutto,
  Gebühren, Funding, risikiertem Betrag, Exitgrund.
* **7.335 Journaleinträge** dazu, mit Rating, Regime, Faktorfamilien und
  Post-Mortem (`bars_held`, `stopped_by_wick`, `max_adverse_r`).
  Anreicherungslücke **0** in allen zwölf Märkten.
* `run_signature`, `signal_timeframe`, `execution_timeframe`,
  `decision_version` und `code_version` — **je Datei und je Eintrag**.

Jede Frage, die der alte 4-Markt-Baseline beantworten konnte, ist jetzt über
zwölf Märkte beantwortbar, ohne neu zu rechnen. Und die Kadenzfalle aus
Abschnitt 1 kann sich nicht wiederholen, weil die Kadenz in jeder Zeile steht
statt aus der Minutenverteilung erschlossen werden zu müssen.

---

## 5. Was als nächstes etwas ändern könnte

Nicht die Suche. 124 Registereinträge liegen auf zwölf Märkten, die nach dem
Versuchsbudget etwa 45 unabhängige Versuche tragen, und der 125. auf
denselben Daten ändert daran nichts.

Was läuft: **71 weitere Märkte** nach einer vor der Liste festgelegten Regel
(Börsenstart vor 2021-10-01), gerade 21 von 83 lokal. Das ist der einzige
Hebel, der die Schranke aus Abschnitt 2 verschieben kann — entweder indem
sie schmaler wird und die Null verlässt, oder indem sie bestätigt, dass dort
nichts ist.

Beide Ausgänge sind brauchbar. Der zweite ist der wahrscheinlichere, und er
wäre immer noch das erste belastbare Ergebnis dieses Projekts.
