# E12 — Die Uhr: Wochenende, Funding-Stunde, Viertelstundenmarke

**Stand 11.10.2026.** Suchseite gemessen, Replikationsseite offen.
Skript `scripts/study_the_clock.py`, Daten `data/study_the_clock.json`.
Vorab registriert in `audit/EXPERIMENTS_NEXT.yaml`, Arm E12,
`total_comparisons` 58 → 61.

---

## 0. Die falsche Tatsache und die richtige Frage

Der Auftrag kam so: „Diese Märkte sind am Wochenende geschlossen, ich weiss
gar nicht, warum da so viel getradet wird."

**Die Tatsache ist falsch.** Krypto-Perpetuals laufen 24 Stunden an sieben
Tagen. Geschlossen sind Aktien, Devisen und die CME-Futures — und genau die
sind auf TikTok gemeint, wenn von „Wochenende zu" die Rede ist. Unser System
handelt Bybit USDT-Perps; es gibt keine Schlussglocke, die es abwarten
könnte.

**Die Intuition darunter ist eine Hypothese, und sie war nie geprüft.** Dünnere
Wochenendbücher sind in der Literatur beschrieben, und die Folge wäre genau
das, was im Papierprotokoll ständig auftaucht: ein Stop, den ein Docht holt,
während die Kerze auf der richtigen Seite schliesst. Eine falsche Prämisse und
eine prüfbare Frage sind zwei verschiedene Dinge, und die zweite bekommt eine
Messung.

Dazu kam eine zweite Quelle. Kim/Hansen, *The Quarter-Hour Effect: Periodic
Algorithmic Trading and Return Predictability in Cryptocurrency Futures*
(arXiv:2607.09426) finden über sechs Binance-Perps periodische Volatilitäts-
und Volumenschübe auf Minuten-, Fünfminuten- und Viertelstundenmarken, und
Vorhersagbarkeit der Eröffnungsrenditen an Viertelstunden-Öffnungen.

Unsere Einstiege liegen **per Konstruktion** auf genau diesen Marken. Gemessen
im alten Lauf: 2.343 von 2.734 Trades öffnen auf `:00`.

---

## 1. Was vorher festgelegt wurde

| | |
|---|---|
| Primärkennzahl | **Brutto**-R je Trade. Netto wäre eine Gebührengeschichte und sagte nichts über den Einstieg. |
| Tor 1 | Zwei-Gruppen-Differenz, korrigiertes Intervall ohne Null. Zwei überlappende Intervalle nebeneinander sind **kein** Test — Lehre aus E11. |
| Tor 2 | Replikation 0,5–2,0× zwischen altem 4-Markt-Lauf und neuem 12-Markt-Lauf. |
| Pflichtangabe | Der **linke Rand** beider Gruppen: Anteil unter −1R, schlimmster Einzelverlust, 5 %-Quantil. Ein besserer Mittelwert bei schwererem Rand ist **kein** positives Ergebnis — Lehre aus E10. |
| Mindestbesetzung | 100 Fälle je Zelle. Darunter heisst „nicht entscheidbar", nicht „kein Effekt". |
| Niveau | 99,918 % (Bonferroni auf 61 Vergleiche). |

Und der Confound, der E12.3 sonst erledigt hätte: **die Einstiegsminute
korreliert mit der Setup-Zeitebene.** Ein H1-Signal steigt per Konstruktion auf
`:00` ein, ein M15-Signal auf jeder Viertelstunde. Über alle Trades gerechnet
misst die Zelle die Zeitebene und nennt sie die Uhr. E12.3 läuft deshalb nur
innerhalb der M15-Population. Dass der Confound real ist, zeigt die
Verteilung: H1 1.517, M15 542, H4 559, D1 116.

Dafür musste `Fill` erst seine Zeitebene bekommen — sie wurde bis dahin
weggeworfen. Commit `9dd701c`.

---

## 2. Suchseite: alter 4-Markt-Lauf, 2.734 Trades

### E12.1 Wochenende gegen Werktag

| | n | Mittel brutto | unter −1R | schlimmster | 5 %-Quantil |
|---|---|---|---|---|---|
| **Sa/So** (UTC) | 516 | **−0,0956 R** | 60,3 % | −3,778 R | −1,0395 |
| **Mo–Fr** (UTC) | 2.218 | **−0,0207 R** | 55,9 % | −2,461 R | −1,0381 |

Differenz **−0,0749 R**, korrigiertes Intervall **[−0,3247; +0,1919]** —
**Null enthalten**.

Das Wochenende ist in **Mittelwert und Rand** schlechter: das 4,6-fache der
Verlusterwartung, 4,4 Prozentpunkte mehr Trades jenseits des Stops, und der
schlimmste Einzelverlust ist um die Hälfte grösser. Die Richtung stimmt mit der
Intuition und mit der Literatur überein.

