# Die Tape-Abdeckung, nachgerechnet — 19.10.2026

**Anlass.** `audit/TAPE_VOLLE_ABDECKUNG.md:32` nennt **94,9 % Abdeckung** für
die Binance-Gegenaufnahme. Ein Prüfagent zählte **72,0 %** nach. Weil auf
diesen Daten mehrere Befunde des Projekts ruhen — der Maker-Markout, „49 % der
ruhenden Order verschwinden je 17 s", „nur 12,4 % der Order an der Berührung
füllen je" —, habe ich selbst nachgezählt.

## Beide hatten recht, über verschiedene Fragen

Gezählt über die `a`-Kennungen (Binances aggTrade-Id, die **je Symbol** läuft,
also eine echte Lückenzählung erlaubt), aus `data/quarantine/binance_tape/`:

| | BTCUSDT | ETHUSDT |
|---|---|---|
| Kennungen gesammelt | 622.195 | 577.403 |
| Spanne erste..letzte | 1.699.181 | 1.521.366 |
| **A — ganze Spanne** | **36,6 %** | **38,0 %** |
| **B — Lücken > 1.000 (≈28 s) herausgerechnet** | **92,8 %** | 92,9 % |
| **B — Lücken > 10.000 (≈285 s) herausgerechnet** | **71,9 %** | 72,0 % |
| Abschnitte bei Bruch > 1.000 | 87 | 76 |
| Abschnitte bei Bruch > 10.000 | 5 | 6 |
| längster Abschnitt (Bruch > 10.000) | 532.031 Kennungen, **64,8 % dicht** | 454.900, 70,0 % |

**Keine der drei Zahlen ist „die" Abdeckung.** Sie hängt an der Bruchschwelle,
und das Dokument nannte seine Schwelle nicht. Das ist der eigentliche Defekt —
keine falsche Zahl, eine **unbenannte**. Dieselbe Klasse wie der
`coverage:`/`content:`-Präfix beim Datenstempel und wie „nenne das Intervall,
das du zitierst".

* Die **94,9 %** des Dokuments liegen bei meinen 92,8 % — es hat also die
  *Dichte innerhalb der Sammelstösse* gemessen. Das ist eine legitime Frage.
* Die **72,0 %** des Prüfers sind meine Lesart B bei einer weiten Schwelle, die
  die kleinen Lücken in die Abschnitte hineinzieht und mitzählt.
* Und die Zahl, die **keine der beiden Seiten berichtet hat**: über die ganze
  Spanne liegen **36,6 %** des Marktgeschehens auf der Platte.

## Welche Lesart für welchen Befund gilt

Bei der gemessenen Rate von 35,1 Trades/s je Markt:

| Horizont | Kennungen | bleibt innerhalb eines Stosses? |
|---|---|---|
| 1 s | ~35 | ja |
| 5 s | ~176 | ja |
| **17 s** | **~597** | **ja** (Stossgrenze liegt bei ~1.000) |
| 30 s | ~1.053 | an der Grenze |
| 5 min | ~10.530 | nein |

**Daraus folgt für die vorhandenen Befunde:**

* „49 % der ruhenden Order verschwinden je **17 s**" und „12,4 % füllen an der
  Berührung" bleiben **innerhalb eines Stosses**. Für sie gilt die dichte
  Lesart (92,8 %), und sie stehen damit — mit dem Zusatz, dass 7,2 % der Trades
  auch dort fehlen und die Verschwinde-Rate deshalb eher **unterschätzt** ist
  (ein fehlender Trade kann eine Füllung sein, die nicht gesehen wurde).
* Der **5-Minuten**-Markout aus `TAPE_MAKER_BEFUND.md` überschreitet die
  Stossgrenze. Er braucht die weite Lesart, und bei 64,8 % Dichte im längsten
  zusammenhängenden Abschnitt ruht er auf einem Drittel fehlender Trades. Er
  war ohnehin der Horizont, dessen Intervall die Null einschliesst
  (−0,378 bp [−0,850; +0,111]) — dieser Befund wird dadurch nicht schlechter,
  aber seine Begründung ist jetzt eine andere: nicht nur Streuung, auch
  Lückenhaftigkeit.
* Jede **künftige** Messung über mehr als ~28 s in diesen Daten muss ihre
  Bruchschwelle nennen und darf 94,9 % nicht zitieren.

## Was zu tun ist

`audit/TAPE_VOLLE_ABDECKUNG.md` bleibt stehen; seine 94,9 % sind richtig
**gerechnet** und falsch **beschriftet**. Diese Datei ist die Beschriftung.

Eine dichtere Neuaufnahme würde die Lücken nicht grundsätzlich beheben: sie
entstehen zwischen den Abfragen, und 87 Stösse in einem Fenster heissen 86
Unterbrechungen. Wer eine lückenlose Reihe braucht, braucht einen
Datenstrom und keine Abfrageschleife.

## Etiketten

| Aussage | |
|---|---|
| Die drei Prozentzahlen | **BELEGT** (eigene Zählung über 622.195 bzw. 577.403 Kennungen) |
| Stossgrenze ≈28 s bei 35,1 Trades/s | **BELEGT** (Rate aus dem Dokument, Umrechnung hier) |
| 17-s-Befunde bleiben innerhalb eines Stosses | **BELEGT** (597 < 1.000) |
| Verschwinde-Rate ist eher unterschätzt | **MODELLIERT** — ein fehlender Trade *kann* eine ungesehene Füllung sein; dass er es ist, sagen diese Daten nicht |

*Nebenbefund zur eigenen Arbeit:* der erste Entwurf meines Zählskripts suchte
`a` auf der obersten Ebene jeder Zeile und fand null Kennungen. Die Sätze sind
verschachtelt (`{"received_ms": …, "trades": [{"a": …}]}`). Die Form
angenommen statt angesehen — und der leere Treffer hat es sofort verraten,
weil „keine Kennungen gefunden" kein plausibles Ergebnis ist.
