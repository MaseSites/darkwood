# Bestand und Familien, 18.10.2026 — was da ist, und was damit messbar wäre

**Anlass.** Nach der Schliessung der alten Familie stand die Frage, welche der
fünf von der unabhängigen Prüfung genannten Familien hier überhaupt *messbar*
ist — nicht, welche attraktiv klingt. Sieben Agenten: einer nahm den Bestand
auf, fünf prüften je eine Familie, einer ordnete und prüfte die Belegstellen
gegen.

**Lesehinweis zur Beweislage.** Die Bestandszahlen in §1 habe ich **selbst
nachgemessen**. Die Familienmessungen in §3 sind **Agentenmessungen, von mir
nicht nachgerechnet** — sie sind als solche gekennzeichnet, und zwei davon
tragen so viel Gewicht, dass sie vor einer Entscheidung nachgerechnet gehören.

---

## 1. Der Befund, der grösser ist als die Familienfrage

**Der Datenbestand ist fünfmal grösser als sein Manifest sagte — und der Replay
lief nie über mehr als zwölf Märkte.**

Selbst nachgezählt am 18.10.2026:

| | Manifest sagte | **gemessen** |
|---|---|---|
| Marktverzeichnisse | 12 | **83** |
| mit vollem Ebenensatz (W1/D1/H4/H1/M15/M1) | — | **68** |
| Parquet-Dateien | 521 | **2.589** |
| Umfang | 867 MB | **3,76 GB** |
| Marktjahre insgesamt | — | **354,0** |
| davon in den zwölf aktiven genutzt | — | **72,2** |
| **ungenutzt** | — | **281,7 → Faktor 4,90** |

Und es sind keine dünnen Neulinge: **jeder der 68 trägt mindestens 1.837 Tage**
D1-Historie. Der kürzeste ist SOLUSDT mit 1.828 Tagen — und der ist schon einer
der zwölf aktiven.

### Was die 4,90x wert sind — gerechnet, nicht gehofft

Die operative Halbbreite (Bonferroni(73) + Cluster je Markt) fällt mit √4,90
von **0,0649 auf 0,0293**.

| Achse aus dem Blindfleck-Audit | Obergrenze | bei 12 Märkten | **bei 68** |
|---|---|---|---|
| Ausstieg sieht die Struktur | ~+0.12 R | 1,8x über der Grenze | **4,1x — klar messbar** |
| Balkentakt (Volumen/Dollar) | erwartet innerhalb ±0,077 | unentscheidbar | **entscheidbar** |
| `swing_lookback` + Detektorkonstanten | +0.011 R | 7x darunter | **noch darunter** |

**Aber sie machen das vorhandene Ergebnis nicht verlässlich negativ.** Dafür
bräuchte es eine Halbbreite unter 0,0129, also die **25-fache** Stichprobe.
4,90x reicht nicht. Mehr Märkte erhöhen also *nicht* die Chance, eine Kante zu
finden — sie machen zwei bis drei Achsen entscheidbar, und das ist alles.

### Was es kostet

Aus den gespeicherten Laufzeiten: Mittel **4.359 s je Markt**, Spanne 1.189 bis
33.707 s. 68 Märkte in **einem** Prozess sind **82,3 h CPU**, die 56
zusätzlichen 67,8 h. Der Rechner läuft auf Akku bei 37 % Takt, und neun
gleichzeitige Prozesse haben hier schon einmal sechs Stunden ohne ein einziges
Ergebnis gekostet.

`audit/DATEN_MANIFEST.yaml` ist korrigiert, mit dieser Rechnung darin.

---

## 2. Drei Datensätze, die niemand benutzt — und eine Namensfalle

**`data/signals.sqlite`: 67.985 Zeilen.** Die grösste Population des Projekts,
2021-01-25 bis 2026-10-18: 52.605 abgelehnte Signale **mit Grund** (Kosten
30.980, Chance-Risiko 24.774, Liquidation 21, Grenzen 17), 4.133 besetzte,
11.247 genommene, je mit Einstieg und Stop. Das erlaubt kontrafaktische
Rechnungen **ohne Neulauf**.

Zwei Vorbehalte, beide aus dem Bestand selbst: die Datei ist **lebendig**, ihr
Hash friert nichts ein (zwei Messungen zwei Stunden auseinander wichen ab), und
`signal_timeframe` ist in **67.985 von 67.985** Zeilen `M15` — hier ist kein
Zeitrahmen-Gradient zu finden.