**Belegt ist es nicht.** Bei 516 Fällen und einem auf 61 Vergleiche
korrigierten Niveau ist das Intervall 0,52 R breit. Ein Punktschätzer, der
4,6-mal so gross ist, und ein Intervall, das die Null enthält, sind kein
Widerspruch — sie sagen, dass die Stichprobe die Frage nicht trägt.

### E12.2 Funding-Stunde gegen sonst

| | n | Mittel brutto | unter −1R | schlimmster |
|---|---|---|---|---|
| ≤ 60 min nach Abrechnung | 611 | −0,0555 R | 52,2 % | −1,998 R |
| sonst | 2.123 | −0,0289 R | 57,98 % | −3,778 R |

Differenz **−0,0266 R**, Intervall **[−0,2529; +0,2107]** — **Null enthalten**.

Hier ist der Rand in der Funding-Gruppe **besser**, nicht schlechter: 5,8
Prozentpunkte weniger Trades jenseits des Stops, und der schlimmste Verlust
ist halb so gross. Wäre nur der Mittelwert berichtet, hätte die Zelle wie ein
schwacher Negativbefund gelesen. Genau dafür ist die Randpflicht da.

### E12.3 Stundenmarke gegen Viertelstunde, nur M15

| | n | Mittel brutto | unter −1R |
|---|---|---|---|
| `:00` | 500 | −0,0141 R | 60,4 % |
| `:15` / `:30` / `:45` | **2** | **+1,0259 R** | 50,0 % |
| andere Minuten (Limit-Fills) | 40 | *ausgeschlossen* | |

**NICHT ENTSCHEIDBAR.** Zwei Fälle, gegen eine Mindestbesetzung von 100.

**Und die erste Fassung dieser Zelle war falsch gruppiert.** Sie verglich `:00`
gegen „nicht `:00`" und bekam 42 Fälle bei −0,1283 R. Von diesen 42 lagen
**40 auf beliebigen Minuten** — 1, 2, 3, 12, 34, 41, 52 — und nur zwei auf
einer Viertelstundenmarke. Der Einstiegszeitstempel ist die **Füllung**, nicht
die Entscheidung; bei einer Limit-Order liegen die beiden auseinander, und wer
nach dem Komplement einer Marke gruppiert, sammelt genau diese Differenz ein.

Richtig gruppiert kippt das Vorzeichen: −0,1283 R über 42 kontaminierte Fälle
gegen **+1,0259 R** über zwei echte. Ohne die vorab festgelegte
Mindestbesetzung wäre daraus eine Entdeckung aus zwei Beobachtungen geworden.

### Und der Grund für die zwei Fälle ist nicht die Uhr

Von 542 M15-Trades des alten Laufs öffnen 500 auf `:00` und nur **zwei** auf
einer Viertelstunde. Das sah nach einem Defekt in `SEARCH_ORDER` aus. Es ist
keiner.

**Der alte Lauf läuft auf H1-Kadenz, der heutige auf M15.** Bei stündlicher
Entscheidung wird der M15-Chart nur zur vollen Stunde befragt — 72 seiner 96
Tageskerzen werden nie angesehen. `config/settings.yaml` beschreibt genau das
als behobenen Defekt und steht heute auf `signal: M15`. Der neue Lauf
bestätigt es: auf BTCUSDT liegen 65 von 88 M15-Einstiegen auf 15/30/45.

**Die Vergleichsgruppe existiert im alten Lauf also nicht.** E12.3 ist dort
nicht „zu klein besetzt", sondern prinzipiell nicht messbar.

Und nichts in den Daten sagte das. Die Replay-Zeilen im Journal tragen keine
`run_signature`; die Kadenz war nur aus der Minutenverteilung der Einstiege zu
**erschliessen**. `journal/record.py` nennt diesen Zustand selbst: „Eine
Eigenschaft, die man nur durch Git-Archäologie findet, ist keine
aufgezeichnete Eigenschaft." Das Skript markiert sie deshalb als
`H1 (erschlossen)` und verweigert jede Replikation über zwei Kadenzen —
der Unterschied wäre grösser als die Zelle, die er prüfen soll.

---

## 3. Der Mechanismus: wodurch das Wochenende herausfaellt

**Das System meidet das Wochenende längst.**

| | Wochenendanteil der Trades |
|---|---|
| Kalender | 28,6 % |
| alter Lauf, 4 Märkte, 2.734 Trades | **18,9 %** |
| neuer Lauf, BTCUSDT, 263 Trades | **13,3 %** |

Niemand hat das konfiguriert. **Und der Mechanismus ist exakt bestimmbar**,
ohne eine neue Messung — nur durch eine Gruppierung des Signalspeichers nach
Wochentag. 47.918 Replay-Zeilen unter der laufenden Signatur, Kostendeckel
0,08:

| | n | genommen | Kosten-Ablehnung | Chance/Risiko-Ablehnung |
|---|---|---|---|---|
| **Werktag** | 34.684 | 16,9 % | 46,3 % | 36,8 % |
| **Wochenende** | 13.234 | **11,2 %** | **51,9 %** | 36,8 % |

