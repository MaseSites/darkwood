# E3: Ausgänge als kausale Handelspolitik

> **NACHTRAG 09.10.2026 — die Grenze von E3.3 war zu schmal gerechnet.**
> Der Bootstrap konnte bei den ausgelieferten 3 000 Ziehungen das korrigierte
> Perzentil nicht auflösen: unter der unteren Grenze lagen 1,44 Ziehungen, die
> Grenze war damit fast das Minimum der Stichprobe. Mit der jetzt
> niveau-abhängigen Ziehungszahl (20 801 bei Bonferroni auf 52) lautet die
> gepaarte Differenz von E3.3 **−0,0557 [−0,1091; −0,0001]** statt
> [−0,1123; −0,0060]. Sie schliesst die Null noch aus — um ein Zehntausendstel
> R. **Das Urteil lautet damit „am Rand", nicht „zuverlässig schlechter".**
> Über sieben Saatwerte war es bei 3 000 Ziehungen 6 zu 1, bei 200 000
> einstimmig. E3.2 bleibt unverändert unentschieden. Vollständig in
> `audit/BOOTSTRAP_RAND.md`. Die Zahlen unten bleiben stehen, weil ein Bericht,
> der nachträglich umgeschrieben wird, keine Aufzeichnung ist.


Reproduktion: `python scripts/study_exits.py`

**Ergebnis: kein Kandidat — und zum ersten Mal ist etwas, das das System
schon tut, messbar besser als die benannte Alternative.**

---

## 1. Warum diese Frage als letzte noch offen war

Der Zustandsbericht schloss lange so: `net_r = (eingefangene Bewegung −
Gebühr) / Stop-Abstand`, also kürzen sich Stop, Positionsgrösse und Hebel
heraus, also ist jeder Vorschlag mit anderen Stops arithmetisch erledigt.

Die Positionsgrösse kürzt sich heraus. **Der Stop nicht.** Er steht im
Nenner — und, der übersehene Teil, er verschiebt den
**Ausstiegszeitpunkt**. Ein Trade, der bei −1 R ausgestoppt wird und danach
gedreht hätte, ist bei einem anderen Ausstieg ein anderer Trade.

`scripts/study_stop_path.py` hat das gemessen und ausdrücklich festgehalten,
dass es keine Exit-Studie ist: *„ob das in Summe hilft, kann nur ein
vollständig neu simulierter Pfad sagen (E3)."* Hier ist er.

## 2. Was gemessen wurde

**7 255 Fälle** über zwölf Märkte, jeder Arm auf **denselben Einstiegen**,
verglichen als **gepaarte Differenz je Trade**. Unverbunden gerechnet würde
der Vergleich die Streuung der Einstiege mitmessen, die beide Arme
gemeinsam haben — und die ist um Grössenordnungen grösser als der gesuchte
Effekt.

Korrigiert auf die 46 angemeldeten Vergleiche (Niveau 99,891 %).

| Arm | Netto-R | Haltezeit | gepaarte Differenz zur Basis |
|---|---|---|---|
| **E3.1** Stop + Ziel, 48 h | **−0,0205** | 14,4 h | (Basis) |
| **E3.2** Stop + 24-h-Uhr, kein Ziel | −0,0824 | 14,2 h | −0,0619 [−0,1316; +0,0071] |
| **E3.3** Stop + 2,0-ATR-Trail | −0,0762 | 7,9 h | **−0,0557 [−0,1123; −0,0060]** |

**E3.3 ist zuverlässig schlechter.** Das korrigierte Intervall schliesst die
Null aus — auf der falschen Seite. Das ist nicht „unentschieden", das ist
ein Befund.

E3.2 zeigt in dieselbe Richtung (−0,0619) und bleibt unentschieden; das
Intervall streift die Null knapp.

## 3. Warum, und das ist der lesbare Teil

| Arm | Stop | Ziel | Zeit | Trail |
|---|---|---|---|---|
| E3.1 | 55,9 % | **31,1 %** | 13,0 % | — |
| E3.2 | 57,3 % | — | 42,7 % | — |
| E3.3 | — | — | 1,0 % | **99,0 %** |