**`data/quarantine/calibration.sqlite`: 2.734 Vorhersagen gegen 2.734
Ergebnisse**, über `decision_id` verknüpft, mit `predicted_probability`,
`raw_score`, `realized_net_r`, `realized_cost`, `realized_win`. Ein fertiger
Kalibrierungsdatensatz, den ein einziges Skript anfasst.

**`data/sentiment.parquet`: 3.160 Tageswerte** (Fear & Greed), 2018-02-01 bis
2026-09-30. Das Manifest führte es als *„status: leer, 0 von 12 Märkten"*.

**Und die Namensfalle:** `data/quarantine/` heisst so, ist aber für 456 der
460 MB **kein Abfall**, sondern der Arbeitsspeicher der Mikrostruktur-Studien —
acht Skripte schreiben dorthin und lesen davon. Tatsächlich aussortiert sind
**70 Zeilen in zwei Dateien, 8 KB**. Der grösste und am wenigsten bekannte
Posten des Projekts trägt einen Namen, der zum Wegsehen einlädt.

**Ein Fund, der kein Mangel ist:** `data/intents.sqlite` hat **0 Zeilen**.
Dieses Projekt hat nie eine Order geschrieben. Die Schranke steht also nicht nur
in Kommentaren.

---

## 3. Die fünf Familien — keine ist hier tragfähig

*Agentenmessungen, von mir nicht nachgerechnet. Die mit ⚠ markierten tragen so
viel Gewicht, dass sie vor einer Entscheidung nachgerechnet gehören.*

| Familie | machbar | warum sie fällt |
|---|---|---|
| **Market Making** | **offen** | Braucht durchlaufendes Quotieren auf einer handelbaren Venue. Lighter steht nicht in `venue.py`, Bybit hat null Mikrostruktur, jede Order braucht ein menschlich gehaltenes Token. ~~Und die Vorfrage fällt: 0,0 % der Orders am Quotierungsabstand überleben 30 Sekunden; der Spread-Term echter Maker scheitert am Replikationstor mit 113,5x.~~ **Am 19.10.2026 nachgerechnet, siehe Abschnitt 3a: die 0,0 % stimmen, messen aber die falsche Zeitskala; die 113,5x existieren nirgends.** |
| **Volatilitätsrisikoprämie** | teilweise | Weg (a) Optionen: das definierende implizite Bein fehlt **vollständig** und ist nur käuflich. Weg (b) Funding: machbar — und **dieselbe gescheiterte Carry-Familie unter neuem Namen**. Der Vola-Gradient, der sie unterscheiden würde (3,9x über die volle Historie), ist nach dem November-2024-Bruch verschwunden; jedes Vola-Terzil liegt danach nach Maut negativ. |
| **Optionskonvexität** | teilweise | ⚠ Die Kostenfrage ist schlüssellos entschieden: der Optionsanteil ist in **allen vier Verfallseimern 1,5–1,7x grösser** als die 0,105 % des Perps — das projekteigene Tötungskriterium ist erfüllt. Die PnL-Frage ist nicht machbar: Deribit bewahrt öffentlich nur den letzten Verfall auf (64 Instrumente, ein Termin). Und sie **erbt den Richtungsbefund vollständig** — eine 0,25-Delta-Option zu kaufen verlangt einen gerichteten 4–8-Stunden-Aufruf. |
| **Relative Value** | teilweise | Überraschend gut bei den Daten: die Spot/Perp-Zeitgleichheit ist **exakt** (33.013 von 33.013 auf der Stunde, 3,8 Jahre, 8 Märkte). Aber: der Same-Venue-Arm ist als **E6 schon erledigt_negativ** mit Vorzeichenwechsel in der Replikation; die Cross-Venue-Dislokation liegt selbst in ihrer extremsten Sekunde aus 24 Stunden noch **24-fach unter** der Maut von 280 bp; der Funding-Spread bräuchte 269 Tage und perfekte Voraussicht. Und ein Treffer wäre **nicht ausführbar**: Bybit hat keine einzige Kurszeile auf der Platte, `binance_spot` darf per Konstruktion nie eine Order tragen. |
| **Event-Trading** | teilweise | Von sechs Ereignisarten sind nur **zwei datierbar**. Die eine reichliche (Funding-Abrechnungen, 486.848 Ereignisse, 395.924 mit Preisfenster) ist gemessen und fällt am eigenen Befund: **+0,575 bp Drift plus 1,591 bp Funding gegen 10,0 bp Maut** bei einer Auflösung von ±0,374 bp. Das Makro-Fenster ist das einzige offene Stück, und seine Machtrechnung fällt vor dem Lauf. |

