---
typ: produkt-teil
projekt: TradingBrain
bereich: status
status: aktiv
aktualisiert: 2026-10-23
tags: [status, migration, execution, forwaertsstichprobe, plankonto, chartbild]
---

# Aktueller Stand

Stand dieser Notiz: **2026-10-21, 10:15** (Nachtrag Chartbild 23.10.). Vor der nächsten Fortschreibung den Repo-Stand erneut prüfen.

> [!info] 23.10. — Chartbild für Chat und Händler (Schatten, ohne Wirkung)
> Auf Wunsch des Eigentümers sehen beide Bots den Chart jetzt als Bild
> (PNG, Pillow, `src/traidingbrain/vision/`).
> - **Chat:** jede Nachricht bekommt ein Bild des Markts (Frage-Zeitebene + H4 + D1,
>   nur geschlossene Kerzen, Setups/Positionen eingezeichnet), über die Claude-CLI
>   im stream-json-Format (`vision/frage.py`).
> - **Händler:** jede neue Order wird gezeichnet (M15/H1/H4, Kerzen nur bis zum
>   Entscheidungsschluss) und Claude gefragt „nehmen/auslassen". **Nur
>   aufgeschrieben** in `data/vision_shadow_plan.sqlite` (+ PNGs), blockiert nichts,
>   nicht in der Signatur; Entscheidungsstempel unverändert (`0619b41ca4e4`).
>   Abschalten: `--ohne-chart-urteil`. Auswertung: `scripts/vision_report.py`.
> - Grund für Schatten statt Veto: das Bild enthält keine Kerze, die der Händler
>   nicht schon als Zahl hat. Ein Veto erst, wenn der Report die Null ausschliesst
>   (bei ~2 Trades/Tag frühestens nach Wochen).
> - Wirksam erst nach Neustart von Händler und Dashboard (Neustart-Budget beachten).