**Das Ziel arbeitet.** In 31,1 % der Fälle verlässt der Trade über das Ziel
— und beide Alternativen nehmen genau diese Tür weg. E3.2 ersetzt sie durch
eine Uhr, E3.3 durch einen mitlaufenden Stop, und beide schneiden den
Gewinner früher ab: die Haltezeit fällt bei E3.3 von 14,4 auf **7,9
Stunden**, der Trail greift in 99 % der Fälle.

Ein Trailing-Stop, der fast immer zuerst greift, ist kein Gewinnschutz,
sondern ein engerer Stop mit mehr Schritten. Dass er schlechter ist, ist
nach dieser Zerlegung nicht überraschend — aber es war vorher nicht
gemessen, und „nicht überraschend" ist kein Beleg.

## 4. Die Abnahme

Vorab festgelegt: **(a)** gepaarter Mehrwert mit korrigiertem Intervall ohne
Null und **(b)** absolut netto positiv.

* (a) **KEINER** — und E3.3 verfehlt sie in die Gegenrichtung.
* (b) **KEINER** — alle drei Arme sind negativ.

**→ NICHT BELEGT.**

Und das Umgekehrte, das hier zum ersten Mal auftritt: die **bestehende**
Ausstiegspolitik ist messbar besser als beide Alternativen, bei E3.3 mit
Intervall ohne Null. Das ist das erste Mal in diesem Projekt, dass etwas,
das das System schon tut, gegen eine benannte Alternative verteidigt werden
kann statt nur nicht widerlegt zu sein.

Es macht das System nicht profitabel. Es schliesst eine Richtung, in die zu
optimieren wäre.

## 5. Grenzen, ohne Beschönigung

**Die Population ist eine andere als in E1, mit Absicht.** E1 filtert nur
`liquidation` und behält die von Kosten- und Chance-Risiko-Regel abgelehnten
Signale, weil es fragt, ob ein Modell Gewinner aus dem *ganzen* Pool picken
kann. E3 fragt, ob ein anderer Ausstieg die Trades verbessert, die das
System **tatsächlich nimmt** — eine Ausstiegspolitik gilt nur für eine
Position, die es gibt. Preis: auf BTC bleiben 203 von 2 552 Signalen, 92 %
fallen an den Regeln. **Die Fallzahlen von E1 und E3 sind nicht
vergleichbar.**

**Die −0,0205 R der Basis sind nicht die −0,0906 R der Replay-Verteilung.**
Andere Population (nur genommene), anderer Horizont (48 h), zwölf Märkte.
Nicht nebeneinanderlegen.

**Keine Slot-Konkurrenz.** Diese Signale haben nie um einen Platz
konkurriert. Ein längerer Halt belegt Slots, die ein anderer Trade
gebraucht hätte — das sieht nur ein vollständiger Portfolio-Replay, und das
Register verlangt ihn ausdrücklich *danach*. Für einen durchgefallenen Arm
erübrigt er sich.

**Die 2,0 ATR sind vorab festgelegt und wurden nicht nachjustiert.** Ein
anderer Trail-Abstand könnte besser abschneiden. Ihn nach dem Ergebnis zu
suchen wäre genau der Griff, den der Forschungsauftrag verbietet — und die
Zerlegung in Abschnitt 3 sagt ohnehin, woran es liegt: nicht am Abstand,
sondern daran, dass der Trail die Ziel-Tür ersetzt.

**Eine offene Frage, die dieser Test nicht beantwortet.** Ein Signal, das
die Kostenregel verwirft, könnte unter einem Trailing-Ausstieg annehmbar
werden — der erwartete Kostenanteil hängt an der Haltedauer. Das wäre eine
andere *Einstiegs*-Menge und würde die Paarung zerstören, auf der dieser
Test beruht. Eigene Frage, nicht ein Nachbessern dieser.