**Das Muster:** vier der fünf sind *messbar* und werden von der Messung
erledigt; eine ist strukturell unmöglich. Und drei von fünf erben den
Richtungsbefund ganz oder teilweise — Optionskonvexität vollständig, VRP(b) als
Carry unter neuem Namen, Relative Value nur in seiner Querschnittsvariante
(die ausdrücklich der alten Familie gehört).

**Nicht geerbt** wird der Richtungsbefund von: der Funding-Abrechnung als
Mikrostruktur-Ereignis (der Bedingungsgeber ist eine Zahlungsverpflichtung, kein
Preismerkmal), echter gehedgter Arbitrage (die Kursrichtung kommt in der
Zerlegung nicht vor) und Market Making im Ansatz (es verdient am Spread). Alle
drei fallen aus anderen Gründen.

---

## 3a. Nachtrag 19.10.2026 — die zwei ⚠-Zahlen nachgerechnet

Oben steht: *„Agentenmessungen, von mir nicht nachgerechnet. Die mit ⚠
markierten tragen so viel Gewicht, dass sie vor einer Entscheidung
nachgerechnet gehören."* Das ist jetzt geschehen, jeder Befund anschliessend
adversarisch gegengeprüft. **Die beiden Familien gehen verschieden aus.**

### Optionskonvexität — die Totzahl HÄLT

Der Widerlegungsversuch ist gescheitert. `cost.py` rechnet exakt die
berichteten **1,6 / 1,5 / 1,7 / 1,6x** nach. Über 133 Varianten (Haltedauer
1–24 h, fünf Delta-Bänder, vier Eimer) fallen nur drei unter 1,0x — alle bei
1 h Haltedauer und damit ausserhalb des projekteigenen 4–8-h-Fensters; das
Bootstrap liefert in keinem Eimer einen Zug unter 1,0x.

Zwei Verfeinerungen: über das echte 4–8-h-Fenster sind es **1,32–1,81x**,
nicht 1,5–1,7x. Und der gewählte Nenner (je Underlying-Notional) ist der für
Optionen **günstigste** — je Delta-Exposure sind es 5,63x, als Anteil der
Prämie 26,6 %. Gemessen ist der **Hausanteil** (Spread + Theta + Gebühr), nicht
die Prämie; die Commit-Nachricht `8915020` ist an dieser Stelle falsch
formuliert, dieses Dokument war korrekt.

**Eine Beweislücke bleibt und ist neu:** die tragenden Dateien liegen im
Sitzungs-Scratchpad, nicht im Repository. Eine Messung, die eine Familie
tötet und sich aus dem Projekt heraus nicht wiederholen lässt, ist nach den
eigenen Massstäben nicht reproduzierbar.

### Market Making — die Schliessung hält NICHT

Nicht, weil der Markt gut wäre. Aus drei Gründen:

**1. Die 0,0 % stimmen — unter der richtigen Lesart.** Ein Agent mass 1,667 %
und hielt die Zahl für gekippt; die Gegenprüfung hat ihn widerlegt. Er zählte
Orders, die sich bis zu **63 bp** wegbewegt hatten, und 24 % seiner
„Überlebenden" waren *andere* Orders auf derselben Kennung (geänderte
`initial_base_amount` — bei einer ruhenden Order unmöglich; `order_id` ist auf
dieser Venue ein **Slot**, keine Order-Identität). Richtig gelesen — dieselbe
Order, noch am Antritt — sind es **0,313 %**, für BTC/ETH/SOL **exakt
0,000 %** (60 % aller Beobachtungen), zweistufig gebootstrappt
[0,0000; 0,8701] %.

**2. Sie beantwortet die falsche Frage.** `scripts/collect_venue_tape.py:89`
setzt `BOOK_EVERY = 30.0` — das Buch wird **alle 30 Sekunden** aufgenommen,
kleinster gemessener Paarabstand 28,0 s. Ob eine Quote 1, 5 oder 20 Sekunden
steht, ist in diesen Daten nicht sichtbar, **und genau dort wird Market Making
entschieden.** Die Messung sagt „eine Quote überlebt keine 30 Sekunden" — was
niemand erwarten würde, der quotiert.

