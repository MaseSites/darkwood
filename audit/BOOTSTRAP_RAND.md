# Der Bootstrap konnte den Rand nicht auflösen — und E3.3 steht jetzt bei −0,0001

Reproduktion:

```bash
python scripts/build_trial_ledger.py     # das Ledger und die Lücke
python scripts/study_exits.py            # E3 mit der korrigierten Zahl
```

Stand 09.10.2026, 11:00–11:40 UTC. Commit vor der Arbeit: `dd4a1ca`.

---

## 1. Wie das aufgefallen ist

Beim Bau des Trial-Ledgers stellte sich die Frage, ob die Mehrfachkorrektur
auf die richtige Zahl geht. Also: hält E8, wenn man strenger korrigiert?

| Bonferroni auf | Niveau | E8.1 Achsenabschnitt |
|---|---|---|
| 52 | 99,9038 % | −0,0831 [−0,1455; −0,0214] |
| 124 | 99,9597 % | −0,0831 [−0,1458; −0,0187] |
| 250 | 99,9800 % | −0,0831 [−0,1458; −0,0185] |
| 500 | 99,9900 % | −0,0831 [−0,1458; −0,0184] |

**Das Intervall hört auf, breiter zu werden.** Und genau das war verdächtig:
ein strengeres Niveau *muss* ein breiteres Intervall ergeben.

## 2. Die Ursache, gerechnet

Die untere Grenze ist das Perzentil `(1 − Niveau) / 2` der Resample-Verteilung.
Bei `DRAWS = 3000` liegen darunter:

| Bonferroni auf | Perzentil | Ziehungen darunter |
|---|---|---|
| 46 | 0,05435 % | 1,63 |
| **52** | 0,04808 % | **1,44** |
| 124 | 0,02016 % | 0,60 |
| 500 | 0,00500 % | 0,15 |

**Eine Grenze, die auf anderthalb Ziehungen beruht, ist kein Perzentil,
sondern fast das Minimum der Stichprobe.** Sie kann nicht breiter werden, weil
es nichts Extremeres zu finden gibt.

Der Kommentar an `DRAWS` sagte: *„Enough that the percentile bounds are stable
to about a thousandth of an R."* Das stimmt für ein 95-%-Intervall. Für die
korrigierten Niveaus, mit denen dieses Projekt ausschliesslich arbeitet,
stimmt es nicht.

## 3. Was es angerichtet hat — gemessen an E3.3

E3.3 ist der Fall, dessen Grenze am nächsten an der Null lag: der
2,0-ATR-Trail gegen die Basis, 7 255 gepaarte Fälle, berichtete obere Grenze
**−0,0060**. Sieben Saatwerte, drei Ziehungszahlen:

| Ziehungen | obere Grenze | Null ausgeschlossen in |
|---|---|---|
| 3 000 *(ausgeliefert)* | −0,0021 ± 0,0036 | **6 von 7 Saatwerten** |
| 40 000 | −0,0010 ± 0,0019 | 6 von 7 |
| 200 000 | −0,0014 ± 0,0008 | **7 von 7** |

**Das Urteil „zuverlässig schlechter" war bei den ausgelieferten Einstellungen
saatwert-abhängig.** Ein Saatwert von sieben hätte „unentschieden" gemeldet.
Es hält — der benutzte Saatwert war nicht der abweichende, und bei genug
Ziehungen hält es durchgehend. Aber es wurde mit einer Methode festgestellt,
die es nicht verlässlich sagen konnte.

E3.2 ist in allen Varianten 0 von 7 und war damit zu Recht als unentschieden
berichtet.

## 4. Behoben, und was sich dadurch an den Zahlen ändert

`block_bootstrap`, `paired_difference` und `two_group_difference` richten die
Ziehungen jetzt nach dem **Niveau** statt nach einer festen Zahl:

```
draws_for(level) = MIN_TAIL_DRAWS / ((1 - level) / 2),  mindestens DRAWS,
                                                        höchstens MAX_DRAWS
```

`MIN_TAIL_DRAWS = 10` — eine Entscheidung, keine Ableitung. `MAX_DRAWS =
200 000`, weil gemessen 3 000 Ziehungen 116 ms kosten, 20 000 672 ms und
50 000 1,7 s; bei 200 000 ist ein Intervall rund sieben Sekunden und eine
Studie rechnet Dutzende.

Bei Bonferroni auf 52 sind das **20 801 Ziehungen** statt 3 000. Ein
unkorrigiertes 95-%-Intervall behält den Boden von 3 000.

Und das Intervall trägt jetzt mit, wie gut sein Rand belegt ist: `draws`,
`tail_draws` und `tail_resolved`. Bindet die Obergrenze — etwa bei Bonferroni
auf 2 000, wo nur 2,5 Ziehungen unter dem Perzentil bleiben — steht das in der
Ausgabe statt nirgends.

### Die neuen Zahlen