Die Setups **feuern proportional**: 27,6 % der Signale fallen aufs Wochenende,
bei 28,6 % Kalenderanteil. Das Chance-Risiko-Tor greift an beiden Tagen
**identisch** mit 36,8 %. Der ganze Unterschied steckt im Kostentor.

| | Kostenquote (Median) | Stopweite (Median) |
|---|---|---|
| Werktag | 0,06727 | 0,82683 % |
| Wochenende | **0,08920** | **0,59877 %** |

**Der Deckel steht bei 0,08.** Der Wochenend-Median liegt darüber, der
Werktags-Median darunter. Das ist der gesamte Mechanismus.

Und die Ursache dahinter ist eine Identität, keine Auslegung: über alle 47.918
Zeilen ist `cost_fraction × stop_fraction` konstant **0,00105000** — die
Rundenkostenrate. Eine höhere Kostenquote bedeutet also zwingend einen
**engeren Stop**. Gemessen: die Wochenend-Stopweite ist das **0,724-fache** der
Werktags-Weite.

Die Kette, ganz:

1. Geringere Wochenend-Volatilität zieht strukturbasierte Stops zusammen —
   0,599 % statt 0,827 % des Einstiegs.
2. Die Rundengebühr ist fest, 0,105 % des Notionals.
3. Also steigt die Gebühr als Anteil der Stopweite von 6,7 % auf 8,9 %.
4. Der Deckel liegt bei 8 % — der Wochenend-Median überschreitet ihn.
5. Die Annahmequote fällt von 16,9 % auf 11,2 %.

**Das Wochenende wird nicht gemieden, weil es gefährlich ist, sondern weil es
teuer ist relativ zur verfügbaren Bewegung.** Das ist dieselbe Achse, an der
das ganze System hängt: die Bewegung gegen die Maut.

Das ist der Teil, in dem die Intuition des Nutzers recht hat, nur anders als
gemeint: die Frage war „warum tradest du am Wochenende so viel", und die
Antwort ist, dass das System dort **unterproportional** handelt — ohne dass es
ihm jemand gesagt hat, und aus einem Grund, den man benennen kann.

---

## 4. Was das Ergebnis nicht ist

**Es ist kein Negativbefund.** Die Replikationsseite fehlt: der 12-Markt-Lauf
hatte zum Messzeitpunkt einen Markt fertig. Drei Zellen sind auf der neuen
Seite nur deshalb nicht entscheidbar, weil die Besetzung fehlt. Das Skript
sagt das selbst — die erste Fassung druckte an dieser Stelle „keine Zelle hat
beide Tore genommen", was formal stimmte und inhaltlich täuschte. Der
Unterschied zwischen *nicht bestanden* und *noch nicht messbar* ist die Lehre
aus E11 und gehört in den Code, nicht in den Bericht.

**Und selbst ein positives Ergebnis wäre begrenzt.** Ein Zeitfilter ändert nur,
welche Trades existieren, nicht ihre Verteilung. Ein Hebel, der bloss die
Trade-Zahl ändert, kann das Vorzeichen nicht drehen — die Lehre, die schon an
der Trade-Zahl, der Positionsgrösse und dem Hebel hängt. E12 kann bestenfalls
eine Teilpopulation benennen, die für sich positiv ist, und müsste dann gegen
das gemessen werden, was das System **heute schon nimmt**, nicht gegen alle
Signale.

Bei −0,0207 R auf der Werktagsseite gibt es dort nichts, was durch Weglassen
des Wochenendes positiv würde: 516 von 2.734 Trades zu entfernen hebt den
Mittelwert von −0,0348 auf −0,0207 R. Das ist eine Verbesserung um 0,014 R und
bleibt negativ.

---

## 5. Offen

1. **Replikation** auf dem 12-Markt-Lauf, sobald er durch ist (~6 h) — aber
   **nur für E12.1 und E12.2.** E12.3 hat auf der alten Seite keine
   Vergleichsgruppe; dafür braucht es zwei Läufe gleicher Kadenz, und den
   zweiten gibt es noch nicht.
2. **Der alte 4-Markt-Baseline trägt keine Konfiguration.** Jeder Vergleich
   gegen ihn ist Archäologie. Der neue Runner schreibt `run_signature`,
   `signal_timeframe` und `execution_timeframe` je Datei und je Eintrag
   (Commit `6712704`); die Lücke bleibt für alles, was vorher entstand.
3. **Wodurch genau das Wochenende herausfällt.** Vermutung Kostentor; prüfbar
   über die Ablehnungsgründe im Signalspeicher, gruppiert nach Wochentag.
   Keine neue Messung nötig, nur eine Gruppierung.

---

*Quellen: Kim, Chan und Peter Reinhard Hansen, „The Quarter-Hour Effect:
Periodic Algorithmic Trading and Return Predictability in Cryptocurrency
Futures", arXiv:2607.09426.*