**3. Die 113,5x existieren nirgends.** `grep` über `audit/`, `docs/`,
`scripts/`, `src/` findet sie **genau einmal**: in derselben Tabellenzeile, die
sie als Beweis zitiert. Kein Skript, kein JSON, kein Logeintrag rechnet sie.

Dazu zwei Einschränkungen, die für jede Zahl dieser Familie gelten:

* `data/intents.sqlite` hat **0 Zeilen**. Dieses Projekt hat nie eine Order
  geschrieben; jede Überlebenszahl ist über **fremde** Orders gemessen — deren
  Warteschlangenposition, Storno-Logik und Latenz. Adverse Selektion sagt,
  dass ein langsamer Teilnehmer genau dann gefüllt wird, wenn es schlecht für
  ihn ist, und das ist hier nicht messbar.
* Die ganze Aufnahme ist **ein Kalendertag** (24,8 h, 07.–08.10.2026, sechs
  Märkte). Jedes „das Tor hält" daraus ist in-sample.

**Was zu tun wäre, um die Familie wirklich zu entscheiden:** eine
Buchaufnahme mit **1-Sekunden-Kadenz oder feiner**, über mehrere, zeitlich
getrennte Tage. Das ist Datenerhebung, keine Analyse — und sie existiert
nicht. Bis dahin ist Market Making **weder belegt noch widerlegt**, und das
ist etwas anderes als „fällt".

---

## 4. Zwei Beweislücken im eigenen Bestand

Der Bestandsagent hat zwei Stellen gefunden, an denen eine **berichtete** Zahl
nicht hält. Beide gehören nachgerechnet, bevor etwas darauf aufbaut:

1. **`audit/TAPE_VOLLE_ABDECKUNG.md` nennt 94,9 %** für die
   Binance-Gegenaufnahme. Nachgezählt über die aggTrade-Kennungen, Lücken
   herausgerechnet: **72,0 %** (BTCUSDT) und 71,0 % (ETHUSDT), im längsten
   zusammenhängenden Abschnitt von 2,8 h nur **64,8 %**. Jeder Cross-Venue-
   Markout auf dieser Seite ruht auf rund einem Drittel fehlender Trades.
2. **Die vier herkunftsgeprüften Funding-Dateien haben einen ungeprüften
   Schwanz.** Jede der zwölf trägt 34 Abrechnungen **nach** dem Ende der
   Beweislage (2026-10-07 08:00), und geschrieben hat sie der Pfad, der die
   Venue aus `config.engine.exchange.name` holt — und das ist seit je `binance`.
   Die vier Bybit-Dateien sind damit vermutlich in sich zeitlich gemischt, in
   genau den Dateien, die die geprüfte Ausnahme waren. Offline nicht beweisbar;
   der Cache endet vor dem Anhang.

Dazu ein alter Defekt, der **siebenmal breiter** geworden ist: die
Funding-Tabelle hat nur eine Spalte `rate`, die **realisierte**. Angekündigte
und abgerechnete Rate sind nicht getrennt. Das betraf zwölf Märkte und betrifft
jetzt 83 — und jede Carry- oder VRP-Familie, die eine Rate *vor* ihrer
Abrechnung als Merkmal nutzt, erbt ihn.

---

## 5. Was daraus folgt

1. **Die fünf genannten Familien sind geschlossen.** Keine ist hier tragfähig.
   Vier mit einer Zahl, eine strukturell.
2. **Der einzige neue Hebel ist Stichprobe, nicht Hypothese.** 4,90x liegen
   bereit und kosten 82 CPU-Stunden. Sie machen zwei bis drei offene Achsen
   *entscheidbar* — sie machen aber auch das vorhandene Ergebnis nicht
   verlässlich negativ, und sie erhöhen die Chance auf eine Kante nicht.
3. **Drei Datensätze erlauben Rechnungen ohne Neulauf** — 67.985 Signale mit
   Ablehnungsgrund, 2.734 Kalibrierungspaare, 3.160 Sentimentwerte. Das ist der
   billigste verbleibende Weg zu einer Messung, wenn man eine will.
4. **Zwei berichtete Zahlen halten nicht**, und eine davon (die 94,9 %
   Tape-Abdeckung) trägt frühere Befunde.

**Die Entscheidung bleibt beim Auftraggeber**, und sie lautet jetzt nicht mehr
„welche Familie", sondern: *ist noch eine Frage offen, die 82 CPU-Stunden wert
ist — oder ist der richtige Schritt, aufzuschreiben und aufzuhören?*