| Befund | vorher | **jetzt** | Urteil |
|---|---|---|---|
| **E3.3** Trail gegen Basis | −0,0557 [−0,1123; **−0,0060**] | −0,0557 [−0,1091; **−0,0001**] | **am Rand** |
| E3.2 Uhr gegen Basis | −0,0619 [−0,1316; +0,0071] | −0,0619 [−0,1290; +0,0115] | unentschieden, unverändert |
| E8.1 Rest nach Beta | −0,0823 [−0,1414; −0,0119] | −0,0831 [−0,1453; −0,0217] | hält |
| E8 Mechanik, eigenes Symbol | −0,0505 [−0,0868; −0,0113] | −0,0509 [−0,0864; −0,0128] | hält |
| E4V.1 Residual-Reversion | −12,43 [−22,46; −1,33] bp | −12,43 [−23,40; −1,35] bp | hält |
| E4V.2 Kontrolle | +12,53 [−16,20; +47,56] bp | +12,53 [−17,45; +45,18] bp | spannt, unverändert |

**Nur ein Urteil ist betroffen, und es ist das stärkste, das E3 gefällt hat.**
Die obere Grenze von E3.3 liegt bei **−0,0001 R** — ein Zehntausendstel. Die
Aussage „zuverlässig schlechter" steht formal noch, aber sie steht auf der
Kante, und so gehört sie berichtet. `audit/E3_AUSGAENGE.md` und der Eintrag im
Ratchet tragen diesen Vorbehalt jetzt.

**Die Richtung des Fehlers war glücklich.** Zu wenige Ziehungen machen ein
Intervall *zu schmal* und sein Rand *verrauscht*. Ein Projekt, dessen Befunde
alle negativ oder null sind, war davon kaum bedroht: zu schmal heisst, dass
Effekte zu leicht als gesichert gelten — und gesichert wurde hier fast nichts.
Betroffen waren genau die Grenzfälle, und E3.3 war der engste.

## 5. Und das Trial-Ledger, das dabei entstand

`audit/TRIAL_LEDGER.csv`, 88 Zeilen, gebaut von
`scripts/build_trial_ledger.py` aus `ratchet.py` und
`EXPERIMENTS_NEXT.yaml`. Jede Zeile trägt ihre Quelle.

| | |
|---|---|
| Arme mit Zahlen, aufzählbar | **14** |
| Familien als Einzeiler | 24 |
| vorab registrierte Arme | 37 |
| angemeldete Vergleichszellen | 52 |
| `meta.prior_search` **behauptet** | **124 Versuche, 87 Arme** |
| **nicht aufzählbar** | **110** |

Gesucht, wo 124 und 87 herkommen: sie stehen in
`EXPERIMENTS_NEXT.yaml:meta.prior_search` und im Zustandsbericht — **nur
dort, als Behauptung.** Eine Aufzählung existiert nicht.

**Warum das zählt.** `total_comparisons` trägt die Mehrfachkorrektur, und der
Kommentar daneben sagt, die Zahl solle *„die bereits gelesenen Zellen der
Vorgänger-Suche"* enthalten, *„soweit dieselbe Frage betroffen ist"*. Ohne
Aufzählung ist nicht prüfbar, ob 52 diese Zellen enthält oder nicht.

**Was dagegen prüfbar ist und geprüft wurde:** ob es überhaupt einen
Unterschied macht. Abschnitt 1 zeigt, dass E8.1 selbst bei Bonferroni auf 500
die Null ausschliesst — jetzt mit einer Ziehungszahl, die das auch belegen
kann. Die unaufgezählten 110 sind damit ein **Dokumentationsmangel, kein
offener Befund**: das zentrale negative Ergebnis hält auf jedem Niveau, das
hier plausibel wäre.

## 5b. Was die Änderung kostet

Die volle Testsuite braucht jetzt etwa das Doppelte an Rechenzeit (591 s CPU
gegen rund 290 s), weil jedes korrigierte Intervall 20 801 statt 3 000
Ziehungen rechnet.

**Und sie hat dabei einen bestehenden Test gekippt** —
`test_adapter_jobs.py::test_the_job_id_is_derived_from_the_command`, eine
Wanduhr-Zusicherung von 60 Sekunden auf einem echten Unterprozess. Der Test
nennt die Diagnose selbst: *„Bevor dies als Defekt gelesen wird: läuft noch
etwas Grosses auf der Maschine? … Diese Datei allein laufen lassen — bleibt
sie rot, ist es der Code."* Allein gelaufen: **grün, 17 Tests.**

Es war also Maschinenlast, verursacht von dieser Änderung. Der Test hat genau
das vorhergesagt, was eintrat, und seine eigene Prüfanweisung mitgeliefert.
Festgehalten statt wegerklärt: wer die Suite neben einem Backtest laufen
lässt, bekommt hier einen roten Punkt, der keiner ist.

## 6. Offen

**Die 110 fehlenden Zeilen.** Sie liessen sich nur aus der Git-Historie und
den Berichten rekonstruieren, und ich habe es nicht getan. Solange die
Behauptung im Register steht, sollte sie entweder belegt oder auf das
Aufzählbare zurückgenommen werden.

**`MIN_TAIL_DRAWS = 10` ist gesetzt, nicht abgeleitet.** Bei zehn wackelt die
Grenze über Saatwerte noch; gemessen bei E3.3 mit 40 000 Ziehungen ± 0,0019.
Für eine Grenze bei −0,0001 ist das nicht genug, und genau deshalb steht dort
jetzt „am Rand" statt „zuverlässig".