> [!info] 21.10. 12:46 UTC — Not-Aus aufgehoben, Papierhandel läuft wieder
> Auf Anweisung des Eigentümers („papertraide den ganzen Tag") ist
> `data/KILL_SWITCH` entfernt. Seine Bedingung war erfüllt: die zwei
> Gewinner-gegen-Verlierer-Regeln (`timeframes: [D1, H4, H1]`,
> `require_agreement: true`) stehen in `config_offen/settings.yaml`, der
> Händler läuft seit 12:39 UTC mit `|tf=D1,H4,H1|bild`. Inhalt und Grund
> des alten Not-Aus liegen in `data/KILL_SWITCH.aufgehoben-20261021`.
> Erwartung laut eigener Messung: Break-even (+0,002 R ungesehen), kein Vorteil.
>
> **13:00 UTC — Anzeige repariert (Layout, nicht committet):** die neue
> Signatur `…|tf=D1,H4,H1|bild|plan30x7r15f` liess das Dashboard ein neues
> Konto sehen — 0 von 26 Trades, kein Tagesverlauf. Die Ansichten
> (`api/portfolio.py` `gleiches_konto`, `api/paper.py`, `api/terminal.py`
> Verlauf) erkennen das Konto jetzt am Namen `plan`; alle 26 Trades sind
> zurück, heute 14 Trades / −87,98 USDT, Kasse 825,08. Nebenbei: der Verlauf
> zeigte die 11 `plan30x7`-Trades bisher doppelt. **Offen für den Kollegen:**
> die Verlustbremsen zählen weiter nach `konto_schluessel` und sehen in der
> neuen Konfiguration darum 0 Trades — dieselbe Lücke wie am 20.10.

> [!warning] E17 ist gelaufen — der Kandidat A D1+H4 ist TOT
> Der Abschnitt „Forschungsbefund P0a" unten beschreibt ihn noch als besten
> Kandidaten. Das gilt seit dem 20.10. abends nicht mehr. Siehe unten
> „E17 — out-of-sample".

## Alles zusammengelegt — 21.10. vormittags

`BELEGT` — **die Bewertungsschicht sagt über 7'335 Replay-Trades nichts
voraus.** Erstmals über alle zwölf Märkte geschnitten (bisher nur die 2'734
alten Vier-Markt-Zeilen): Rating ≥ 70 +0,002 R gegen Rating < 40 −0,004 R;
Widerspruch > 50 % −0,017 R gegen −0,012 R; „eindeutig" +0,040 R
[−0,019; +0,108], Intervall über null wie schon bei 588 Trades; Richtung
„mit Bild" −0,002 R gegen „gegen Bild" −0,054 R, Differenz unter der
Auflösung von 0,077 R. Die Zahl 1–100 im Terminal ist Beschreibung der
Indikatorlage, keine Prognose — das stand schon in
`WARUM_JEDER_TRADE_SO_ENDETE.md` (68,2 gegen 67,3) und gilt jetzt auch für
jede ihrer Teilgrössen.

`BELEGT` — **jedes Muster der 54 Live-Trades wurde gegen das Replay
gehalten, und keines ist dort.** Live: Shorts im Aufwärtstrend 2 von 10,
−0,52 R; Widerspruch > 50 % 1 von 9, −0,73 R; 00–08 UTC 1 von 10, −0,94 R.
Replay: Shorts im Aufwärtstrend −0,052 R (n=627), Widerspruch −0,017 R
(n=980), 00–08 UTC −0,024/+0,014 R (n=2'304). Das sind die üblichen
Stichprobenläufe einer Nacht, keine Regeln. Einzig die Zeitebene zeigt
live dieselbe Richtung wie das Replay (M15 −0,22 R live, −0,073 R Replay
für Setup A) — und genau dieser Hebel ist mit E17 out-of-sample gefallen.

`BELEGT` — **das Plankonto handelt seit dem 20.10. gegen den einzigen
Befund dieses Projekts mit einem Intervall ohne Null.** Billige Trades
(Kostenanteil ≤ 0,08) haben über 43'727 Signale die bessere
Brutto-Erwartung (+0,0561 R [+0,017; +0,097]) und netto −0,0097 gegen
−0,2111 R. Mit `max_cost_fraction_of_risk: 1.0` in `config_offen` nimmt das
Plankonto diese teure Population: 21 Trades unter offenen Toren laufen auf
−0,319 R je Trade, 13 davon über dem alten Kostentor. Das ist die gemessene
Erwartung dieser Population, kein Pech. Die Entscheidung bleibt beim
Eigentümer (mehr Trades gegen bessere Trades), aber sie steht jetzt neben
ihrer Zahl.

`LAYOUT` — **TradingView-Bedienung im Terminal** (21.10. nachmittags, Branch
`layout`, `ea884c5`): Tastenkürzel, Skalen, Charttypen, Countdown,
Zeichnungsverwaltung, Watchlist, Mehrfach-Layout D1/H4/H1/15m, Bar Replay,
Vergleich. Liste und Gründe für das Weggelassene in
[[🖥 Darkwood Terminal — Oberfläche & Bewertungsschicht]]. Vorher am selben
Tag: Leiste unter dem Chart ließ sich nicht öffnen (`808072c`).

`ENTSCHIEDEN` — **Ab 21.10. ~14:15: diese Session nur noch Layout, Analysen
beim Kollegen.** Alles gepusht (`freqtrade-core` auf `0569ed4`), Branch
`layout` angelegt und gepusht. Pfad-Zuständigkeiten und die offenen
Betriebspunkte (Kill-Switch-Freigabe nach Neustart, E24-Auswertung, E25,
E26, E27) stehen in [[🤝 Übergabe Claude ↔ ChatGPT ↔ Codex]].

`ENTSCHIEDEN` — **Gewinner gegen Verlierer, und zwei Regeln daraus** (21.10.,
13:10). Auftrag: „was hast du bei den Gewinnern anders gemacht, mache es
wieder; keine Trades, bis du bereit bist." Kill-Switch seit 11:10 UTC, offene
Positionen laufen aus. Jede Differenz der 59 Live-Trades gegen das Replay
(7'335) und gegen 39'075 Trades auf 56 ungesehenen Märkten gehalten
(`audit/GEWINNER_GEGEN_VERLIERER_21OKT.md`). **Dreifach bestätigt:** M15-Setups
sind überall die schlechteste Ebene (ungesehen 34,6 % / −0,064 R gegen
37,9 % / +0,001 R); Trades gegen das Gesamtbild sind überall schlechter
(32,4 % / −0,072 gegen 37,4 % / −0,019). **Rauschen:** Widerspruch, Rating,
Regime, Seite, Stunde, Markt, Setup B/G. Umgesetzt im Plankonto:
`setups.timeframes [D1, H4, H1]` und `require_agreement: true`, Signatur
`|tf=D1,H4,H1|bild`, neuer Grund `Rule.PICTURE`. Erwartung vorab, ehrlich:
Break-even (+0,002 R, 39 % Treffer out-of-sample), halb so viele Trades, sechs
von zehn weiter im Stop. Vorwärtstest E27 registriert (frühestens 100 Trades,
bis dahin keine Anpassung). Neustart beim flachen Konto, danach Freigabe.

`LÄUFT` — **E26-Sammler eingerichtet** (21.10., ~12:50): geplante Aufgabe
`traidingBrain-ebenen` schreibt alle 15 Minuten je Markt eine Zeile in
`data/ebenen.sqlite` — Minuten bis zum nächsten Kalendertermin (high/medium,
7-Tage-Horizont, nur bekannte Termine) und für BTC/ETH den Abstand zum
nächsten grossen Options-Strike (≥ ¼ des grössten OI) sowie zum grössten
Strike. Nur Aufzeichnung, kein Eingriff in den Entscheidungspfad. E26 im
Register vorregistriert (`total_comparisons` 82), Auswertung frühestens nach
vier Wochen und 200 Trades je Arm; Erwartung vorab gering. Stand:
`python scripts/record_ebenen.py --status`.

`GEPRÜFT` — „schaue das alles auch an" (dreizehn Terminal-Ebenen): fünf sind
die Setups selbst, sechs sind Anzeigeebenen aus Familien, die am 14.10. als
Prädiktoren geschlossen wurden, zwei Einzelgrössen (Kalenderabstand,
Strike-Abstand) sind nie geprüft und nur vorwärts messbar. Tabelle in
[[🖥 Darkwood Terminal — Oberfläche & Bewertungsschicht]]. Keine Ebene
schaltet einen Einstieg ohne Messung.

`ENTSCHIEDEN` — **Die Vorgabe 20x in sechs Monaten bleibt bestehen**
(Eigentümer, 21.10. nach der Durchbruch-Analyse). Sie gilt als Entscheidung,
nicht als Messergebnis: +1,66 % je Tag, +0,4536 R je Trade. Konsequenz im
Register (`meta.goal.bestaetigt_21_10_2026`): jeder Arm wird gegen +0,4536 R
geprüft, Fenster 21.10.2026 → 21.04.2027, sofern kein anderes Startdatum
genannt wird. Der einzige Pfad mit positiver Messung ist Market Making BTC
auf Lighter; dafür ist **E25** vorregistriert (Beständigkeit derselben Maker
über eine Woche, zwei Tore, null Risiko, `total_comparisons` 80). Hält E25,
folgt E0 (eigene Füllmessung mit echtem Unterkonto, 100 USD Deckel). Fällt
E25, hat die Vorgabe keinen Pfad mit positiver Messung mehr. Für die
laufende Setup-Familie ändert die Bestätigung nichts. **Abdeckung:** die
WS-Aufnahme (`data/quarantine/venue_ws`, BTC/ETH/SOL) läuft seit 20.10. 09 h
ohne Lücke, Stand 21.10. 11 h rund 27 h; sieben Tage sind am **27.10. ~09 h**
voll. Die Tape-Aufnahme hat eine Lücke 08.–19.10. und läuft seit 19.10. 19 h.

`ANALYSE` — Auftrag „was brauchst du für den Durchbruch": beantwortet in
[[🎯 Was ein Durchbruch bräuchte — 21.10.2026]]. Kern: +0,10 R je Trade
wäre schon 3,5× im Halbjahr, aber kein Arm ist von null zu trennen und
+0,10 R bräuchte 13 Monate Vorwärtslauf zum Nachweis. Der Durchbruch liegt
in einer anderen Ertragsquelle (einzige positive Messung: BTC-Maker auf
Lighter, +4,47 bp/Tag, zwei Hürden), Echtzeit-Buch statt Polling, und einer
eigenen Füllmessung mit ~100 USD echt. Sechs konkrete Bedarfe, drei Verbote.

`LÄUFT` — **E24 ist gebaut und rechnet** (21.10., ab ~11:30, drei Stränge,
`data/dienst/e24_strang*.log`). Der Eigentümer hat nach der Erwartung
„unentschieden" trotzdem bauen lassen. Bau: `src/traidingbrain/data/takt.py`
erzeugt Volumen- und Dollar-Balken aus den Minuten (Schwelle = Mittelwert der
M15-Grösse je Markt, Hierarchie 1:4:16:96:672; Mittel statt Median, VOR dem
Lauf im Register begründet). Jeder Takt-Balken trägt `close_ts`; Pipeline,
Snapshot, Motor und Journal lesen die Spalte, wenn sie da ist, sonst rechnen
sie wie bisher — der goldene Zeitbalken-Lauf in `tests/test_backtest.py` ist
unverändert grün. Rauchtest BTC: 165'988 Takt-Balken gegen 176'975 M15-Kerzen,
mittlere Dauer 15,8 min. Ausgabe `data/replay_fills_e24/<arm>/`, Auswertung
`python scripts/study_e24_takt.py --auswerten` → `audit/E24_ERGEBNIS.md`. Tor
(c) auf 56 Märkten nur, wenn (a) und (b) auf zwölf halten.

`REGISTER` — Auftrag des Eigentümers 21.10.: „Aufgaben, die uns overpowered
machen, damit wir praktisch nur noch gewinnen". Antwort aus dem Register, nicht
aus dem Bauch: **E1** (alle Merkmale per Modell verbinden) ist gelaufen und
gefallen (−0,10 / −0,07 R, besser als Zufall, absolut negativ) — der Status
stand fälschlich noch auf „registriert", nachgetragen. **E13** und **E17**
ebenfalls nachgetragen. Die beste je gemessene Zelle hat 47,1 % Treffer
(A D1, n=172); „nur gewinnen" bräuchte bei fester Auszahlung 66,75 % für 20x.
**E24 Volumen-/Dollar-Takt** vorregistriert (`total_comparisons` 77 → 79): der
einzige Kandidat ohne arithmetische Decke, Erwartung des Prüfers
„unentschieden innerhalb ±0,077 R", Umfang Tage. Wird nur gebaut, wenn der
Eigentümer es nach dieser Erwartung noch will.

`ENTSCHIEDEN` — **Kostentor im Plankonto zurück auf 0,08** (21.10., ~10:20,
auf Entscheidung des Eigentümers). `config_offen/risk.yaml`
`max_cost_fraction_of_risk: 1.0 → 0.08`, mit datiertem Kommentar. Das
CRV-Tor (`min_reward_risk: 0.01`) bleibt offen, das war nicht Teil der
Entscheidung; der Händler druckt deshalb weiter „<<< OFFEN". Die Signatur
wechselt von `…|1.0|M15|…` auf `…|0.08|M15|…`, Trades beider Epochen bleiben
trennbar. Preis: ~81 % der Signale der letzten 24 h lagen über 0,08, also
rund 5 statt 26 Trades je Tag. **Der Neustart wartet auf ein flaches Konto**
(Wächterskript pollt die Zyklus-Zeile, beendet `plantrade.py` bei „0 offen",
der Wrapper startet nach 60 s neu), weil der Stempel beim Schliessen
geschrieben wird. Vier Positionen waren offen, als die Entscheidung fiel.

`BEHOBEN` — drei falsche Lehren im Handelsbuch: der feste Schlusssatz „in R
ist die Summe positiv" (stand bei −6,70 R weiter da; jetzt vorzeichenabhängig),
„nie im Plus, Einstieg von der ersten Kerze an falsch" bei Zielgewinnern
unter einer Kerze Länge (jetzt „nicht beobachtbar": 3 Trades nie im Plus, 7
unbeobachtet, nicht 10), und „die Familien widersprachen sich — das war kein
klares Bild" als Erklärung (jetzt mit der Replay-Zahl, die sagt, dass es keine
ist).

`BEOBACHTET` — das Plan-Dashboard starb zwischen 23:32 und 08:45 fünfzehnmal
mit −1, der Neustartzähler des Wrappers stand auf 20 und wurde um 08:29 von
Hand zurückgesetzt; seit 08:45 läuft es (Journal-Endpunkt antwortet 200).
Ursache im Log: `ImportError JournalStore` aus einem Stand vor der Reparatur.
Zwischen 08:29 und 08:45 liefen zeitweise mehrere Wrapper auf demselben Port
(Zähler 1/7/4/15 durcheinander).

**Stand Plankonto:** 22 geschlossene Trades, −6,70 R, −160,44 USD, Treffer
8 von 22. Letzte acht Trades (21.10. 00:05–05:47 UTC) sieben Verlierer, davon
sieben Shorts in einem steigenden Markt — `max_same_direction: 2` ist seit
09:44 scharf und hätte davon den dritten und folgende abgelehnt.

## E23 und die Wächter — 21.10. nachmittags

`BELEGT` — **E23 ist gelaufen und überholt E20**
([[🔬 E23 — Lighter Maker-P&L, beobachtet statt geschätzt]]). 974'938
Geschäfte über 24 h: BTC-Maker behalten ihren Spread auf jedem Horizont,
ETH- und SOL-Maker geben ihn binnen zehn Sekunden zurück. E20 hatte den
GESTELLTEN Touch-Spread gemessen und die Märkte genau umgekehrt gereiht.

`BELEGT` — die Zerlegung in Ausführung und Altbestand zeigt: SOL sieht
profitabel aus (+43'176 USD), aber das Handwerk verlor −21'186 und die
Rallye rettete es. BTC gewinnt am Handwerk (+275'696 von +349'205).

`OFFEN` — ob wir Market Making betreiben sollten, ist damit NICHT
beantwortet: die Füllquote von 2.880 % (E20) steht zwischen „andere
verdienen hier" und „wir können es".

`BELEGT` — die Wächter in `scripts/verify_claims.py` sind von 8 auf 11
gewachsen: Märkte mit Kerzen (**83**, nicht 12 und nicht 102 — beides
Zählfehler von mir am selben Tag), Risikodeckel im Plankonto (1,5 %),
Epochen des Plankontos (2). Alle elf grün.

`KORREKTUR` — der Anteil teurer Signale ist **81 %** der letzten 24 h, nicht
43 %. Die 43 % waren über die ganze Historie gerechnet. Das Kostentor zu
schliessen kostet damit 26 → 5 Trades je Tag, nicht ein Fünftel davon.

## Verlustanalyse — 21.10. mittags

`BELEGT` — der Verlust des Plankontos ist zerlegt
([[💸 Verlustanalyse Plankonto — 21.10.2026]]). Über 19 geschlossene Trades:
brutto −116,84, Gebühren −22,22, Funding −0,19 → netto **−139,25 USD**.

`BELEGT` — **57 % davon ist Positionsgrösse, nicht Richtung.** Bei gleichem
Risiko je Trade hätten dieselben R-Werte −60,54 USD ergeben. Verlierer trugen
17,26 USD Risiko gegen 8,86 bei Gewinnern, weil ihre Stops fast doppelt so
weit lagen.

`BELEGT` — die naheliegende Lehre hält NICHT: in R sind weite Stops −0,3414
gegen −0,0957 bei engen, also 0,25 R Unterschied bei einer Streuung von 1,25 R
und n=19. Unter der Auflösung.

`BELEGT` — der 1,5-%-Risikodeckel wirkt: Asymmetrie von 2,63× auf 1,39×, und
die zweite Epoche lief in R viel schlechter (−4,612 gegen +0,337 R) und
kostete weniger als die Hälfte.

`ENTSCHIEDEN` — neu: `max_same_direction: 2`, nur im Plankonto. Zwei
Fünfzehn-Minuten-Kerzen erzeugten 42 % aller Trades und kosteten 90,61 USD,
beide gleichgerichtet. Wirksam mit dem nächsten Neustart des Händlers, der
wartet, bis das Konto flach ist.

`BELEGT` — Haltedauer: Median 31 Minuten, längster Trade 4,08 h. Es gibt
**keinen Zeitausstieg** — lange Trades sind erlaubt, sie entstehen nur nicht,
weil Stop und Ziel auf M15 nah beieinanderliegen.

`OFFEN` — 20 von 47 genommenen Live-Signalen (43 %) liegen über dem alten
Kostentor. Gegen einen Befund aus 7.335 Trades: billige Trades haben die
bessere Brutto-Erwartung. Produktentscheidung, nicht einseitig getroffen.

## Terminal und Bewertungsschicht — 21.10. vormittags

`BELEGT` — die Oberfläche hat jetzt eine **Aufschlüsselung je Faktor**: ein
Klick auf eine Bot-Karte zeigt die Einzelmessungen darunter (180 bei
„Indikatoren") mit dem vollen Rechenweg ihres Gewichts. Details und die
Quellenlage je Ebene stehen in
[[🖥 Darkwood Terminal — Oberfläche & Bewertungsschicht]].

`BELEGT` — neu und mit gemessenen Zahlen: Zonen einzeln bewertet, grosse
Trades mit Beträgen (Schwelle = oberstes Promille des Tages, auf BTC
711'227 USD je Abschluss), Options-Gamma je Strike als **Betrag ohne
Vorzeichen**, Handelsjournal mit Begründung je Trade.

`BELEGT` — **keine GEX-Linie, keine Liquidationsebene, kein Etikett
„institutionell".** Begründungen in
[[📡 Datenquellen — was es gibt und was nicht]].

`BELEGT` — ein struktureller Anzeigefehler behoben: `current_era` verglich
gegen `run_signature(config)` **ohne** den Konto-Zusatz `|plan30x7r15f`, der
aus `config_offen/plan.yaml` kommt und dort nicht vorkommen kann. Der
Vergleich traf **nie** — acht geschlossene Trades im Journal, „0 Trades" in
der Schlagzeile, −40,24 USD in der Tabelle darunter.

`BELEGT` — Kontostand am 21.10. um 08:30: **860,75 USD** von 1.000, vier
offene Positionen, 20 abgeschlossene Trades über alle Epochen des
Plankontos: −4,2750 R / −139,07 USD, Treffer 8 von 20.

`BELEGT` — der Mechanismus dahinter, aus dem Handelsbuch: durchschnittliches
Risiko **7,75 USD auf Gewinnern gegen 17,26 USD auf Verlierern** (Faktor
2,23). Darum ist dasselbe Konto in R weniger negativ als in Geld.

## Projektzustand

- `BELEGT` — letzter committeter Projektstand bei der Migration: `c88553f`.
- `BELEGT` — im Arbeitsbaum liegen uncommittete Änderungen von Claudes laufender Phase 2. Diese Migration hat sie nicht berührt.
- `BELEGT` — vorherige Phasen-Commits: `ab67b34` (Vorwärtsstichprobe isoliert), `4d8eefc` (mypy 20 → 17), `c88553f` (Derivate fail-closed / Venue-Provenienz).
- `BELEGT` — die laufende Vorwärtsstichprobe meldete Entscheidungscode `d8c7f12104e4` auf Commit `de3c0ee`; Händlerstart 2026-10-16T04:58:30Z. Das Dashboard lief separat auf `b51160e`.
- `BELEGT` — der Händler wurde durch die späteren Commits nicht neu gestartet; die Stichprobe ist deshalb als eigene Epoche zu behandeln.

## Forschungsbefund P0a

- `BELEGT` — Legacy-Population: 7.335 Fills; vorhandene Kennzahl durchschnittlich **−0,0129 R**.
- `BELEGT` — die bisher geprüften sechs Arme lieferten keine ausreichende robuste Kante.
- `MODELLIERT` — bester bisheriger Kandidat A D1+H4: ungefähr **+0,0856 R** in-sample, nach realistischerer Ausführung ungefähr **+0,0728 R**.
- `BELEGT` — die gemessene Gebührenkorrektur schließt nur ungefähr **0,3 %** der für das Wachstumsziel berechneten Lücke.
- `BELEGT` — die vorhandene Zahl ist als **“Conditional simulated net R under the Legacy fill and fee model”** zu beschriften. Sie ist weder ein Live-Ertrag noch eine gemeinsame Portfolio-Kante.

## Ausführung und Daten

- `BELEGT` — der Legacy-Simulator nahm LIMIT-Einstiege und Targets als Maker an, ohne diese Rolle historisch beweisen zu können.
- `BELEGT` — OHLCV enthält kein zeitgleiches Bid/Ask und kann PostOnly-Marketability nicht exakt prüfen.
- `BELEGT` — auch L1 plus Trade-Tape beweist ohne Queue-Position nicht, ob die eigene Order gefüllt worden wäre.
- `MODELLIERT` — Taker/Taker plus Slippage ist eine kostenkonservative Schranke, aber keine historisch belegte Fill-Wahrscheinlichkeit.
- `BELEGT` — Venue wird in Phase 1 auf Verzeichnisebene und als Pflichtspalte geführt; acht alte Parquet-Dateien blieben dabei byte-identisch.
- `BELEGT` — `analysis/context.py` behielt für die isolierte Stichprobe absichtlich die alte Bybit-Positionierungsquelle neben Binance-Kerzen. Diese Mischquelle ist dokumentiertes Erbe, kein Zielzustand.

## Prüfstand

Vor den laufenden Phase-2-Änderungen war gemessen:

- `pytest -q -p no:randomly`: 1.772 gesammelt, 26 übersprungen, 0 Fehler, Exit 0
- `ruff check src tests scripts`: sauber
- `mypy --strict src`: nach Phase 0 noch 17 Fehler; 14 davon im optionalen, nicht importierbaren MCP-Adapter

Diese Zahlen gelten nicht automatisch für den aktuell uncommitteten Arbeitsbaum.

## Unmittelbar offen

1. Claude Phase 2 fertigstellen lassen und danach Commit, Diff, Teststand und neue Entscheidungen übernehmen.
2. Vorwärtsstichprobe unverändert lassen, solange ihre Auswertungsregel nicht erreicht oder ausdrücklich beendet ist.
3. Venue-/Environment-Bindung und ausführbare Bybit-Semantik beweisen.
4. Signal-/Marktausgang strikt von Execution Feasibility trennen.
5. Keine Live-Leistungsbehauptung aus Legacy- oder Paper-Ergebnissen ableiten.

## Zweites Papierkonto — Plan 30 % × 7× (seit 2026-10-19)

- `BELEGT` — läuft getrennt vom bestehenden: Speicher `data/plan_paper.sqlite`,
  Laufsignatur mit Zusatz `plan30x7`, Risikodeckel 35 % je Trade **im Sizer** geprüft
  (`forward_sizer(max_risk_share=…)`, lehnt ab statt zu kürzen). Start 1.000 USDT als
  EINE Kasse, nicht als zwölf Einzelkonten.
- `BELEGT` — zwei Dashboards: bestehend auf `127.0.0.1:8787`, Plankonto auf `:8788`.
  Beide Ansichten (Trades, Verlauf) sind seit `0d12eba` kontobezogen gefiltert;
  **gelöscht wurde nichts**.
- `BELEGT` — Vorwärtsbemessung heißt: Risiko ist ein **Ergebnis**, keine Eingabe. Über
  die 7.335 Replay-Trades riskiert diese Regel im Median 4,38 %, im 99. Perzentil
  30,62 % des Kontos. Darum eigene Risikokonfiguration und eigener Speicher.
- `BELEGT` — Vorabmessung derselben Regel auf denselben Trades: Höchststand 9.695 CHF
  nach 410 Trades, Kontoboden nach 787; 0 von 300 Umordnungen endeten über dem Start.
- `BELEGT` — zum Zeitpunkt dieser Notiz **null abgeschlossene Trades**. Es existiert
  keine Leistungsaussage über dieses Konto, weder positiv noch negativ.

## Behobene Messfehler in der Anzeige (2026-10-19)

- `BELEGT` — `/api/state` las ein Feld, das im Betrieb niemand setzt; beide Dashboards
  meldeten dauerhaft „A risk limit is blocking new trades". Behoben in `103907f`.
- `BELEGT` — dahinter: die drei Verlustsicherungen des Dashboards rechneten gegen
  `initial_equity` (1.000) statt gegen den Kontostand (11.775) — Tagesdeckel 54 statt
  rund 589. Quelle ist jetzt `account_equity`.
- `BELEGT` — der **Händler** war nie betroffen (`broker.equity`, `live/paper.py:833`).
  Das Tor gilt nur für Handbestätigungen, und unarmiert kann nichts gesendet werden.
- `BELEGT` — beide durch Rückmutation gegengeprüft; fünf neue Tests fallen auf dem alten
  Code mit genau dem Symptom.

## Autoritative Repo-Quellen

- `C:\Users\sever\OneDrive\Desktop\traidingBrain\audit\CHATGPT_BRIEFING_02.md`
- `C:\Users\sever\OneDrive\Desktop\traidingBrain\audit\P0A_LEGACY_FREEZE.md`
- `C:\Users\sever\OneDrive\Desktop\traidingBrain\audit\p0a_manifest.json`
- `C:\Users\sever\OneDrive\Desktop\traidingBrain\audit\FORWARD_SAMPLE_ISOLATION.md`
- `C:\Users\sever\OneDrive\Desktop\traidingBrain\audit\PHASE0_MYPY.md`
- `C:\Users\sever\OneDrive\Desktop\traidingBrain\docs\TRADING_BRAIN_ZUSTANDSBERICHT.md`

## E17 — out-of-sample, 20.10.2026 abends

`BELEGT` — der Replay über **68 Märkte** ist durch; die vorregistrierte
Auswertung urteilt:

| Arm | in-sample | ungesehen (56 Märkte) | Tor 1 | Tor 2 |
|---|---|---|---|---|
| A auf D1+H4 | +0.0856 R | **+0.0341 R [−0.0694, +0.1377]** | gefallen | bestanden (0.65×) |
| alles ohne M15 | — | +0.0006 R | gefallen | gefallen (0.35×) |
| Basis | −0.0132 R | −0.0349 R [−0.0915, +0.0218] | gefallen | gefallen |

`BELEGT` — Das Register verlangt **beide** Tore. Ein bestandenes Tor 2 bei
gefallenem Tor 1 heisst: der Effekt wiederholt sich in der Grössenordnung,
ist aber nicht von null zu unterscheiden — also war er nie da.

`BELEGT` — Der Lauf brach zuerst auf gemischten Entscheidungscodes ab
(28× `0311ffba621b`, 40× `d435dfde8083`). Nachgesehen statt umgangen:
`git diff fc6f014 61020fa` zeigt im `src`-Baum **nur `journal/version.py`** —
den Stempelrechner selbst. Analyse, Simulator, Ausführung, Daten sind
byte-gleich, `run_signature` ist bei allen 68 Dateien identisch. Die Sicherung
bleibt scharf und bekam einen **belegpflichtigen** Ausweg
(`--gemischt-erlauben "<Begründung>"`, die Begründung landet im Ergebnis-JSON).

## Plankonto, 21.10. 00:30

`BELEGT` — Stand **913.06 USD** von 1'000 Start. 13 abgeschlossene Trades,
54 % Treffer, Höchstrückgang −14.5 %.

`BELEGT` — **Die Verlustbremsen lasen nur die laufende Signatur.** Als am
20.10. der Risikodeckel dazukam, wechselte der Zusatz von `plan30x7` auf
`plan30x7r15` — und die Tagesbremse sah null Trades statt elf. Ein Druck auf
„Apply" im Terminal setzte Tages-, Wochengrenze und Abkühlung auf null, genau
dann, wenn jemand nach einem schlechten Tag an den Einstellungen dreht.
Behoben: `journal/history.konto_schluessel` + `account_trades`.

`BELEGT` — Die Lockerung der Grenzen (Tag 25 %, Woche 50 %, Abkühlung nach 8)
war **nicht** die Ursache der Freigabe; der Signaturwechsel hatte sie Stunden
vorher gelöst. Der Signaturzusatz trägt dafür jetzt ein `f`.

## Terminal, 20./21.10.

`BELEGT` — Zwei Abteile (Indikatoren/Settings), **zwölf** einstellbare
Indikatoren mit eigenen Achsen für RSI/MACD/Stochastik/ATR/Volumen.

`BELEGT` — **Siebzehn Zeichenwerkzeuge**; Punkte in Zeit und Preis, nie in
Pixeln. Jede gesetzte Zeichnung wird gegen das Gemessene gehalten (Zonen,
Pools, Lücken, Ereignisse, ATR als Massstab) — drei Urteile, Widerspruch ist
eines davon.

`BELEGT` — Konto-Tab neu, Verlauf eingegliedert und als eigener Reiter
gelöscht. Sechs Kacheln mit Zahl, Einordnung **und Begründung**.

`BELEGT` — Echtes Volumenprofil mit VPOC aus `data.binance.vision`. Siehe
[[📡 Datenquellen — was es gibt und was nicht]].

## Offen

- Trading Journal im Trades-Tab, mit Rückkopplung ins Gehirn
- Faktor-Aufschlüsselung im Bot-Panel (Klick → Unterfaktoren mit Gewicht,
  Rating, Begründung)
- Heatmap: Tardis-Gratistage holen und **messen**, bevor ein Dauersammler läuft
- E22 Trail (vorregistriert, jetzt durch E17 entsperrt)
- Max 2 gleichgerichtete Positionen (`risk/limits.py`)
