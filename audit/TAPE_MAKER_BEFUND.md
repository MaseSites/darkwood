# Der erste Befund, der beide Tore passiert — und warum er trotzdem kein Ertrag ist

Reproduktion:

```bash
python scripts/collect_venue_tape.py --hours 11     # nimmt auf
python scripts/study_tape_fills.py --markets BTC     # misst
```

**Zuerst der Vorbehalt, weil er die ganze Lesart bestimmt.** Was hier
gemessen wird, sind **die Orders anderer Leute**. Ihre Fills bei günstigem
Markout spiegeln *ihre* Warteschlangenposition, *ihre* Storno-Logik, *ihre*
Latenz. Dass meine Orders sich genauso verhalten würden, folgt daraus
**nicht** — adverse Selektion sagt das Gegenteil: ein langsamer Teilnehmer
wird genau dann gefüllt, wenn es schlecht für ihn ist.

Der Befund ist also eine Aussage darüber, **wer dort heute Market Making
macht**, und nicht ein Versprechen an einen neuen Teilnehmer. Wer ihn anders
liest, hat die dreizehnte Scheinfindung dieses Projekts.

---

## 1. Was gemessen ist

67 037 beobachtete Buch-Orders auf BTC, über drei getrennte Aufnahmefenster.
Eine Order-Kennung, die in einem Trade auftaucht, **ist gehandelt worden** —
`recentTrades` trägt `ask_id` und `bid_id`, also ist ein Fill belegt und
nicht gefolgert.

| | belegt gefüllt | belegt storniert | liegt noch |
|---|---|---|---|
| gepoolt (67 037) | **8,3 %** | **91,4 %** | 0,3 % |

**91,4 % der ruhenden Orders werden storniert, nicht gefüllt.** Das ist die
erste Zahl, die zählt, und sie ist die Fortsetzung eines Befunds, der schon
dastand: ein Backtest, der eine Maker-Order am Antritt als gefüllt verbucht,
nimmt an, dass das Buch stehen bleibt. Es bleibt nicht.

## 2. Der Markout, bedingt auf den Fill

Vorzeichen aus `is_maker_ask`, gegen ein aus dem Tape geschätztes Mid.
**Positiv heisst gegen den Maker**, negativ zu seinen Gunsten.

| Horizont | Markout | Intervall | n |
|---|---|---|---|
| 1 s | **−0,195 bp** | [−0,226; −0,162] | 5 200 |
| 5 s | −0,151 bp | [−0,205; −0,098] | 5 565 |
| 30 s | −0,158 bp | [−0,305; −0,019] | 5 567 |
| 5 min | −0,821 bp | [−1,265; −0,396] | 5 567 |

Alle vier schliessen die Null aus, alle vier **zugunsten des Makers**. Das
ist das Gegenteil adverser Selektion.

## 3. Und es replikiert

Dieses Projekt verlangt zwei Tore: ein korrigiertes Intervall ohne Null
**und** Replikation im Band 0,5–2,0×. E6 passierte das erste und fiel am
zweiten mit gekipptem Vorzeichen. Hier:

| Fenster | Dauer | gefüllt | storniert | Markout 1 s |
|---|---|---|---|---|
| 07.10. 17:28–18:40 | 1,21 h | 8,3 % | 90,9 % | −0,170 [−0,210; −0,130] |
| 08.10. 07:20–09:15 | 1,92 h | 8,3 % | 91,3 % | −0,200 [−0,245; −0,154] |
| 08.10. 11:00–11:06 | 0,09 h | 8,8 % | 82,6 % | −0,390 [−0,579; −0,198] |

**Verhältnis Fenster 2 zu Fenster 1: 1,18×.** Im Band. Die Füllquote ist in
beiden identisch (8,3 %), die Storno-Quote praktisch (90,9 gegen 91,3 %).

**Beide Tore bestanden, zum ersten Mal in diesem Projekt.**

## 4. Warum das trotzdem kein Ertrag ist

Vier Gründe, und der erste ist der aus der Vorbemerkung.

**Es ist eine Selektion auf einer bestehenden Population.** Siehe oben. Das
ist nicht ein Vorbehalt unter mehreren, das ist der Kern.

**Die Grössenordnung ist winzig.** 0,195 bp je Fill. Bei 1 000 CHF Konto und
einer Position von 200 CHF sind das **0,0039 CHF je Fill**. Um die 2 953 CHF
zum Ziel zu verdienen, bräuchte es rund **757 000 Fills** — bei 8,3 %
Füllquote also neun Millionen gestellte Orders. Das ist keine Strategie,
das ist eine andere Firma.

**Es ist kein Richtungsvorteil, und das Problem des Systems ist die
Richtung.** 21 gemessene Familien, keine positiv. Dieser Befund sagt nichts
über Richtungsvorhersage; er sagt etwas über Mikrostruktur.

**Market Making ist in diesem Projekt nicht vorbereitet.** Es bräuchte
kontinuierliche Quotierung, Inventarsteuerung, Storno-Latenz unter 300 ms
(dokumentiert für diese Venue) und eine Betriebsbereitschaft, die mit der
1,2-Sekunden-Bestätigung nicht vereinbar ist. Der Forschungsauftrag führt es
ausdrücklich als „unter manuellen Regeln vorerst Forschung".

## 5. Was es dann wert ist

Eine **Richtung**, die vorher nicht da war. Das Projekt hat jede
Richtungsvorhersage gemessen und keine gefunden; der Carry war bis November
2024 ein Ertrag und ist keiner mehr. Dieser Befund sagt: auf dieser Venue
ist der Taker-Fluss uninformiert genug, dass die Steller im Schnitt
gewinnen.

Das ist die erste gemessene Stelle, an der überhaupt Geld auf dem Tisch
liegt — bei jemand anderem. Ob ein neuer Teilnehmer davon etwas bekommt,
ist **offen** und wäre eine eigene, ernsthafte Untersuchung mit eigenem
Blocker (Latenz, Warteschlange, Inventar).

## 6. Grenzen der Zahlen oben

**Drei Fenster über zwei Tage sind keine Regime-Abdeckung.** 3,2 Stunden
insgesamt, ein Markt, kein Stress.

**Die Storno-Quote ist eine Obergrenze.** Eine Lücke im Trade-Tape macht aus
einem Fill eine scheinbare Storno. Gemessen 70 Lücken auf 1 495 Abfragen
(~4,7 %) im ersten Lauf.

**Die beobachtete Population ist nicht zufällig gezogen.** Das Buch wird
alle 30 s aufgenommen, also sind langlebige Orders überrepräsentiert — und
langlebige Orders sind eher die geduldigen, gut platzierten. Das verzerrt in
dieselbe Richtung wie der Befund, und um wie viel, sagt diese Aufnahme
nicht.
