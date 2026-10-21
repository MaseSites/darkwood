---
typ: produkt
status: aktiv
branche: Krypto-Trading / Analyse-Software
look: dunkles Terminal (Blau-Schwarz #060910), monospace Zahlen, keine Schatten
ort: lokal
kontakt: —
angebotssumme: —
naechster_schritt: WARTEN, und zwar begruendet. Die homogene Vorwaertsstichprobe steht bei 13 von 41 noetigen Trades, Mittel +0,5075 R (gefallen von +0,7867 nach zwei weiteren Verlusten -- sechs in Folge). Bei 1,9 Trades/Tag faellt die Antwort um den 25.10.2026, VOR dem Stichtag. Bis dahin NICHTS am Papierhandel aendern, was veraendert welche Trades entstehen. Offen und ungemessen: der Fehler-Ausbruch wiederholt sich im Tagesfenster gegen 08:30 UTC (09.10. 47 Prozent, 10.10. 77 Prozent) -- zu klaeren mit einem gleichzeitigen Abruf einer zweiten, unabhaengigen Adresse WAEHREND des Fensters.
letzter_kontakt: 2026-10-10
projektordner: "../../../traidingBrain"
tech: Python 3.14, pandas/numpy, ccxt (Binance USD-M; Bybit bleibt ein Config-Schalter), pydantic v2, FastAPI, SQLite/Parquet/DuckDB, anthropic SDK; zweiter venv mit Freqtrade 2026.9 + FreqAI (LightGBM/XGBoost/sklearn), lokaler MCP-Adapter
deploy: nur lokal; kein Hosting geplant. Code auf GitHub: https://github.com/MaseSites/TraidingBrain (privat gesichert, kein Deploy-Ziel)
aktualisiert: 2026-10-10
tags: [produkt, python, trading, krypto, claude-api]
---

# traidingBrain

> **Stand 2026-10-10 — es gibt einen Termin, und bis dahin ist Warten die
> Handlung.** Der Papierhandel laeuft seit dem 02.10. auf zwoelf Perps, Konto
> **12 064,96 USDT** von 12 000 Start. Entscheidend ist nicht dieser Betrag,
> sondern: **24 Experimentfamilien sind abgeschlossen, keine hat einen
> Kandidaten ergeben.** Gemessen ueber 2 734 Replay-Trades verliert das System
> **-0,0906 R je Trade**; das Ziel verlangt bei der gemessenen Rate von 1,9
> Trades/Tag **+0,8701 R**. Die Einstiege tragen brutto keinen Vorteil (E8: das
> Beta zum Kryptomarkt ist 0,985, daneben liegt nichts).
>
> **Der Termin:** ein Vorteil, der fuer das Ziel reicht, waere nach **41**
> Vorwaertstrades nachweisbar. Homogen vorhanden sind **13** — Mittel
> **+0,5075 R**, gefallen von +0,7867, weil zwei weitere Trades verloren
> haben. Das sind **sechs Verluste in Folge**, und die Trefferquote fiel von
> 63,6 auf 53,8 Prozent. Die vorab festgelegte Gegenerwartung aus dem Replay
> ist **-0,0867 R bei 35,4 Prozent**, und der Abstand dazu schrumpfte von 2,06
> auf 1,52 Standardfehler — unter der unkorrigierten Schwelle von 1,96. 28
> fehlende Trades sind 15 Tage: **~25.10.2026**, vor dem Stichtag.
>
> **Neu am 10.10., und es kostet Zeit statt Geld:** der Fehler-Ausbruch hat
> sich wiederholt, **77 Prozent** gegen 47 am 09.10., identische Signatur
> (`fetch_ohlcv(.., W1)`, alle zwoelf Maerkte). Beide Ausbrueche liegen im
> selben Tagesfenster, Ende gegen 08:33 UTC. Drei von vier Entscheidungen
> fielen nicht. Kein Geld verloren — der Broker holt 240 Minuten nach.
>
> **Was jetzt aufpasst, statt nachtraeglich rekonstruiert zu werden.** Am
> 09.10. musste die Stichprobe dreimal nachgeschnitten werden und zweimal war
> die Begruendung falsch. Dagegen stehen seit dem 10.10. zwei Instrumente:
> ein **Golden-Test** ueber den echten Live-Entscheidungspfad (faellt bei
> geaenderter Entscheidungslogik — mit Mutationsprobe belegt) und
> **`decision_version`**, ein Stempel ueber die Bedeutung des entscheidenden
> Codes, der sich bei einem Bericht nicht bewegt und bei
> `MAX_DECISION_ATTEMPTS` schon. Der Stempel trennt die Stichproben, der
> Golden-Test sagt, ob sie getrennt werden muessen.
>
> Alle Zahlen mit Befehl und Intervall in `audit/` im Projektordner, Einstieg
> `docs/TRADING_BRAIN_ZUSTANDSBERICHT.md` und
> `audit/PFLICHTENHEFT_KANDIDAT.md` (woran ein Kandidat zu erkennen waere).
> Keine Echtgeld-Anbindung, keine Order, kein Broker — und P33 (Alter,
> Rechtslage) ist unveraendert offen.

> **Wissensstand 2026-09-30:** `TRADING_ANALYSE_GRUNDLAGEN.md` im Projektordner
> bildet nun neben Charttechnik auch Preisbildung, Marktteilnehmer, Ausführung,
> Instrument-/Derivatmechanik, Makro-/Cross-Asset-Kanäle, Risikomathematik,
> Datenqualität, Backtestfehler und ein erweitertes Indikatorinventar ab. Details
> und Quellenstatus stehen in [[traidingBrain — Regel-Aufnahme]].

Handels-Analysesystem für Krypto-Perpetuals (heute Binance USD-M). Ein Sprachmodell ist
ausschliesslich **Deutungs- und Entscheidungsschicht** — nicht Datenquelle, nicht
Ausführer. Die Daten kommen deterministisch aus Code, und **kein Trade geht raus
ohne dass Severin ihn im Dashboard bestätigt hat.**

## Die eine Regel, die alles prägt

Das System bereitet einen vollständigen Trade vor — Entry, Stop, Take Profit,
Hebel, Positionsgrösse, Risiko in Franken, Liquidationspreis — und legt ihn als
Vorschlag ins Dashboard. Severin kann Hebel und Risiko **senken** (nie erhöhen) und
muss dann *halten*, nicht klicken. Erst danach geht eine Order an die Börse.

Durchgesetzt als Architektur, nicht als UI: `execution/` akzeptiert nur einen
server-seitig ausgestellten, einmalig gültigen Token. Ohne ihn existiert kein
Codepfad zur Börse.

## Entscheidungen, die getroffen wurden

- **Bybit statt Binance.** `testnet.binancefuture.com` war nicht erreichbar (auch
  nicht von Claude aus geprüft), `testnet.bybit.com` schon. Alles liegt hinter
  einem ccxt-Protokoll, Binance bleibt ein Config-Schalter.
- **Kursdaten von Mainnet, Handel auf Testnet.** Getrennte Entscheidungen: eine
  Testnet-Kurshistorie ist zu dünn zum Backtesten, und der öffentliche
  Kline-Endpunkt braucht keinen Schlüssel.
- **Das Modell sieht keine Preise, kein Datum, keinen Symbolnamen.** Alles in
  ATR-Einheiten, Kurslevel nur über undurchsichtige IDs. Sonst würde es aus
  „BTC, 16'540 $, extreme Vola" den November 2022 erkennen und teilweise aus dem
  Gedächtnis antworten statt aus der Analyse.
- **Die Confidence rechnet Python, nicht das Modell.** Das Modell bewertet fünf
  Faktoren von −1 bis +1 mit Begründung; die Gewichtung passiert im Code.
- **Hebel wird abgeleitet, nie gewählt.** Immer der höchste, bei dem die
  Liquidation noch mindestens 2.5 Stop-Abstände hinter dem Stop liegt.

## Der wichtigste Befund bisher

Die ersten Backtests verloren deutlich — und die Ursache war nicht die Strategie.
Positionsgrösse ist Risiko geteilt durch Stop-Abstand, also kauft ein enger Stop
eine grosse Position, und Gebühren skalieren mit der Position, nicht mit dem
Risiko. Beim 10. Perzentil der gemessenen Stops (0.18 % vom Preis) kostet ein
Rundlauf **42 % des riskierten Betrags**.

Eine einzige Regel — Transaktionskosten dürfen höchstens 15 % des Risikobudgets
fressen — drehte beides:

| | vorher | nachher |
|---|---|---|
| Baseline | −76.9 %, Drawdown 80.5 % | **+19.3 %**, Drawdown 14.9 % |
| Regel-Brain | −45.8 %, Drawdown 49.6 % | **+24.1 %**, Drawdown 5.9 % |

## Und die ehrliche Einordnung dazu

**Die +19.3 % waren ein Ein-Symbol-Artefakt.** Über drei Symbole gepoolt
(BTC, ETH, SOL, 698 Trades) liegt die Baseline schon *in-sample* bei
**−0.012 R [−0.131, +0.112]** — also bei null. BTC war der Ausreisser:

| | BTC | ETH | SOL | gepoolt |
|---|---|---|---|---|
| Baseline in-sample | +0.116 | −0.003 | −0.089 | **−0.012** |
| Baseline out-of-sample | +0.008 | −0.028 | −0.094 | **−0.036** |
| Zufall out-of-sample | +0.009 | −0.216 | −0.211 | **−0.153** |
| Regel-Brain out-of-sample | +0.744 | +0.605 | −0.378 | **+0.324** |

**Kein Ansatz hat einen belegten Vorteil.** Jedes gepoolte Konfidenzintervall
schliesst die Null ein. Das Regel-Brain sieht am besten aus (+0.324 R), aber mit
97 Trades, einem Intervall von −0.051 bis +0.674 und einem Symbol (SOL) klar im
Minus — das ist keine Evidenz, das ist Streuung.

Was die Kostenregel tatsächlich bewirkt hat: die Zufallsstrategie lag in-sample
bei −0.179 R und schloss die Null **aus** — ein systematisches Ausbluten. Das ist
weg. **Die Regel hat den Verlust beseitigt, keinen Gewinn erzeugt.**

Der Unterschied ist die ganze Sache. Ein System, das nicht mehr blutet, ist die
Voraussetzung dafür, dass ein Vorteil überhaupt sichtbar werden könnte — es ist
aber selbst noch keiner.

### Vier Symbole, und was der Walk-Forward dazu sagt

Mit XRP dazu (172 Trades out-of-sample) sah das Regel-Brain zum ersten Mal echt
aus: **+0.355 R [+0.064, +0.749]**, Null ausgeschlossen, alle vier Symbole positiv.

Der Walk-Forward über vier Zeitabschnitte zeigt aber, wo das herkommt — fast alles
steckt im **letzten** Abschnitt (März–Sept 2026):

| Symbol | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Urteil |
|---|---|---|---|---|---|
| BTC | −0.300 | +0.281 | +0.680 | +1.258 | nur 31 Trades — nichts etabliert |
| ETH | +0.125 | +0.217 | +0.500 | +1.164 | **in allen vier positiv** |
| SOL | −0.026 | −0.110 | −0.223 | +1.033 | positiv in 1 von 4 |
| XRP | −0.360 | +0.140 | +0.234 | −0.140 | positiv in 2 von 4 |

Drei von vier Symbolen haben ihren besten Abschnitt gleichzeitig. Da die vier Coins
korrelieren, ist das genau das Bild, das entsteht, wenn **die Marktphase** der
Strategie passte — nicht die Strategie selbst. SOL ist in drei von vier
Abschnitten negativ.

**Stand: nicht etabliert.** Ein Symbol ist konsistent, zwei sind es nicht, eines
hat zu wenige Trades. Der nächste sinnvolle Schritt sind mehr *Perioden*, nicht
mehr korrelierte Symbole in derselben Periode.

## Was steht

Zehn Stufen, jede mit eigenem Abnahmekriterium, alle committet:

0. Gerüst und Verträge (Domain-Typen, Protocols, Import-Grenzen per Test erzwungen)
1. Datenschicht — Bybit-Backfill, Parquet + DuckDB, Validierung
2. Analyse — Indikatoren, Struktur mit Bestätigungsindex, Liquidität, Regime, MTF-Snapshot
3. Simulator — Intrabar-Auflösung über M1, Gaps, Funding, Liquidation; plus zwei Messlatten
4. Brain-Layer — Prompt, Guard, Confidence-Arithmetik, Decision-Cache, Gate
5. Out-of-Sample-Messung — Split, Walk-Forward, Block-Bootstrap
6. History-Engine — kNN mit Purging und Embargo, walk-forward aufgebaut
7. Vorschläge, Limits, Kill-Switch, Dashboard
8. Ausführung — Write-Ahead-Intent, clientOrderId-Idempotenz, SL-Watchdog, Reconcile
9. Post-Trade-Analyse — Vorschläge nur in eine Review-Queue, nie automatisch angewendet

Dazu die Live-Schleife (`scripts/run_live.py`), die exakt dieselben Objekte fährt
wie der Backtest — sonst wäre der Backtest kein Beleg für das, was live passiert.

**453 Tests**, ruff sauber, `mypy --strict` sauber.

## Dashboard

Dunkles Terminal, eine Entscheidung pro Bildschirm. Signatur-Element ist eine
**Risiko-Leiter**: eine massstäbliche Preisachse mit gebrochener Skala — Trade-Zone
massstabsgetreu, sichtbarer Bruch, Liquidation darunter mit echtem Abstand. Die
erste Version war durchgehend linear und unlesbar, weil der Trade 1 % des Preises
einnimmt und die Liquidation 10 % darunter liegt.

Bestätigen ist ein **Halten** (1.2 s), kein Klick. Drei Fehler fand erst die echte
Benutzung: der 4-Sekunden-Poll zerstörte den Button mitten in der Geste, der
Ausgang verschwand mit dem Vorschlag aus der Liste, und die Stepper waren mit 34 px
zu klein für einen Daumen.

## Offene Punkte

- **Kostenschätzung liegt vor** (`scripts/estimate_cost.py`): BTCUSDT allein
  ergibt 4'542 Modell-Aufrufe, alle vier Symbole zusammen 17'772 — auf Opus 5.5
  mit Caching **448 $** gegen ein Budget von 25 $ in `settings.yaml`. Opus 5.5 mit Caching **114 $**, mit Batch-API 57 $;
  Sonnet 5.5 mit Batch 29 $; Haiku 4.5 mit Batch 15 $. Ohne funktionierenden
  Prompt-Cache wären es 447 $ — deshalb ist der stabile Prefix kein Detail.
  Vier Symbole vervierfachen das.
- **ANTHROPIC_API_KEY fehlt** — ohne ihn läuft alles mit einem regelbasierten
  Ersatz-Brain. Das ist zugleich die schärfste Messlatte: gleiches Gate, gleiche
  Faktoren, gleiches Sizing, nur das Urteil durch Arithmetik ersetzt.
- **Bybit-Testnet-Schlüssel fehlen** — nötig für Stufe 8 in echt.
- **Der Weg zur Börse ist noch nicht verbunden.** `executor.send()` wird an genau
  einer Stelle aufgerufen: in `api/app.py`. Den Executor baut aber nur
  `scripts/run_live.py`, und der Prozess hat keine HTTP-Oberfläche; der
  Dashboard-Prozess hat die Oberfläche und keinen Executor. `run_live.py --execute`
  armt also etwas, das nur für Reconcile, Symbol-Regeln, offene Positionen und den
  Stop-Watchdog benutzt wird — eine Bestätigung im Dashboard erreicht die Börse
  nicht. Im Arbeitsverzeichnis liegt dazu ein **unfertiger, nicht committeter**
  Ansatz: `run_dashboard.py --execute` samt `_arm()` (Executor + öffentliche
  Preisquelle + Instrument-Regeln) und in `api/app.py` die Regel, dass ein
  bewaffneter Executor ohne lesbaren Preis keinen Token ausgibt. `_arm()` wird
  nirgends aufgerufen, die Statuszeile behauptet weiter „no exchange is connected",
  und ruff scheitert an der Importreihenfolge.
- **`src/traidingbrain/brain/subscription.py` ist untracked.** Fragt Claude über
  die CLI des bestehenden Abos statt über einen API-Key — erbt Prompt, Schema,
  Guard, Scoring und Cache von `AnthropicBrain`, verzichtet auf Structured
  Outputs, Batch-API und Prompt-Cache-Kontrolle. Kein Skript verdrahtet es, keine
  Tests decken es ab. Entscheiden: fertigstellen und committen oder verwerfen.
- **Backfill vollständig** für alle vier Symbole: 2023-01-01 bis 2026-09-29, W1 bis M1 (je ~1.97 Mio M1-Bars).
- **Die drei Symbole korrelieren.** 500 Trades über BTC/ETH/SOL sind weniger
  wert als 500 unabhängige. Deshalb ist der Block-Bootstrap das Intervall,
  das zählt — und der Bericht sagt das von sich aus.
- **History-Engine liefert noch nichts:** 326 Fälle aus einem Symbol reichen nicht
  für 30 unabhängige Nachbarn (gebraucht: ~750). Vier Symbole gepoolt kommen hin.
- Die Kostenschwelle von 15 % wurde an genau den Daten gewählt, an denen sie
  gemessen wurde. Prinzipiell richtig, aber die Zahl ist in-sample.

## Sicherheitsnetze (alle per Test belegt)

- Kein Auto-Trading; ohne Token kein Codepfad zur Börse
- 100 gleichzeitige Bestätigungen → genau eine Order (Compare-and-Swap, nicht der Token)
- `clientOrderId` aus der Proposal-ID abgeleitet → ein Retry kann keine zweite Position öffnen
- Live-Handel braucht **zwei** unabhängige Signale, nie eine einzelne Config-Zeile
- Stop reist mit der Entry-Order; Watchdog schliesst eine ungeschützte Position
- Kill-Switch ist eine Datei, von aussen setzbar, nur von Hand löschbar — und
  seit 2026-10-05 auch im Papertrader geprüft (vorher: nur auf dem
  Vorschlagspfad, also wirkungslos für den Prozess, der Positionen eröffnet)
- Tagesverlust-, Wochenverlust- und Verlustserien-Sperre, pro Konto gemessen
  gegen die echten Vorwärts-Trades aus dem Journal (seit 2026-10-05; vorher
  gegen eine leere Liste, also nie auslösbar)

## Verlauf

- **2026-09-30, von: ChatGPT, Commit: 84ad7c3 (Wissensbasis uncommitted)** —
  Die 13 Videos der Playlist „Trading by Loma" einzeln erfasst und die verfügbaren
  Transkripte ausgewertet. `DAYTRADING_MASTER_GUIDE.md` enthält 35 Kapitel und
  trennt die Creator-Modelle, Widersprüche und nicht belegten Felder; `video_sources.md`
  bildet Transcript-Status und Kapitelherkunft ab. 329 Zusatzvideo-Kandidaten sind
  entdeckt, aber wegen YouTube-Caption-Rate-Limit bewusst noch keine Quellen.

- **2026-09-29, Abend** — Durchsicht des ganzen Programms. Alles läuft: 453 Tests
  grün, `mypy --strict` sauber, Daten für vier Symbole vollständig. Zwei Befunde,
  die den nächsten Schritt ändern: es gibt heute **keinen Prozess, der Dashboard
  und Executor gleichzeitig hält**, also auch mit Schlüsseln keinen Weg zur Börse
  (die halbfertige Verdrahtung liegt uncommitted im Arbeitsverzeichnis), und der
  echte Claude-Backtest über vier Symbole kostet 448 $ gegen ein 25-$-Budget.
- **2026-09-29** — Projekt von null gebaut. Zehn Stufen, 442 Tests. Wichtigster
  Befund: die Kostenregel beseitigt ein systematisches Ausbleiben von Gewinn,
  erzeugt aber keinen Vorteil. Über drei Symbole gepoolt hat **keine** der drei
  Strategien einen belegbaren Edge — jedes Intervall schliesst die Null ein.

## Zugang ohne API-Key (2026-09-29)

Der Brain laeuft jetzt wahlweise ueber drei Wege, umschaltbar mit `--brain`:

| Wert | Urteil von | Kosten | Voraussetzung |
|---|---|---|---|
| `fake` | Arithmetik, kein Modell | nichts | nichts |
| `subscription` | Claude ueber die CLI | Abo | eingeloggter Claude-Account |
| `api` | Claude ueber die API | pro Token | `ANTHROPIC_API_KEY` |

`SubscriptionBrain` erbt von `AnthropicBrain` und tauscht nur den Transport —
Prompt, Schema, Guard, Scoring und Cache sind dieselben, damit ein Wechsel ein
fairer Vergleich bleibt und nicht ein anderes System.

Was das Abo nicht kann: keine serverseitige Schema-Erzwingung (lokal parsen, ein
Retry mit dem Validierungsfehler, dann NO TRADE), keine Batch-API, keine
Cache-Messung. Darum ist es richtig fuer Live-Vorschlaege (wenige Aufrufe pro
Stunde) und falsch fuer einen Backtest mit tausenden Aufrufen.

### Zwei Fehler, die dabei sichtbar wurden

- Das Dashboard hatte nie einen Executor. Beim Nachruesten zeigte sich, dass die
  Drift-Pruefung einen **unlesbaren** Preis wie *keine Abweichung* behandelte.
  Harmlos, solange nichts senden kann; ein Loch, sobald es das kann. Unbekannt
  lehnt jetzt ab — aber nur, wenn etwas handeln koennte.
- `--execute` war verdrahtet, dokumentiert und wurde nie aufgerufen. 468 Tests
  blieben gruen, weil keiner das Skript ausfuehrt. Drei neue Tests lesen `main()`
  als AST und pruefen die Verdrahtung selbst.

Stand: 471 Tests, ruff und `mypy --strict` sauber. Blockiert nur noch durch die
abgelaufene OAuth-Sitzung und fehlende Bybit-Testnet-Schluessel.

## Nachtarbeit 2026-09-30

### Der "Totalausfall" bei Schritt 5 — drei getrennte Ursachen

1. **Bybit-Schluessel ungueltig.** Auf Testnet, Mainnet *und* Demo mit `10003` abgelehnt.
   Format sauber (18/36 Zeichen). Das Anlegen ging nie durch — die `10024`-Meldung ist
   eine Kontosperre fuer Derivate, nichts an .env aendert daran etwas.
2. **Der Absturz danach war ein Fehler von mir.** Jeder Boersenfehler endete in 30 Zeilen
   ccxt-Traceback. Neu: `execution/diagnose.py` uebersetzt jeden Code in die konkrete
   naechste Handlung — 10003 und 10005 sehen gleich fatal aus und haben nichts gemeinsam.
3. **Leeres Dashboard.** `--demo` fragte nur den neuesten Balken; Ablehnen ist die normale
   Antwort, also blieb der Bildschirm meistens leer. Sucht jetzt rueckwaerts und nennt sonst
   die drei haeufigsten Ablehngruende mit Anzahl.

### Chart im Dashboard

Selbst geschrieben (Canvas, keine Bibliothek, kein CDN). Kerzen, benannte Levels,
Entry/SL/TP/Liquidation, **Risiko rot und Chance gruen als Flaechen** — das Verhaeltnis
zweier Zahlen muss man rechnen, das zweier Flaechen sieht man. Strukturbrueche und Sweeps
als senkrechte Marker: aus `bos: true` wird eine Stelle im Chart. Zeitebenen umschaltbar
(W1/D1/H4/H1/M15), Payloads pro Ebene gecached, damit Vergleichen kein Warten ist.

Der Chart endet **immer am Entscheidungsbalken**. Ein Balken weiter waere die Antwort.

Darunter die Faktortabelle: pro Faktor die Lesart, die Sicherheit, das Gewicht und die
Punkte — und die Summe stimmt mit der angezeigten Zahl ueberein. Dabei fiel ein echter
Fehler auf: die Punkte ergaben 78.8, angezeigt waren 75, weil der History-Deckel griff.
Der Deckel ist jetzt Teil der Rechnung statt einer Fussnote.

### Neue Datenquellen

| Quelle | Umfang | Warum |
|---|---|---|
| Open Interest | 4 Symbole x 32'830 Stunden ab 2023-01 | Unterscheidet echte Nachfrage von Short-Squeeze |
| Long/Short-Quote | dito | Ueberfuellte Buecher |
| FOMC-Kalender | 57 Sitzungen 2021-2027, von federalreserve.gov | Geplante Volatilitaet |
| Regel-Termine | NFP, Options-Verfall, monatlich + quartalsweise | dito |

Jedes Kalender-Ereignis traegt, **wann sein Termin oeffentlich wurde**. Ohne das saehe jeder
2023-Balken den 2026-Kalender. Alles in New Yorker Zeit, nicht in fester UTC-Stunde: 14:00 ET
ist im Juli 18:00 UTC und im Januar 19:00.

Das News-Gewicht bleibt bei 0. Die Daten machen ein Anheben *vertretbar*; das Anheben ist
eine Entscheidung, die gemessen wird, kein Nebeneffekt.

### Gemessen, nicht behauptet

Positionierung in den Liquiditaets-Faktor gefaltet (kein sechster Faktor — die Spezifikation
hat fuenf Gewichte, die sich zu eins addieren):

| | Trades | Erwartung | 95 %-Intervall |
|---|---|---|---|
| vorher, out-of-sample | 172 | +0.355 R | [+0.064, +0.749] |
| nachher | 144 | +0.417 R | [+0.136, +0.791] |

Die Intervalle ueberlappen fast vollstaendig. **Kein nachweisbarer Unterschied** — aber 26 %
weniger Trades bei leicht besserem Ergebnis, und geschadet hat es nicht.

### History-Engine

War nie in `evaluate.py` verdrahtet — kein einziger Fall, jeder Lookup "nicht genug", also
Confidence-Deckel und Risiko-Deckel dauerhaft. Jetzt ein gemeinsamer Index ueber alle vier
Symbole (ein Symbol liefert ~330 Faelle, gebraucht werden ~750). Symbole nacheinander zu
rechnen ist trotz geteiltem Index sicher: ein Fall ist erst zulaessig, wenn sein Ergebnis vor
dem Embargo-Fenster aufgeloest war.

### Drei stille Fehler, alle derselben Art

Jeder meldete Erfolg und tat nichts. Das ist die gefaehrlichste Fehlerklasse in diesem
Projekt, weil das Symptom jeweils wie ein echtes Ergebnis aussah.

1. **History-Schwelle unerreichbar.** `k_neighbours: 25` gegen `min_samples_for_stats: 30`.
   Ein Lookup liefert hoechstens k Nachbarn, Deduplizierung reduziert nur — die Bedingung
   war arithmetisch unerfuellbar. 71'078 Lookups, 0 mit "genug". Symptom: History-Faktor
   stumm, Confidence-Deckel nie geloest — ununterscheidbar von echtem Datenmangel. Der
   Config-Kommentar erklaerte sorgfaeltig das falsche Problem. k ist jetzt 120, und
   `settings.py` lehnt die Kombination ab.

2. **Backfill kann nicht rueckwaerts.** Resume nahm `max(gewuenschter_start, neuester)` —
   nur vorwaerts. Die Anfrage "zurueck bis 2021" holte 0 Zeilen und meldete "Done". Jetzt
   erkennt er, auf welcher Seite das Loch ist. Dazu: der Bericht zeigte den zuletzt
   geschriebenen Block als Gesamtstand ("116 bars" bei 259 gespeicherten).

3. **Die ganze Datenschicht war nie in Git.** `.gitignore` hatte `data/` ohne fuehrenden
   Schraegstrich — das trifft jeden Ordner dieses Namens in jeder Tiefe, also auch
   `src/traidingbrain/data/`. Neun Module, 1'661 Zeilen: Boersenclient, Store, Backfill,
   Validierung, Funding, Derivate, Kalender. Seit dem ersten Commit untracked. `git status`
   war sauber, weil die Dateien ignoriert waren. Ein frischer Klon waere beim ersten Import
   gescheitert. Aufgefallen nur, weil `git show HEAD:` auf eine gerade bearbeitete Datei
   sagte, der Pfad existiere in HEAD nicht.

   Geprueft nach dem Fix: frischer Klon importiert alle Module und besteht die volle Suite.

### Fenster verdoppelt

Der Backtest lief auf 975 nutzbaren Tagen, alle in derselben Marktphase — genau der Grund,
warum das Urteil "nicht etabliert" lautete. Bybit liefert Kerzen ab 2021; der Store reicht
jetzt fuer BTC/ETH/SOL bis Oktober 2021 zurueck (XRP ab 2023, spaetere Notierung). Das sind
~2,63 Mio. M1-Bars pro Symbol statt 1,97 Mio., 223 MB, und es bringt **den Baerenmarkt 2022**
ins Fenster — eine wirklich andere Marktphase statt weiterer korrelierter Symbole in
derselben.

Open Interest und Long/Short-Quote wurden mitgezogen: 43'799 Stunden pro Symbol ab 2021-10.

### Vierter stiller Fehler, gleich danach gefunden

Der Backtest lief ohne Pruefung, ob die Minutendaten das Signalfenster ueberhaupt abdecken.
Die Minutenserie entscheidet, ob innerhalb einer Stunde zuerst der Stop oder das Ziel getroffen
wurde — fehlt sie, fuellt nichts, jeder Einstieg laeuft ab, und der Bericht sagt "no trades".
Das ist von "die Strategie hat nichts gefunden" nicht zu unterscheiden.

Erreichbar durch ganz normale Benutzung: genau das entsteht, wenn man die Kerzenhistorie
verlaengert und die Minutenhistorie nicht. Der Lauf bricht jetzt ab und nennt den Befehl.

Der Toleranztest dazu war im ersten Anlauf falsch — er schnitt 30 Zeilen ab in der Annahme,
das seien 30 Minuten. Die "M1"-Fixture hat aber 15-Minuten-Schritte, also 7,5 Stunden, und der
Test behauptete damit, eine echte Luecke sei in Ordnung.

## Ergebnis ueber das verdoppelte Fenster (1430 Tage, 2022-10 bis 2026-09)

### History-Index arbeitet endlich

2'909 aufgeloeste Faelle, 448'382 Lookups, **149'269 davon mit genug vergleichbaren Faellen**
(33 %). Vor dem k_neighbours-Fix: 0 von 71'078. Der Confidence-Deckel kann sich damit heben.

### Split

| | Trades | Erwartung | 95 %-Intervall |
|---|---|---|---|
| in-sample 2022-10..2024-10 | 231 | **-0.028 R** | [-0.228, +0.165] |
| out-of-sample 2024-10..2026-09 | 230 | +0.298 R | [+0.075, +0.570] |

In-sample negativ, out-of-sample positiv — die *umgekehrte* Richtung von Ueberanpassung.
Das heisst nicht "robust", sondern: der juengere Zeitraum war guenstig.

Pro Symbol in-sample: BTC +0.237, ETH +0.197, SOL -0.010, **XRP -0.364**.

### Zufallskontrolle

555 bzw. 562 Trades, E = -0.042 und -0.039, beide Intervalle ueberspannen die Null.
Zufaelliges Einsteigen ist **flach** statt blutend (-0.179 R vor der Kostenregel). Das ist der
eine Effekt, der ueber das ganze neue Fenster haelt.

### Walk-forward, 6 Perioden — Strategie gegen Zufall

| Symbol | fake-brain | random |
|---|---|---|
| BTC | 47 Trades gesamt, zu duenn | 2 von 6 |
| ETH | **5 von 6** | 2 von 6 |
| SOL | **5 von 6** | 1 von 6 |
| XRP | 1 von 6 | 3 von 6 |

Das Skript nennt alles "nicht konsistent", weil es 6 von 6 verlangt. Der *Kontrast* zu Zufall
ist aber das Informative, und den berechnet es nicht: ETH und SOL schlagen die Kontrolle
deutlich, XRP ist schlechter als Zufall.

**Urteil: weiterhin nicht etabliert.** Aber zum ersten Mal sieht etwas nach Signal aus statt
nach guenstiger Marktphase. Bei 6 Folds ist 5-von-6 unter Zufall p ~ 0.11 pro Symbol, und die
Symbole korrelieren — zwei davon sind also kein unabhaengiger Doppelbeleg.

**Naechster ehrlicher Schritt:** XRP wegzulassen waere Symbolauswahl *nach* Sicht der
Ergebnisse und damit wieder in-sample. Die Hypothese "XRP passt nicht zu dieser Strategie"
braucht neue Daten, kein neues Filtern derselben.

## Stack-Abgleich 2026-09-30

Severins Zielarchitektur gegen den Ist-Stand:

| Baustein | Stand |
|---|---|
| Claude als Analyse-Schicht | fertig, laeuft ueber das Abo |
| Preise, Open Interest, Crowd-Quote | fertig, **venue-neutral** |
| Wirtschaftskalender (FOMC, NFP, Verfall) | fertig, 273 Termine |
| Python-Backend + Chart-Frontend | fertig |
| Order-Ausfuehrung | fertig und getestet, wartet auf ein Konto |
| Postgres | **fehlt** |
| Raspberry-Pi-Sammler | **fehlt** |
| Obsidian-Export | **fehlt** |
| News / Social | **fehlt** |

### Venue ist jetzt wirklich eine Config-Entscheidung

`exchange.name` stand seit dem ersten Commit in der settings.yaml, daneben ein Kommentar,
ein Venue-Wechsel sei Konfiguration statt Umbau. **Gelesen wurde es nie** — `ccxt.bybit`
stand direkt im Datenclient und nochmal im Executor. `data/venue.py` ist jetzt die einzige
Stelle, die eine Boerse kennt, und kennt genau die drei Dinge, die ccxt nicht vereinheitlicht:
Symbol-Schreibweise (`BTC/USDT:USDT` gegen `BTC/USDT`), wie man in den Uebungsmodus kommt,
und ob die Boerse die Rechte eines API-Keys ueberhaupt meldet.

Default steht jetzt auf **binance**. Die urspruengliche Notiz sagte,
testnet.binancefuture.com sei nicht erreichbar — das stimmt nicht mehr.

### Fund: ccxt hat Binances Futures-Sandbox abgeschaltet

`set_sandbox_mode` wirft auf binanceusdm inzwischen einen Deprecation-Hinweis statt den Host
zu wechseln. `enable_demo_trading` funktioniert und leitet auf demo-dapi.binance.com.
Bybit nutzt weiter sandbox_mode.

**Das waere erst beim ersten Konto-Zugriff aufgefallen** — oeffentliche Daten antworten in
beiden Einstellungen. `testnet: true` haette also durch jeden Backtest hindurch richtig
ausgesehen.

### Postgres bewusst nicht gebaut

Auf diesem Rechner gibt es kein Docker, kein psql, kein psycopg. Einen ungetesteten
Postgres-Adapter zu schreiben waere genau das Muster, das diese Woche vier Mal aufgetreten
ist: Code, der richtig aussieht und auf dem Zielsystem scheitert. Kommt, sobald ein
Postgres da ist — lokal oder auf dem VPS.

## Marktansicht und Regel-Andockpunkte (2026-09-30, zweiter Block)

### Der Chart ist jetzt durchgehend begehbar

Bisher gab es einen Chart nur, wenn ein Vorschlag existierte. Ein Bildschirm, der nur dann
etwas zeigt, wenn das System zufaellig ein Setup findet, ist einer, an dem niemand den Markt
lernt — und die meisten Stunden haben kein Setup.

`/api/market/{symbol}/chart` liefert dieselben Zeichnungen ohne Trade: Kerzen, Levels,
Strukturbrueche, Sweeps, und darunter **eine Zeile pro Zeitebene** mit Regime, Trend,
Volatilitaet, Swing-Folge und Ereignissen. Dazu Positionierung, Stimmung, Sitzung und der
naechste Termin.

Gezeichnet vom **gleichen** Renderer wie der Vorschlags-Chart. Zwei Zeichnungen desselben
Marktes wuerden irgendwann auseinanderlaufen, und zwar unsichtbar: beide saehen plausibel aus,
und der Marktbildschirm wuerde leise eine andere Lesart lehren als die, auf der die Trades
beruhen.

Zwischengespeichert, weil eine Mehr-Zeitebenen-Analyse **23 Sekunden** braucht. Schluessel ist
der neueste gespeicherte Balken, nicht ein Zeitgeber: ein Zeitgeber baut entweder neu, was noch
aktuell ist, oder liefert einen Chart, der leise hinterherhinkt. Gemessen: 23,3s kalt, 0,03s warm.

### Andockpunkte fuer die kommenden Regeln

Statt eine Regel-Sprache zu erfinden, habe ich gebaut, was Regeln brauchen werden:

**Handelssitzungen.** In der jeweiligen Ortszeit definiert und umgerechnet — London ist UTC+0
im Winter und UTC+1 im Sommer. Eine auf eine feste UTC-Stunde genagelte Sitzung ist ein halbes
Jahr lang eine Stunde falsch, und zwar genau um die Eroeffnung herum. Geprueft: 07:30 UTC ist
im Juli London, im Januar nicht.

Der Sitzungsbereich ist ein *laufendes* Hoch und Tief, nie das spaetere der ganzen Sitzung.
Das waere der gewoehnlichste Lookahead hier und saehe wie ein funktionierendes Merkmal aus.

**Nachrichtensperre.** `news_blackout_minutes` — symmetrisch, weil beide Haelften dasselbe
Problem sind: vorher duennt das Buch aus, nachher wird die erste Bewegung oft zurueckgenommen.
Nur hohe Wichtigkeit zaehlt.

Beide stehen **standardmaessig auf aus**. Eine Einschraenkung, die niemand gemessen hat,
verkleinert nur die Stichprobe — und dieselbe Kante auf weniger Trades sieht besser aus,
ohne es zu sein.

### Zwei eigene Testfehler

22:30 UTC ist Sydney, keine ruhige Stunde (die einzige ist 21:00-22:00 UTC). Und ein
Testfenster von 09:00 bis 14:00 ueberspannt einen Sitzungswechsel, also startet der Bereich
mittendrin neu. Beide Male hatte der Code recht.

### Stand

670 Tests, 52 Commits, Schema 4, Prompt v4. Dashboard auf **Port 8800**, Live-Schleife laeuft.

## Offene Frage an Severin

Die Regel-Aufnahme steht: [[traidingBrain — Regel-Aufnahme]] — jede Frage, die
beantwortet sein muss, mit dem heutigen Wert und dem Ort in der Konfiguration.
Was dort mit „muss gebaut werden" markiert ist, existiert noch nicht.

## Severins Regelwerk ist eingebaut (2026-09-30, dritter Block)

Severin hat per ChatGPT aus 13 YouTube-Videos einen `DAYTRADING_MASTER_GUIDE.md`
erzeugt (1287 Zeilen, jede Aussage mit Videoquelle) plus `TRADING_ANALYSE_GRUNDLAGEN.md`
(Definitionsebene). Ansage: meine Regeln ignorieren, seine benutzen.

### Was ersetzt wurde und was nicht

Strategie, Muster, Entries, Stops, Ziele: **vollstaendig** aus dem Guide.

Geldregeln: **nicht**, und zwar weil der Guide es selbst verbietet. Kapitel 23
sagt woertlich, die Playlist gebe keine Positionsgroessenformel, keinen
Prozentsatz, kein Tagesverlustlimit, und "jede konkrete Sizing-Regel waere eine
nicht erlaubte Ergaenzung". Kapitel 24: keine Sessions. Severins 100-CHF-Beispiel
aus seiner Nachricht wartet auf die Entscheidung Prozent oder Festbetrag.

### Gebaut

- `analysis/candles.py` - 18 Muster aus V03 plus V08s Breakout-Bestaetigung
- `analysis/zones.py` - Supply/Demand (V09), Order Blocks (V11), Inducement (V12)
- `analysis/fvg_quality.py` - V05-Filter und V13-Sechs-Faktoren, getrennt
- `strategy/setups.py` - Setups A, C, F, G lauffaehig; B, D, E deklariert unvollstaendig
- `strategies/guide.py` - eine Backtest-Strategie pro Setup plus Pool

Nicht gebaut, absichtlich: Breaker Blocks und IFVG. Die Guide-Kapitel 16 und 18
sagen, dass kein Video sie definiert.

### Das Ergebnis, ehrlich

BTCUSDT, vier Jahre. **Jedes Konfidenzintervall ueberlappt die Null** - die
Guide-Regeln, meine alte Baseline und der Zufall gleichermassen. Nichts ist
belegt, auch nicht das Gegenteil.

| | Trades | Erwartung (R) |
|---|---|---|
| Zufall | 175 | +0,171 [-0,038, +0,395] |
| guide-A | 211 | +0,034 [-0,138, +0,200] |
| guide-C | 78 | +0,054 [-0,343, +0,473] |
| guide-all | 291 | +0,051 [-0,113, +0,222] |

### Der eigentliche Befund: die Kostenschwelle

Der Trichter zeigt, dass **meine** Regeln mehr wegfiltern als Severins:
Setup C verliert 57 % seiner Signale an die Kostenregel, Setup G 65 % ans
Mindest-CRV. Beides steht nicht im Guide.

`min_economic_stop_fraction` ist die Kostenregel rueckwaerts geloest und
erklaert alles: Positionsgroesse ist Risiko durch Stop-Abstand, also kauft ein
Stop `d` ein Volumen von `Risiko/d`, die Runde kostet `Volumen * c`, also frisst
sie `c/d` des Risikos, und der Deckel `f` ergibt `d >= c/f`. Die Strategie faellt
komplett heraus. Bei diesen Gebuehren und 15 % Deckel: **0,70 %**.

Jede Regel mit engerem Stop wird abgelehnt, bevor jemand fragt, ob die Idee
stimmte. Die Guide-Setups setzen Stops an Struktur - Zonenkante, Gap-Kerze - und
auf Stunden-Krypto ist die oft duenner als 0,7 %. Setup G median: 0,68 %.
Das ist eine Tatsache ueber Instrument und Gebuehrentabelle, nicht ueber V13.

### Acht Bugs derselben Familie

Einzeln korrekte Bedingungen, die zusammen unmoeglich sind: null Signale, keine
Fehlermeldung. Beispiele: der Breakout prueft "Preis ist ueber dem Level" statt
"hat gerade gebrochen" (6307 statt 816 Signale); Setup F verlangt eine
unberuehrte Zone UND dass dieser Bar sie erstmals beruehrt - derselbe Moment;
Setup G nimmt den Stop von der dritten Kerze, deren Low die Gap-Oberkante ist
(Stop 0,016 % vom Entry, CRV 55).

Dazu zwei Performance-Fehler: Kerzenerkennung baute ihre Arrays bei jedem
Zugriff neu (37 s statt 0,94 s), Zonen beantworteten "war der Preis schon zurueck"
durch Scannen pro Aufruf (quadratisch).

### Stand

797 Tests, 64 Commits, ruff und mypy --strict sauber. Dashboard auf Port 8800
zeigt feuernde Setups mit komplettem Trade und markiert die, deren Stop zu eng
fuer die Gebuehren ist.

## Der Raspberry Pi ist jetzt der Sammler (2026-09-30, Abend)

Zwei Luecken aus dem Stack-Abgleich sind geschlossen, und es war dieselbe Luecke:
**Postgres** und **Raspberry-Pi-Sammler** brauchten beide eine Maschine, die laeuft
wenn der Laptop aus ist.

### Was die Hardware entschieden hat

Es ist ein **Raspberry Pi 1 Model B+** — armv6, ein Kern mit 700 MHz, 426 MB
nutzbares RAM, Raspbian 13. Das ist kein Detail, das ist die Architektur:

- **`pyarrow` gibt es fuer armv6 nicht.** piwheels liefert ueberraschend viel
  (pandas, numpy, duckdb, sogar pydantic-core in Rust), aber nicht pyarrow. Die
  vier Parquet-Speicher sind auf dem Pi damit nicht importierbar — was passt,
  denn er schreibt nach Postgres und das Archiv bleibt auf dem Laptop.
- **Der Sammler ist ein Timer, kein Dienst.** Ein Python-Prozess mit ccxt haelt
  74 MB (gemessen, nicht geschaetzt). Dauerhaft waere das ein Fuenftel der
  Maschine fuer die 99 % der Zeit, in der er nichts tut.
- **`pip install` ohne `--only-binary=:all:` faengt an zu kompilieren.** Es zog
  eine Cython-Bauumgebung fuer ccxts Async-Abhaengigkeiten hoch; auf diesem Kern
  waeren das Stunden gewesen. Mit der Einschraenkung scheitert es sofort und
  ehrlich, statt langsam und unbemerkt.

### Der Umbau, den das erzwungen hat

`frames.py` importiert pandas auf Modulebene. `exchange.py` holte von dort
`is_closed` — also eine Addition und einen Vergleich, fuer hundert Megabyte.
Die Arithmetik liegt jetzt in **`data/grid.py`** (pandas-frei), `frames.py`
re-exportiert sie, kein Aufrufer aendert sich. Damit laeuft der Boersen-Client
auf dem Pi **unveraendert** — mitsamt Retry-Logik und der Regel, dass eine noch
offene Kerze nie gespeichert wird. Zwei Maschinen, die unabhaengig entscheiden
wann eine Kerze fertig ist, waeren ein Fehler fuer spaeter gewesen.

### Was laeuft

Postgres 17 auf dem Pi, auf 426 MB getrimmt (`shared_buffers 32MB`,
`max_connections 20`, Checkpoints alle 15 min gegen SD-Karten-Verschleiss).
Vier systemd-Timer, jeder mit hartem `MemoryMax` — geht etwas schief, stirbt der
Dienst und nicht die Maschine:

| Timer | Takt | Aufgabe |
|---|---|---|
| `tb-collect-fast` | alle 5 min | M1, M15 fuer vier Symbole (~58 s pro Lauf) |
| `tb-collect-slow` | stuendlich, :04 | H1, H4, D1, W1 + Funding |
| `tb-health` | alle 15 min | meldet stillstehende Serien via `systemctl --failed` |
| `tb-backup` | naechtlich 03:20 | `pg_dump`, sieben Staende |

Erster Kaltstart: 28 Serien, 142 s, 74 MB Spitze. Der erste automatische Lauf
hat um 22:20 von selbst ausgeloest.

### Der Fund, der wichtiger ist als der Pi

**Die Testsuite leert `proposals` vor jedem Fall** — `truncate()` ruft nur die
Fixture. Solange nie eine Postgres-Datenbank erreichbar war, uebersprang sich
jeder dieser Tests und es fiel niemandem auf. Mit der ersten laufenden Datenbank
waere jeder Testlauf ein Loeschbefehl auf die Tabelle gewesen, in die
`run_live.py` echte Vorschlaege schreibt.

Jetzt: eigene Datenbank `traidingbrain_test`, neues `TB_POSTGRES_TEST_URL`, und
ein Riegel in `conftest.py`, der den Lauf **verweigert** statt warnt, wenn beide
URLs gleich sind. Eine Warnung in einer Testsuite wird einmal gelesen.

Nebenbei: `psycopg-pool` wurde von `storage/postgres.py` importiert, stand aber
nicht in den `dependencies`. Auf jedem Rechner, der das Projekt schon einmal
gebaut hat, faellt das nicht auf. Der Pi war die erste frische Installation seit
dem Pool-Commit, und genau dort ist es gescheitert. Nachgetragen.

### Was der Pi bewusst nicht bekommt

- **Keine Order-Ausfuehrung.** Nicht aus Leistungsgruenden: ein Pi, der nachts
  eigenstaendig Orders sendet, hebt die Bestaetigungsregel auf, die die
  Architektur traegt.
- **Keine Backtests, keine Analyse-Engine, kein Brain.** Der CLI-Weg braucht
  Node.js, und Node hat armv6 vor Jahren fallengelassen.

### Offen

- **Open Interest und Long/Short-Quote fehlen noch.** `data/derivatives.py`
  liefert DataFrames und importiert pyarrow — es braucht denselben Schnitt, den
  `grid.py` fuer `frames.py` gemacht hat: Holen von Speichern trennen.
- **Sync Postgres nach Parquet** ist noch nicht gebaut. Der Pi sammelt vorwaerts,
  aber niemand raeumt es bisher ins Archiv.
- **Wirtschaftskalender** koennte der Pi auch ziehen (`fetch_fomc.py` braucht nur
  httpx).
- **Statusseite im LAN** und eine Benachrichtigung aufs Handy bei Ausfall.
- **Backups liegen auf derselben SD-Karte.** Gegen Datenbankschaden hilft das,
  gegen einen Kartentod nicht — der Laptop muesste sie abholen.

Zugang: `ssh severin@traidingpi.local` (Schluessel, kein Passwort). Der Name
heisst **traidingpi**, mit demselben vertauschten i wie das Projekt.


Verwandt: [[traidingBrain — Regel-Aufnahme]]

---

**Session beendet 30.09.2026.** Alles gestoppt, 67 Commits, nichts offen im
Working Tree. Zum Weitermachen: [[traidingBrain — Übergabe]].

---

## Der Befund, der alles andere einordnet (04.10.2026)

Den ganzen Tag wurden Hebel gemessen: mehr Märkte, schnellerer Takt, Setups an
und aus, Score als Veto, Breakeven-Stop, Kostendecke. Alle veränderten die
**Zahl** der Trades, keiner das **Vorzeichen** der Erwartung. Der Grund steht in
einer Zerlegung:

| | pro Trade |
|---|---|
| Brutto (vor Gebühren) | −0,0102 R  [−0,070, +0,051] |
| Gebühren | −0,0530 R |
| **Netto** | **−0,0631 R** |

Das Brutto ist von Null nicht zu unterscheiden. **Die Einstiege tragen keine
Vorhersage — der ganze Verlust ist die Maut.** Damit ist auch erklärt, warum
sechs Hebel nichts bewegten: keiner von ihnen berührt, was ein Einstieg *weiss*.

Konsequenz für künftige Sessions: Ein Vorschlag, der nur die Trade-Zahl
verändert, kann das Vorzeichen nicht drehen. Nur etwas, das die Einstiege besser
macht, kann das — oder etwas, das die Maut senkt, und die ist fast ausgereizt.

### Die Formel, die die Live-Flaute erklärt

`Kostenanteil = Gebührensatz ÷ Stopweite`. Die Positionsgrösse ist Risiko
geteilt durch Stopabstand, also kauft ein enger Stop eine grosse Position, und
Gebühren skalieren mit der Position, das Risiko nicht. Umgestellt: bei der
Decke 0,15 muss ein Stop **0,700 % vom Preis** entfernt stehen.

BTCs Stunden-ATR ist 0,2 % des Preises. Der Stop müsste also **3,5 ATR** weit
stehen. Darum lösen Stunden- und 15-Minuten-Setups aus und werden alle
abgelehnt; H4/D1/W1 gehen durch. Neun von zwölf Papertrading-Konten sagen genau
diesen Satz. Das ist eine Tatsache über das Instrument und die Gebührentabelle,
nicht über die Regeln.

### Gemessen und übernommen

- **12 Märkte** statt 4 — mehr Gelegenheiten, gleiche Erwartung.
- **M15-Takt** statt H1 — +50 % Trades, pro Trade unverändert, also gratis.
- **Setup C abgeschaltet** — +133,2 R über vier Märkte. Steht jetzt in
  `config/settings.yaml` unter `setups.enabled`, nicht im Code.
- **Setup E eingebaut** (NocOrderBlock, V11), aus seiner Karte gebaut.
- **Maker-Gebühr auf Zielausgänge** — ein Take Profit liegt im Buch und
  verdient 0,02 % statt 0,055 % zu zahlen. +0,0092 R pro Trade = 17 % der
  Gebühren. (Ich hatte zuerst „ein Drittel" behauptet und musste korrigieren.)
- **Risiko 0,5 % → 1 %** pro Trade.

Erwartung dadurch: −0,0920 R → −0,0631 R → **−0,0539 R**. Das Intervall reicht
erstmals über Null: [−0,114, +0,008].

### Gemessen und verworfen

- **Kostendecke lockern** — doppelt so viele Trades, dreifacher Verlust. Die
  abgelehnten verlieren rund dreimal so viel wie die erlaubten. Über vier
  Einstellungen monoton, das ist der Abdruck eines echten Effekts.
- **Score als Veto** — 0,42 Standardfehler, Vorzeichen wechselt je Setup.
- **Breakeven-Stop** — 0,36 Standardfehler.

### Severins Liquiditäts-Indikator

Die Hypothese (Preis läuft zur schwereren Seite) ist über 619 037 Kerzen
**falsch**: die Steigung ist negativ und wächst linear mit dem Horizont
(−0,117 bei 24 Kerzen bis −0,710 bei 168). Brauchbar ist nur eine Seite:
`lean ≥ 0,6` — fast alles unberührte Gewicht über dem Preis — bringt die
folgende Woche **−0,195 ATR** gegen eine Grundlinie von **+0,761 ATR**. Die
einzige Bedingung im ganzen Datensatz, die in steigenden Märkten negativ wird.

Als Filter gegen das System geprüft — **durchgefallen.** Alle vier Märkte:

| | ohne | mit | |
|---|---|---|---|
| BTC | −0,0136 | −0,0489 | schadet deutlich |
| ETH | −0,0659 | −0,0789 | schadet |
| SOL | −0,0269 | −0,0262 | +0,0007 |
| XRP | −0,0553 | −0,0522 | +0,0031 |
| gepoolt | −0,0409 [−0,086, +0,008] | −0,0490 [−0,099, **−0,002**] | −12,3 R |

Das Vorzeichen steht je Markt 2:2, die Beträge nicht: die Schäden sind
zusammen zehnmal so groß wie die Hilfen. Der harte Grund steht aber in den
Intervallen — **ohne** Filter schliesst das Intervall die Null nicht aus, **mit**
Filter schon, auf der negativen Seite. Er macht aus einem System, das
nachweislich nicht verliert, eines, das nachweislich verliert.

(Bei drei Märkten hatte ich „keiner besser" gesagt; XRP hat das korrigiert.
Das Urteil blieb, die Formulierung war zu stark.)

Der Indikator bleibt im Code als **Merkmal**, nicht als Regel: die gemessene
Bedingung ist echt, aber zu selten und zu schwach, um ein Setup zu überstimmen.
Die ehrliche Sorge stand vorher im Skript: die Schwelle 0,6 wurde an genau
diesen Daten gefunden.

### Stop-Verbreiterung — der einzige signifikante Befund des Tages, gegen sich selbst

Einen unbezahlbaren Stop nicht ablehnen, sondern auf die billigste zulässige
Weite schieben und die Position kleiner rechnen. Das Risiko in Franken bleibt
gleich. Zwei Märkte:

| | Trades | pro Trade | Treffer | Intervall |
|---|---|---|---|---|
| ohne | 1331 | −0,0443 R | 37 % | [−0,118, +0,028] |
| Ziel bleibt | 1439 | −0,0474 R | 37 % | [−0,119, +0,027] |
| Verhältnis bleibt | 2009 | −0,0895 R | 36 % | **[−0,150, −0,026]** |

Die Variante, die Severin beschrieben hatte (Verhältnis halten), ist die
schädlichste: 678 Trades mehr, 121 R Kosten, und das einzige Intervall des
Tages, das die Null ausschliesst — auf der falschen Seite. Die Trefferquote
fällt wie vorhergesagt, was bestätigt, dass der Mechanismus echt gerechnet ist.

### Kostendecke, zweite Richtung — nichts zu ändern

Vier Märkte, 0,10 gegen die ausgelieferte 0,15:

    Decke 0.100   n=2234   -0.0471 R   [-0.105, +0.009]
    Decke 0.150   n=3300   -0.0409 R   [-0.088, +0.008]

Je Markt **2:2** — BTC und SOL für 0,10, ETH und XRP für 0,15. Ein Gleichstand
bei vier Märkten ist die sauberste Form von „kein Effekt". Entscheidend für die
Praxis: die 0,15 liefert **mehr** Trades *und* ist pro Trade besser, sie
dominiert. Enger stellen kostet beides, lockerer stellen war am 02.10. über
vier Einstellungen monoton widerlegt. Die Schraube steht richtig.

**Die Falle, in die ich fast getreten bin:** BTC allein gab der 0,10 ein
**+0,0455 R** — die erste positive Erwartung des Projekts. Über vier Märkte ist
dieselbe Decke −0,0471 R. Ein Markt, vier Zellen angeschaut, die beste
genommen. Seitdem steht das Konfidenzintervall in derselben Zeile wie der
Mittelwert, und die Studie druckt eine Tabelle je Markt plus die Zeile *beste
Decke je Markt* — weil der gepoolte Mittelwert verdeckt, ob die Märkte sich
einig sind, und genau diese Einigkeit einen Effekt von Rauschen trennt.

### Drei Auswertungsfehler, die alle in die bequeme Richtung liefen

Dass die Studien auf mehrere Prozesse aufgeteilt wurden (eine Zelle braucht
beim M15-Takt 22 Minuten, ein ganzer Lauf überlebt kein Zeitfenster), hat drei
Fehler erzeugt — und alle drei hätten das Ergebnis geschmeichelt:

1. **Verlorene Zellen.** Jeder Prozess hält den Stand vom Start und schreibt
   alles zurück; der letzte hätte die Arbeit der anderen gelöscht. Keine
   Fehlermeldung, nur eine Messung, bei der zwei Drittel fehlen. Die Datei wird
   jetzt vor jedem Schreiben neu gelesen und verschmolzen.
2. **Vergleich über verschiedene Marktmengen.** Die Arme werden nicht
   gleichzeitig fertig, also verglich die Auswertung zwei Märkte gegen einen.
   Bei der Verbreiterung stand da **+42,9 R dafür**; richtig sind −8,7 R und
   −38,6 R *dagegen*. Das Vorzeichen war falsch. Beide Studien schneiden jetzt
   auf die Märkte, die alle Arme fertig haben.
3. **Golden-Backtest ohne Gewinnpfad** (siehe unten).

### Die Zielrechnung, nüchtern

12 000 → 15 000 Franken bis 30.10.2026 sind bei ~182 Trades **+1,65 R pro
Trade**. Ein weltklasse System schafft +0,10 bis +0,30. Das Ziel ist mit diesem
Hebel und diesem Zeitfenster nicht erreichbar; erreichbar ist, die Erwartung
über Null zu bringen und das belegt zu haben.

### Zwei eigene Fehler, beide öffentlich korrigiert

- **Setup C**: nach 2 Märkten (+5,3 R) für widerlegt erklärt, nach 3 (+53,8 R)
  umgedreht, nach 4 (+133,2 R) bestätigt. Zweimal zu früh geurteilt.
- Einen „eingefrorenen Takt" nach einem Neustart als Bug gemeldet — es war die
  erste Warteschlange, in der jedes flache Symbol seine Analyse neu baut.

### Lücke geschlossen

Der Golden-Backtest bestand aus 7 Stops und einem Zwangsschluss — **kein
einziger Take Profit**. Der Gewinnpfad war ungeschützt, und die Maker-Änderung
ging durch Code, den keine eingefrorene Datei beobachtete. Jetzt ein zweiter
Lauf mit 31 Zielen gegen 23 Stops. Belegt statt behauptet: dreht man die
Maker-Gebühr zurück, fällt der neue Lauf und der alte bleibt grün.

### Offene Fragen an Severin

- Chartzeiten UTC oder Schweizer Zeit?
- Risiko als Prozent oder als fester Franken-Betrag?
- Obergrenze für Trades pro Tag?
- Vor echtem Geld: Börsenkonto eines Erwachsenen — und **dieser Erwachsene muss
  den Bestätigungsknopf halten.**

### Die LLM-Schicht: gebaut, nicht gestartet (04.10.2026, Abend)

Nach vier verworfenen Hebeln bleibt nur die Richtung, die die Einstiege selbst
betrifft. Die Schicht war von Anfang an dafür geplant (`brain/`, Stufe 4/5) und
nie ausgeführt, weil sie pro Aufruf kostet. Also zuerst gerechnet.

**Scanner gegen Richter.** `BrainStrategy` lässt das Modell den Markt selbst
finden: das Tor sieht jede Kerze, 19 % passieren, auf BTC sind das **26 100
Aufrufe = $338** (Batch, Opus) bzw. $1 353 für vier Märkte — gegen ein Budget
von $25 in `settings.yaml`. `BrainJudged` fragt nur dort, wo ein Setup
ausgelöst hat: **6 545 Aufrufe**, ein Viertel davon.

| | BTC | vier Märkte |
|---|---|---|
| Richter, Opus | $85 | $339 |
| Richter, Sonnet | $44 | $174 |
| Richter, Haiku | $22 | $87 |
| Richter über Abo | $0, ~3,6 h | $0, ~14 h |

(Ich hatte zuerst 2 855 Aufrufe geschätzt und damit um das 2,3-fache zu wenig.
Der Richter wird *vor* der Risikoschicht gefragt und sieht alles, was ein Setup
je vorschlägt.)

**Die Arbeitsteilung ist der Kern, nicht die Ersparnis.** Das Setup behält
Entry, Stop und Ziel — die Messung sagt nicht, dass Severins Regeln falsch
sind, sie sagt, dass die *Auswahl* unter ihnen keine Information trägt. Auswahl
ist genau das, was dem Modell bleibt.

**Der riskante Teil: preislose Beschreibung.** Der Prompt zeigt absichtlich
keine Preise, Symbole oder Daten — sonst erkennt das Modell die Periode und
sein Wissen über den späteren Verlauf fließt ein, ein Lookahead, den kein Test
findet. Ein Vorschlag trägt drei Preise. Er wird daher in ATR-Abstände
übersetzt, gesichert durch **Skaleninvarianz**: verzehnfacht man den Markt,
darf sich die Beschreibung um kein Zeichen ändern. Per Mutation geprüft.

**Zwei Fallen, vorher geschlossen.** Der Decision-Cache ist auf Snapshot,
Modell, Prompt-Version und Schema geschlüsselt — zwei verschiedene Fragen zur
gleichen Kerze unter derselben Version kollidieren *stumm*, der Richter hätte
die Scanner-Antwort zurückgelesen. Darum `JUDGE_VERSION`. Und `JudgingBrain`
erbt `decide()`; direkt gerufen hätte es die Scanner-Frage gestellt und die
Antwort als Urteil verbucht — wirft jetzt einen Fehler.

**Die Messlatte mit `FakeBrain` (gratis) ist unbrauchbar als Vergleichslinie.**
Sie lehnt 97 % ab: zu zwei Dritteln ein schlichtes WAIT, der Rest überwiegend
am Reward-to-Risk-Guard (963 von 1 021 Guard-Ablehnungen). Von 1 331 Trades
bleiben 110, pro Trade −0,1287 gegen −0,0443 R. Die Summe sieht um +44,8 R
besser aus — aber nur, weil 92 % der Trades nicht stattfanden.

`FakeBrain` ist als *Scanner* entworfen; seine Schwellen setzen ein
vorgefiltertes Tor voraus. Das sagt daher **weder**, dass ein Modell hilft,
**noch** dass es nicht hilft. (Ich hatte daraus zuerst geschlossen, die
Scoring-Schicht sei das Problem — falsch: das Veto kommt aus FakeBrains eigenem
Urteil und dem Guard, nicht aus `score()`.)

**Nützlicher Nebenfund ohne einen Franken:** Pläne sterben überwiegend am
Reward-to-Risk-Guard. Für ein echtes Modell ist das die erste Stelle, an der
seine Vorschläge scheitern werden.

**Offen und nur mit Severins Entscheidung weiterzuführen:** ein Markt über
Haiku (~$22) oder über das Abo (gratis, ~3,6 h, verbraucht Kontingent).

---

## 05.10.2026 — Prüfung gegen den Selbstlern-Masterplan, und warum alle sechs Hebel scheitern mussten

Severin hat `TRADING_BRAIN_SELBSTLERNEND_MASTERPLAN_FUER_CLAUDE.md` gebracht und
gesagt: umsetzen. Der Plan verlangt in §24 selbst, zuerst Bestand zu prüfen und
nichts ohne Grund neu zu bauen — also 21 Prüfer über zehn Funktionsbereiche,
jeder mit einem Gegenprüfer, dessen Auftrag war zu *widerlegen*.

### Der eine Satz, der alles ordnet

Die sechs gemessenen und verworfenen Hebel liegen in **nur zwei Familien**:

1. *dieselben Signale neu bepreisen* — Kostendecke enger, Kostendecke weiter,
   breitere Stops, Ziel-Deckel bei 1,75 R;
2. *unter denselben Signalen neu auswählen* — Liquidity-Lean-Filter, LLM-Richter.

Beide können ein Vorzeichen, das schon null ist, arithmetisch nicht drehen. Die
Brutto-Erwartung der genommenen Einstiege ist −0,0102 R mit Intervall
[−0,070, +0,051]; in einer Menge, die im Mittel nichts ergibt, gibt es keine
besser-als-nichts-Teilmenge zu finden, und Neu-Bepreisen verschiebt nur die Maut.

**Nie versucht: die Population ändern.** Und der Grund war, dass die
abgelehnten Signale nirgends existierten — jede Ablehnung war ein Integer
(`live/paper.py:487`). Nach tausend Ablehnungen gab es eine Zahl und null
wiederherstellbare Signale. Damit sind die fünf Risikoregeln in `sim/plan.py`
**selbst ungeprüfte Hypothesen**: `study_cost_floor.py` hat die *Schwelle*
einer davon über vier Märkte variiert, nie ob die Regel existieren soll.

Erste Zahlen auf BTC, sobald das Protokoll lief: von **2 801 Signalen werden
2 256 abgelehnt** — 1 273 von der Kostenregel, 983 vom Chance-Risiko-Minimum —
und nur 545 genommen. 81 % der Population ist noch nie angeschaut worden.

### Ziel-Deckel: der Mechanismus stimmt, er zahlt nur nicht

Zwei von drei Armen auf BTC (der dritte lief ins Zeitlimit):

| Arm | n | pro Trade | Treffer |
|---|---|---|---|
| ohne Deckel | 549 | −0,0136 R | 38,6 % |
| Vorschlag abgelehnt | 463 | −0,0201 R | 41,9 % |

Die Trefferquote **steigt** wie vorhergesagt — ein näheres Ziel wird öfter
erreicht. Pro Trade wird es trotzdem schlechter. Der Journal-Befund war in
seiner wirtschaftlichen Behauptung ein Belegungs-Artefakt.

### Zwei stille Defekte in der Vorwärts-Evidenz, beide ohne Symptom

- **Funding erreichte den laufenden Broker nie.** Der Plan wird einmal im
  Konstruktor übergeben; alles später Fällige wurde gegen das Listenende
  gebucht, also als Null. `papertrade.py` holte die Raten alle 20 Zyklen und
  schrieb sie auf die Platte, wo sie niemand las. (Mein erster Fix war falsch
  und ich habe ihn vor dem Test erwischt: den Cursor nach der Uhr zu setzen
  verwirft eine 08:00-Rate, die 08:10 ankommt, als „schon vorbei".)
- **`decide()` verbrannte den Signalbalken.** Der Cursor wurde vor der
  Entscheidung gesetzt und danach unbedingt persistiert, auch nach einer
  Exception. Ein Timeout zerstörte dieses Signal dauerhaft — bei ~2 Signalen
  pro Tag der teuerste stille Verlust der Schleife.
- Dazu: der Abbruch bei dünner Historie kehrte zurück, *bevor* `settle()` lief —
  ein offener Stop blieb unbewacht, und es waren Positionen offen.

### Franken, wie Severin sie wollte

| | nachgespielt (alle) | heutige Konfig (ohne C) | vorwärts |
|---|---|---|---|
| Gewinne | +66 349,74 | +47 537,42 | +6,99 |
| Verluste | −76 656,95 | −52 456,76 | −86,65 |
| netto | −10 307,20 | −4 919,34 | −79,66 |
| **brutto** | −4 018,76 | **−984,96** | −73,33 |
| Gebühren | −6 507,41 (63 %) | −4 119,59 (**84 %**) | −6,33 |

In der heutigen Konfiguration sind **84 % des Verlusts Gebühren**. Brutto
verlieren 1 862 Trades zusammen 985 Franken — bei 1 862 Trades praktisch Null.
Die Einstiege sind nicht schlecht, sie sind *nichts*.

Die −79,66 vorwärts gegen −24,61 auf den Konten: **ein** Trade, BTC am 02.10.,
Setup C, 49,84 Franken Risiko aus der alten 10 000er-Konfiguration, netto
−55,05. −55,05 + −24,61 = −79,66, genau.

### Gebaut (alles getestet, mutationsgeprüft, ruff + mypy --strict grün)

- **Block-Bootstrap** (§13) — Trades sind keine unabhängigen Stichproben.
  *Korrektur an mir selbst:* ich erwartete grob zu enge Intervalle; es sind
  1,06–1,29×, Block 8–14 Trades, **kein Befund dreht sich**.
- **Triple-Barrier-Labelling** (§8) — was aus einem Signal geworden wäre,
  unabhängig davon, ob ein Platz frei war. 500 Zufallspfade laufen durch
  Labeller *und* echten Broker, Übereinstimmung auf 1e-9.
- **Walk-forward mit Purging und Embargo** (§11) — ein Label deckt ein
  Intervall ab, keinen Zeitpunkt; die Schranke liegt an der *Validierung*,
  nicht am Test.
- **Protokoll des abgelehnten Signals** (§6) — `assess()` gibt die Regel, den
  Satz und die Kostenschätzung zurück, die vorher eine Zeile nach ihrer
  Berechnung verworfen wurde. Eigene Datei ohne Equity- oder PnL-Spalte, damit
  ein Schattenfall strukturell kein Trade sein kann. Append-only.
- **Funding in den Labels** — fehlte ganz; der Übereinstimmungstest baute den
  Broker ohne Raten und war dafür strukturell blind. 48 h spannen bis zu sechs
  Settlements, eines ist bei 1,5 % Stop rund 0,02 R.
- **Bonferroni wird jetzt angewandt**, nicht nur gedruckt.

### Zwei gute Nachrichten aus der Prüfung

- **§22 erfüllt und verifiziert:** Echtgeld braucht zwei unabhängige Signale,
  `allow_live` hat keinen Produktionsaufrufer, `testnet: true`, eine umgedrehte
  Umgebungsvariable verweigert den Start.
- **§1 erfüllt:** kein Martingale irgendwo. Verluste senken ausschliesslich die
  Aktivität, nie die Grösse.

### Offen, und Severin gehört die Entscheidung

Zwölf korrelierte Märkte mit je 1 % auf zwölf **getrennten** 1000-Franken-Konten
haben **keine Gesamtrisiko-Grenze**. Kein Echtgeld im Spiel, aber zwölf Märkte
liefern auch nicht zwölfmal so viel Beweis, und §5 des Plans verlangt
ausdrücklich einen Markt, bis die Pipeline geprüft ist.

**Nicht gebaut, bewusst:** jedes numerische Modell. Die Labels sind heute
gelandet und nie auf echten Daten gelaufen, und die Population, die sie
abdecken sollen, entsteht gerade erst. Ein Filter, jetzt auf der
genommenen-nur-Stichprobe trainiert, reproduziert den Lean-Filter mit mehr
Maschinerie.

### Nachtrag am selben Tag — die Antwort auf die Population-Frage

`study_refused.py`, BTCUSDT, 2 861 gelabelte Signale. Die erste Messung in
diesem Projekt, die *abgelehnte* Signale anschaut.

| Gruppe | n | brutto | netto | Treffer |
|---|---|---|---|---|
| genommen | 549 | **+0,0480** | −0,0046 | 41 % |
| abgelehnt, Kostenregel | 1 284 | −0,0532 | −0,3404 | 38 % |
| abgelehnt, Chance-Risiko | 1 002 | +0,0110 | −0,1316 | 58 % |

**Beide Regeln sind bestätigt und damit kein Hebel.** Die Kostenregel lehnt
Signale ab, die brutto nichts wert und netto verheerend sind (−0,34 R) — genau
ihre eigene Behauptung. Die Chance-Risiko-Regel lehnt Signale ab, die **58 %**
der Zeit treffen, viel öfter als das, was wir handeln — und trotzdem 0,13 R
netto verlieren, weil jeder Gewinn zu klein ist, um die Maut zu zahlen.

**Die eigentliche Zahl:** genommene Signale sind brutto +0,048 und netto
−0,0046. Die Maut ist also 0,053 R pro Trade, und wir sind **0,005 R von der
Null entfernt**. Das Intervall auf dem Brutto ist [−0,053, +0,154], enthält
also die Null — ein Kandidat, kein Befund.

Nicht mit der −0,0102-R-Zahl vom 04.10. vergleichen: dort Journal-Trades mit
Platzkonkurrenz, hier jedes Signal gelabelt als wäre es das einzige, mit
48-h-Zeitschranke. Nur der Vergleich *innerhalb* dieses Laufs gilt.

### Der Lernfilter (§8) — und die Zeile, die ihn beim Luegen erwischt

Ridge-Regression auf Netto-R, Walk-forward mit Purging ueber den echten
Label-Horizont, Schwelle auf der Validierung, zehn Fenster, 2 104 Testsignale
auf BTC. Dazu der Permutationstest: derselbe Ablauf mit **gewuerfelten** Labels,
hundertmal.

| | n | netto | Treffer |
|---|---|---|---|
| alle Signale | 2 104 | −0,2184 R | 44 % |
| **vom System genommen** | 400 | **+0,0084 R** | 41 % |
| vom Filter behalten | 433 | −0,0605 R | 52 % |

Der Filter ist **0,069 R pro Trade schlechter als die Regeln, die wir haben** —
und er hat eine Population mit *hoeherer* Trefferquote gefunden, um dorthin zu
kommen. Derselbe Fehlermodus wie beim Ziel-Deckel, zweimal an einem Tag.

Der Permutationstest sagt trotzdem, dass er etwas Echtes lernt: **null von
hundert** Zufallslaeufen waren so gut, p ≈ 0,010.

**Die methodische Lehre, die mich fast einen Falschbericht gekostet hat:** mein
erster Lauf meldete „+0,1578 R gegen alle Signale, p = 0,01". Wahr und
irrefuehrend — „alle Signale" enthaelt die 80 %, die die Risikoregeln ohnehin
ablehnen und die messbar schlecht sind. Ein Filter, der sie vermeidet, entdeckt
nur die Regeln neu. Die einzige ehrliche Vergleichslinie ist, was das System
tatsaechlich nimmt, im selben Testfenster. Permutationstest und Vergleichslinie
beantworten zwei verschiedene Fragen: findet das Verfahren Struktur, und ist
die gefundene Struktur besser als das Vorhandene. Hier: ja, und nein.

### Wo die Null wirklich liegt

Dieselben 549 genommenen BTC-Signale, neu gelabelt mit **einer** Aenderung — der
Gebuehr. Jeder Preis bleibt, also kann sich Brutto nicht bewegen.

| Gebuehr | brutto | Maut | netto |
|---|---|---|---|
| heute (0,055/0,020 %) | +0,0480 | 0,0527 | **−0,0016** |
| −10 % (BNB-Rabatt) | +0,0480 | 0,0474 | **+0,0037** |
| −25 % (VIP 1 + BNB) | +0,0480 | 0,0395 | +0,0116 |
| −50 % | +0,0480 | 0,0263 | +0,0248 |
| 0 | +0,0480 | 0,0000 | +0,0511 |

**Die Null liegt bei 97,0 % der heutigen Gebuehr — 3 % Rabatt.** Binance gibt
10 % fuer Zahlung in BNB und 25 % bei VIP 1 mit BNB; beides sind Einstellungen,
keine Leistungen.

Alle Intervalle enthalten die Null, es ist Signal-Ebene ohne Platzkonkurrenz,
ein Markt. Das sagt **nicht**, dass wir mit Rabatt profitabel sind. Es sagt,
dass der Abstand zur Null die Groesse eines gewoehnlichen Rabatts hat — und das
ist eine andere Art von Problem als einen Vorteil finden zu muessen.

### 05.10.2026, nachmittags — drei Befunde, die nichts mit Strategie zu tun haben

**1. Der Risiko-Deckel hielt aus dem falschen Grund.** Der 1-%-Deckel, der jeden
bisherigen Trade dimensioniert hat, verglich `min_samples_for_uncap` (200) mit
den brauchbaren Nachbarn **einer** Kerze — und die sind durch `k_neighbours`
auf 120 begrenzt, nach Distanzfilter und Deduplikation weniger. Der Vergleich
war also bei jeder Entscheidung wahr. Der Deckel war richtig; der Grund, warum
er hielt, war eine Unmoeglichkeit.

Das ist genau der Fehler, den eine Pruefung im Code schon abfaengt (k = 25 gegen
eine Schwelle von 30, damals siebzigtausend Lookups lang unsichtbar) — er kam
durch, weil die beiden Zahlen in verschiedenen Dateien und damit in
verschiedenen Modellen stehen, die sich nicht sehen. Die neue Pruefung sitzt auf
`AppConfig`, wo beide sichtbar sind, und greift genau dann, wenn es anfaengt zu
zaehlen: sobald jemand Kalibrierung als belegt markiert.

Die Frage war ausserdem die falsche. „Diese Kerze hat 200 Zwillinge" ist eine
Aussage ueber Umgebung, nicht ueber Kalibrierung. Die echte Frage braucht die
Zuversicht neben jedem aufgeloesten Fall, und die speichert `history.Case`
nicht. Das ist die offene Arbeit. Das Verhalten bleibt unveraendert: der Deckel
haelt weiter bei 1 %, jetzt weil nichts gemessen hat, dass die oberen Baender es
verdienen — was am 05.10. einfach stimmt.

**2. Ein p-Wert von 0,010 ist bei hundert Permutationen der kleinste moegliche.**
Nicht „1 % Irrtumswahrscheinlichkeit", sondern „besser als alle hundert". Beim
Testen der Permutationsmaschinerie fiel die Kontrolle „reines Rauschen darf die
Null nicht bestehen" bei p = 1/13 = 0,077 durch — kein Fehler, sondern die
Aufloesung: bei zwoelf Permutationen *ist* 0,077 die Untergrenze, und Rauschen
landet dort etwa jedes dreizehnte Mal. Jeder Report druckt die Untergrenze
jetzt daneben.

**3. Ein veroeffentlichtes Urteil zurueckgezogen.** Die Liquiditaets-Studie
rechnete Intervalle so, als waeren 619.037 ueberlappende Vorwaertsrenditen
unabhaengig — bei 168 Kerzen Horizont teilen zwei Nachbarn 167 Kerzen. Der
Docstring sagte das selbst und lieferte das Urteil trotzdem mit. Jetzt
korrigiert per Block-Bootstrap, Blocklaenge mindestens der Horizont, fuer einen
Eimer mit dessen Anteil skaliert. Auf BTC bei Horizont 24 kostet das den
Befund: die Grundlinie war unkorrigiert [+0,064, +0,141] und schloss die Null
aus — korrigiert [−0,066, +0,270] und tut es nicht. Die Steigung ebenso. Der
vollstaendige Zwoelf-Markt-Lauf steht noch aus.

**Nebenbefund, der schon einmal Geld gekostet haette:** die Kennung, mit der
jede Studie das Signalprotokoll liest, war in drei Skripte handkopiert und
schon auseinandergelaufen — eines nahm `max_bars` auf, zwei nicht. Eine Kennung,
die um ein Zeichen abweicht, liefert nicht falsche Zeilen, sondern **keine**,
und eine Studie ueber eine leere Menge berichtet selbstbewusst gar nichts. Jetzt
an einer Stelle, bytegleich: sie trifft alle 7.338 gesammelten Zeilen.

**ETH ist drin:** 3.561 Signale, 2.772 abgelehnt (77,8 %), 782 Trades — mehr als
BTCs 2.861 und dasselbe Ablehnungsverhaeltnis. SOL und XRP laufen.

### 05.10.2026, abends — die Gegenpruefung kippt den Befund des Tages

Alles oben Gemessene stand auf **einem** Markt. Die Sammlung ueber ETH, SOL und
XRP ist durch (3.561 / 3.275 / 3.146 Signale), und gepoolt ueber vier Maerkte
und 12.843 gelabelte Signale sieht es anders aus.

| Gruppe | n | brutto | netto | Treffer | Intervall auf brutto |
|---|---|---|---|---|---|
| genommen | 3.300 | **+0,0136** | −0,0340 | 39 % | [−0,031, +0,059] |
| abgelehnt (alle) | 9.472 | −0,0365 | −0,2163 | 46 % | [−0,065, −0,008] ohne Null |
| abgelehnt, Kosten | 4.726 | −0,0555 | −0,2996 | 37 % | [−0,099, −0,011] ohne Null |
| abgelehnt, Chance-Risiko | 4.745 | −0,0175 | −0,1334 | **55 %** | [−0,047, +0,012] |

**Die Null liegt bei 69 % Rabatt, nicht bei 3 %.** BTCs brutto +0,0480 war der
beste von vier; gepoolt sind es +0,0136. Selbst ganz ohne Gebuehr bleibt netto
+0,0151 mit einem Intervall, das die Null enthaelt. Die eine handlungsfaehige
Schlussfolgerung des Tages war um den Faktor zwanzig falsch — und die Warnung
lag vor: das Journal sagte bei vier Maerkten, BTC sei der einzige positive.

**Was haelt, haelt jetzt auf 9.472 statt 2.286 Signalen:** beide
Ablehnungsregeln. Die abgelehnten Signale sind brutto schlechter als nichts,
Intervall ohne Null — die Regeln trennen also wirklich. Und die
Trefferquoten-Umkehrung wiederholt sich: 55 % Treffer bei den von der
Chance-Risiko-Regel abgelehnten, und trotzdem 0,13 R Verlust.

**In Preisen, wo das Problem eine Zeile lang ist:** runde Fahrt 0,0750 % des
Preises, erfasste Bewegung im Mittel +0,0626 %, im Median **−0,8497 %**.
1.275 von 3.300 Trades bezahlen sich selbst — 39 %.

### Severins Vorschlag: mehrere Trades gleichzeitig

Strukturell richtig, und der erste Punkt, der die Zielrechnung bewegt. Das Ziel
ist ein fester Gesamtzuwachs, verteilt sich also auf mehr Verzinsungsschritte:

| Trades/Tag | Chancen | noetig pro Trade | |
|---|---|---|---|
| 2,56 (heute) | 64 | +4,22 R | 1,96x ueber dem Maximum |
| 5,0 | 125 | +2,16 R | am Maximum |
| 7,7 | 192 | **+1,40 R** | innerhalb |

Bei dreifachem Takt faellt die Anforderung von „auch mit perfektem System
unmoeglich" auf „innerhalb des Moeglichen". Aber bei der gemessenen Erwartung
von −0,034 R vervielfacht derselbe Motor den Verlust: 64 Trades −21,74 CHF,
1.000 Trades −335,22 CHF. **Vorzeichen zuerst, Takt danach.**

**Selbstkorrektur:** die Meldung „zwoelf Maerkte ohne Gesamtrisiko-Grenze" war
bei der heutigen Einstellung falsch. 1 % je Konto auf zwoelf getrennten Konten
sind zusammen 2 % des Portfolios. Erst bei `max_open_positions=8` waeren es
8 % gleichzeitig — und so korreliert wie Krypto ist, naeher an *einer* 8-%-Wette
als an 96 unabhaengigen. Das ist der Preis am Vorschlag, beherrschbar wenn bekannt.

### 05.10.2026, Abend — die 1-100-Bewertung, gebaut und abgelehnt

Severin wollte eine Zahl von 1 bis 100, die sagt, wie gut es jetzt waere zu
kaufen oder zu verkaufen, wenn er in 5-10 h im Plus sein will. Anlass war ADA:
das Dashboard zeigte „85/100, deutlich, Richtung aufwaerts", ADA lief +10,84 %,
und das System nahm nichts.

**Warum die 85 nicht falsch, aber die Antwort auf eine andere Frage ist.** Sie
mischt Klarheit, Einigkeit, Konsens und Abdeckung — wie stark die Belege *mit
sich selbst* uebereinstimmen. Nichts daran war je gegen die Zukunft trainiert.
`why_no_trade.py` zeigte den Rest: „Setups keines ausgeloest, Zonen 125
unberuehrt davon 0 in Reichweite, kein Sweep vor 34 Kerzen". Die 85 ist eine
Trendbeschreibung, kein Handelssignal.

**Gebaut:** `learn/outlook.py` (28 Merkmale je Kerze, Ziel = vorzeichenbehaftete
Bewegung ueber 5/10 h minus runde Fahrt) und `scripts/study_outlook.py`
(Walk-forward, Purging, Embargo = Horizont, Block-Bootstrap, Permutationstest).
13 Tests, darunter der Zukunfts-Mutationstest.

**Ergebnis: es gibt keine Zahl.** 34.394 Faelle, 18 Fenster, 1.435 Tage.

| Horizont | Richtung | alle Kerzen | gewaehlt | p |
|---|---|---|---|---|
| 5 h | verkaufen | −0,0213 % | −0,0279 % | 0,548 |
| 10 h | kaufen | +0,0441 % | **+0,0223 %** | 0,806 |
| 10 h | verkaufen | −0,0441 % | −0,0095 % | 0,194 |

**Rangkorrelation Vorhersage/Ergebnis: +0,0086 (5 h), +0,0069 (10 h).** Das ist
die Zahl, die entscheidet: bei null ist jede Bandbreite gleich gut. Bei 10 h
waehlte das Modell schlechter als der Durchschnitt.

Nebenbefund: jede Kerze kaufen und 10 h halten bringt +0,0441 % gegen 0,0750 %
runde Fahrt. Schon der blinde Trade verliert — in einer stark steigenden Phase.

**Zwei eigene Fehler, beide jetzt im Code dokumentiert.** Die
Kalibrierungstabelle buendelte zuerst nach dem *Ergebnis* statt nach der
Vorhersage und lieferte eine perfekt monotone Leiter von −1,47 % bis +1,65 %
mit 0 % und 100 % Treffern — ein scheinbar ueberwaeltigender Befund, der nur
sagt „die schlechtesten Faelle waren schlecht". Und die Testdaten liessen alle
Zeitebenen gleichzeitig *beginnen*, wodurch die Wochenebene nie aufgewaermt war
und `build_cases` eine leere Liste lieferte, die wie ein Fehler aussah.

**Was NICHT geprueft ist, und es ist die Ausgangshypothese:** kein einziges
Abstandsmerkmal (Zone, Swing, Fair-Value-Luecke) ist dabei — weggelassen aus
Rechengruenden, weil `ZoneTimeline.known_at` pro Aufruf eine Liste kopiert.
Genau die Familie, aus der ADA kam. Naechster Schritt.

**Nebenbei behoben:** `index_at_or_before` baute bei jedem Aufruf ein volles
Zeitstempel-Array neu. Einmal gecacht — 39x schneller, identische Antworten.
Der eigentliche Brocken ist aber der Analyse-Aufbau mit 127 s je Markt.

**Sicherheitsbefund:** der Kill-Switch stoppt `papertrade.py` nicht (nur in
`RiskLimits.check` geprueft, das der Papertrader nie aufruft), und
`max_daily_loss_pct` / `max_weekly_loss_pct` / die Verlustserien-Abkuehlung sind
wirkungslos, weil die zwei Pfade, die sie pruefen, ein hartkodiert leeres
`recent_trades=[]` uebergeben. Bei Papiergeld harmlos, vor echtem Geld nicht.

## Die drei Risikosperren sind jetzt verdrahtet (2026-10-05, Branch `claude/amazing-raman-3ad84b`)

Der Sicherheitsbefund aus dem Block darüber ist behoben. Er war nicht ein Bug in
den Regeln — die Regeln waren richtig —, sondern eine Methode, die niemand
aufrief: `live/paper.py` importierte `risk.limits` überhaupt nicht, und das ist
der Prozess, der auf zwölf Märkten laufend Positionen eröffnet.

**Was jetzt gilt.** `PaperTrader` bekommt eine `RiskLimits` als Pflichtargument
und fragt sie vor jeder Entscheidung. Die Verlustgrenzen und die Abkühlung
rechnen gegen die echten Vorwärts-Trades dieses Kontos aus dem Journal, nicht
gegen eine leere Liste.

**Die Entscheidung, die dabei zu treffen war: pro Konto, nicht über das
Portfolio.** Die zwölf Märkte halten absichtlich zwölf getrennte Konten, damit
ein Verlust auf einem nicht die Positionsgrösse eines anderen verändert. Eine
gepoolte Verlustgrenze hätte genau das aufgehoben — ein schlechter Morgen auf
SOL hätte BTC gestoppt, und keine Zeile wäre mehr mit den Backtests
vergleichbar, aus denen die Erwartung kommt. Der Preis steht im Code: es gibt
hier **keine** Obergrenze auf Portfolio-Ebene. Zwölf Konten können am selben Tag
jedes seine fünf Prozent verlieren. Der Echtgeld-Pfad handelt ein Konto und ist
davon nicht betroffen.

**Der Kill-Switch löscht auch eine liegende Order.** Eine Papier-Order wartet an
einem Limit und wird von `_settle` gefüllt — hätte der Switch nur neue
Entscheidungen verweigert, wäre er aktiv gewesen und die Position trotzdem
entstanden. Eine **offene** Position bleibt dagegen unangetastet: sie dort zu
schliessen würde einen Ausstieg zu einem Preis ins Vorwärts-Journal schreiben,
den der Switch gewählt hat und nicht der Plan. Dafür gibt es `--close-out`, und
das ist eine Entscheidung von Severin.

**Sichtbar gemacht**, weil eine gesperrte Sperre auf dem Schirm wie ein ruhiger
Markt aussieht: eigener Zähler pro Konto (`refused_by_limits`, auch im
Dashboard-Readout), `papertrade.py --status` schreibt `GESPERRT: <Grund>`, und
der Switch meldet sich beim Wechsel seines Zustands im laufenden Lauf.

**Dashboard sagt nicht mehr 1000 CHF.** `run_dashboard.py` hat die
Simulations-Startsumme als Konto gemeldet — damit rechnete `limits_allow_trading`
gegen ein Guthaben, das niemand hält, und der Tagesverlust war konstruktionsgemäss
null, die Verlustgrenzen also „erfüllt" statt „unbekannt". Jetzt kommt die Zahl
über `--equity`, so wie `run_live.py` es schon macht; ohne die Angabe sagt das
Dashboard, dass es keinen Kontostand kennt. Offen bleibt bewusst: auf dem
Echtgeld-Pfad wird kein abgeschlossener Trade irgendwo festgehalten (der Executor
schreibt Absichten, keine Ergebnisse), also können die Verlustgrenzen dort noch
nicht auslösen. Das ist die nächste Lücke, und sie liegt im Live-Pfad.

**Belegt, nicht behauptet.** Die Tests fragen den Trader, ob eine Position
entsteht — nie, ob `RiskLimits.check` False zurückgibt, denn genau das war immer
schon richtig. Nimmt man die neuen Prüfungen wieder heraus, fallen sechs von
sieben um; der siebte prüft, dass ein Konto *nicht* gesperrt wird (vom Verlust
eines anderen Marktes und von einer Verlustserie aus einem Backtest) und hält
darum bewusst in beide Richtungen. 1233 Tests grün, `ruff` und `mypy --strict`
sauber.

**Noch nicht wirksam auf diesem Rechner.** Die Änderung liegt auf dem Branch;
`papertrade.py` und `run_dashboard.py` laufen weiter mit dem alten Code im
Speicher. Erst nach Merge und Neustart stoppt der Kill-Switch das Papertrading —
und der Dashboard-Neustart will dann `--equity 1000`, sonst meldet er bewusst
kein Konto.

### 05.10.2026, spaet — die ADA-Hypothese gemessen und gefallen

Die Abstandsmerkmale sind nachgezogen (`learn/levels.py`): ein
Vorwaertsdurchgang statt eines quadratischen, moeglich durch eine Invariante —
ein Level ueber dem Kurs kann die Menge nur verlassen, indem der Kurs es
erreicht, denn ein Intervall laesst sich nicht ueberqueren ohne betreten zu
werden. **2,3 s fuer 175.537 Kerzen, 11.492 Zonen, 18.311 Luecken.**

**Mit 35 Merkmalen statt 28 ist die Antwort weiter nein.**

| Horizont | Richtung | alle Kerzen | gewaehlt | p |
|---|---|---|---|---|
| 5 h | kaufen | +0,0213 % | +0,0237 % | 0,516 |
| 5 h | verkaufen | −0,0213 % | −0,0232 % | 0,581 |
| 10 h | kaufen | +0,0441 % | +0,0495 % | 0,484 |
| 10 h | verkaufen | −0,0441 % | −0,0099 % | 0,258 |

Rangkorrelation **+0,0039** (5 h) und **+0,0045** (10 h) — mit den Abstaenden
eher schlechter als ohne. Der ueberzeugendste Beleg ist kein p-Wert: in beiden
Laeufen schloss genau *eine* von zehn Zehntel-Zeilen die Null aus, und sie
**wanderte** (5. Band ohne, 4. Band mit den Abstaenden). Ein echter Effekt
wandert nicht zwischen benachbarten Laeufen.

**Drei Struktur-Tatsachen, die das negative Ergebnis ueberleben:**

- **93 % aller Kerzen haben keine Zone in Reichweite** (Median 7,6 ATR hoch,
  7,3 tief). ADAs „125 unberuehrt, 0 in Reichweite" ist der *Normalzustand* —
  ein zonenbasierter Einstieg wartet strukturell, nicht gelegentlich. Das ist
  der echte Gehalt von Severins Beobachtung, und er stimmt, auch wenn er die
  Richtung nicht vorhersagt.
- Eine Fair-Value-Luecke auf M15 hat **Median-Lebensdauer 1 Kerze**, nur 0,8 %
  bleiben offen. Darum ist nie eine in Reichweite.
- Letzter Swing: Median 1,6 ATR — die einzige Level-Art, die meist nahe ist.

**Offen bleibt genau eines:** der Besetzungsschatten. Zwei Drittel aller Stunden
liegen hinter einem genommenen Signal, dort wird die Strategie nie gefragt und
das Protokoll hat keine Zeile. Die einzige verbliebene Stelle, an der etwas
Ungesehenes sein koennte — und sie ist gross.

**Bilanz des Tages: acht Hypothesen gemessen, acht gefallen.** Gebuehr,
Stopweite, Zieldeckel, Lernfilter, Trefferquote, Risikoregeln lockern,
Platzanzahl, 5-10h-Vorhersage in zwei Merkmalsfamilien. Jede war plausibel,
jede ist jetzt mit Zahlen tot statt mit Meinung offen. Ein System, mit dem wir
Geld machen, ist nicht gefunden. Die 15.000 bis 30.10. sind nicht erreichbar:
25 Tage, gemessene −0,034 R, physikalisches Maximum +2,15 R.

### Quellen- und Evidenztabelle (Auftrag KI-Recherche §10.1)

Trennung zwischen Originalaussage, eigener Ableitung und offenem Punkt. Keine
Vermoegensschaetzung aus den Quellen ist fuer unsere Arbeit relevant — sie
belegen, dass Firmen existieren, nicht dass eine Methode funktioniert.

| Quelle | Originalaussage | Unsere Ableitung | Offener Punkt |
|---|---|---|---|
| High-Flyer (Q1/Q2) | Machine Learning und Deep Learning im Quant-Handel ab 2016/17; Modelle zur Erkennung von Fehlbewertungen; Handel gegen irrational eingeschaetzte Schwankungen | Das ist Mean Reversion — eine Familie, die wir **nie geprueft** haben. Alle fuenf ausgelieferten Setups sind Fortsetzungslogik | Merkmale, Gewichte, Horizonte und Orderregeln sind **nicht** veroeffentlicht. Jeder Nachbau ist unsere Hypothese, nicht ihre Methode |
| Two Sigma (Q4) | Ridge bis Sprachverarbeitung; **unabhaengige** Prognosen zu einer Einschaetzung verbinden; Prozess gegen Ueberanpassung | Vor dem Kombinieren die **Fehlerkorrelation** messen. Angewandt auf unsere 35 Merkmale: effektiver Rang 21,4 von 33 — also nicht entartet | Welche Signale aktuell profitabel sind und wie sie gewichtet werden: nicht veroeffentlicht |
| Renaissance (Q8/Q9) | Mathematische und statistische Methoden; Simons systematisierte Devisenhandel | **Nichts handlungsleitend.** Keine offengelegte Regel | Die Originalregeln sind nicht offen. Keine selbstgebaute Strategie darf „Medallion" heissen |
| Forbes/WSJ (Q3,Q5-Q7,Q10) | Vermoegensschaetzungen; Medallion ~39 %/Jahr nach Gebuehren 1988-2018 | **Keine.** Eine Durchschnittsrendite einer geschlossenen Firma ist keine replizierbare Zinseszinsrate | Von mir **nicht geprueft**. Ich habe keine dieser Seiten abgerufen und zitiere keine Zahl als belegt |
| Dokument selbst §2/§30 | Die Recherche fand **keinen** ueberpruefbaren privaten Fall mit offenem System, der 1.000 auf 20.000 in sechs Monaten bringt | Das ist die ehrlichste Zeile der drei Auftraege und deckt sich mit unseren Messungen | Keiner — es ist eine Grenze der Recherche, kein Unmoeglichkeitsbeweis |

**Was daraus wirklich folgt, in einem Satz:** von drei Firmen ist genau eine
Aussage handlungsleitend — Two Sigmas Punkt, dass Prognosen *unabhaengig* sein
muessen, und High-Flyers Hinweis auf Fehlbewertung, also Mean Reversion. Beides
haben wir jetzt angewandt bzw. auf die Liste gesetzt.

**Merkmals-Unabhaengigkeit gemessen (9.981 BTC-Faelle):** effektiver Rang 21,4
von 33, 20 Hauptkomponenten fuer 90 % der Varianz, **2 konstante Merkmale**
(die Fair-Value-Luecken). Einundzwanzig unabhaengige Merkmale fanden eine
Rangkorrelation von 0,004 — haetten es drei sein koennen, waere Redundanz die
Erklaerung gewesen. Sie ist es nicht. Der negative Befund wird dadurch
staerker. Vier Merkmale sind allerdings dasselbe vierfach gemessen
(rsi <-> close_vs_ema_fast_atr +0,982), also bringt ein weiterer
Momentum-Oszillator einen Namen und keine Information.

### Sechsmonats-Bewertung mit gemessenen Auszahlungen (Auftrag Testplan §8)

`scripts/study_sixmonths.py`. Nicht die parametrische Annahme +2R/−1R des
Auftrags, sondern die **gemessene** Netto-R-Reihe aus 3.300 echten Trades über
vier Maerkte, in Bloecken neu gemischt (Blocklaenge 15, aus der eigenen
Autokorrelation). 20.000 Pfade je Risikostufe, 300 Trades je Pfad.

| Risiko | Median | 5 % | 95 % | Ziel 20k | unter 1k | ≥50 % weg | DD 95 % |
|---|---|---|---|---|---|---|---|
| 0,25 % | 972 | 871 | 1.090 | 0,00 % | 65,9 % | 0,0 % | 15,4 % |
| 0,50 % | 941 | 756 | 1.184 | 0,00 % | 66,7 % | 0,0 % | 28,6 % |
| 1,00 % | 875 | 565 | 1.384 | 0,00 % | 68,6 % | 1,9 % | 49,6 % |
| 2,00 % | 727 | 303 | 1.812 | 0,00 % | 71,9 % | 24,3 % | 75,5 % |
| 3,00 % | 574 | 155 | 2.247 | 0,01 % | 74,9 % | 43,1 % | 88,5 % |

**Das 20-fach-Ziel wird auf keiner Risikostufe erreicht.** Und die Tabelle
zeigt numerisch, was ich vorher nur behauptet habe: mehr Risiko verschiebt die
Verteilung nicht nach oben. Der Median fällt von 972 auf 574, das 95.
Perzentil steigt von 1.090 auf 2.247 — die Verteilung wird breiter, nicht
besser, und bei 3 % verlieren 43 % der Pfade mindestens die Haelfte.

**Die wichtigste Einzelzahl des Tages:**

| | |
|---|---|
| Mittlerer realisierter Gewinn | **+1,561 R** (geplant 2,15) |
| Mittlerer realisierter Verlust | **−1,038 R** (nominal 1,0) |
| Break-even-Trefferquote damit | **39,94 %** |
| Gemessen | **38,60 %** |
| **Luecke zum Nullpunkt** | **1,34 Prozentpunkte** |
| Luecke zum 20-fach-Ziel (3 % Risiko) | 54 % → 15,4 Punkte |

Der Auftrag warnt selbst: „Ein gesetzter Take-Profit von 2R bedeutet nicht,
dass die durchschnittlichen realisierten Gewinne 2R betragen." Mit unseren
Daten bestaetigt — 1,561 statt 2,0, und der Verlust ist groesser als 1 R wegen
Gebuehren, Funding und Luecken durch den Stop. Die Annahme ist auf **beiden**
Seiten optimistisch. Trotzdem sind die noetigen Gewinner fuer 20x fast
identisch zur Tabelle des Auftrags (162 von 300 bei 3 %), weil sich die beiden
Abweichungen im Zinseszins fast aufheben.

**Vorbehalt:** die 1,34 Punkte gelten nur bei gleichbleibenden
Auszahlungsgroessen — und genau das ist heute dreimal widerlegt worden. Der
Zieldeckel hob die Trefferquote auf 41,9 % und wurde pro Trade schlechter; der
Lernfilter hob sie auf 52 % und lag 0,069 R hinter den Regeln.

**Kostenannahme geprueft (Auftrag §3/§11):** unsere Gesamtkosten sind 0,1350 %
runde Fahrt (0,0750 % Gebuehr + 0,0600 % Slippage bei 3 bp je Seite) gegen die
0,1250 % des Auftrags. Wir sind also **konservativer**, um 0,0079 R pro Trade.
Meine erste Rechnung behauptete das Gegenteil, weil sie unsere reine Gebuehr
gegen ihre Gesamtkosten stellte.

**Datenlueck (Auftrag §9):** wir haben **kein Taker-Volumen**. Unsere Kerzen
sind (ts, open, high, low, close, volume); Binance liefert `taker_buy_volume`
im Archiv mit. `flow_imbalance` ist also nicht berechenbar, bis der Backfill
erweitert wird — eine Luecke, keine Unmoeglichkeit. Erfreulich: nichts in
unserem Code schaetzt Kaeufer aus Kerzenfarben, die Proxy-Warnung trifft uns
nicht.

### 05.10.2026, nachts — drei Familien erledigt, und das Muster dahinter

**Der eigentliche Befund des Tages**, sichtbar erst, als drei unabhaengige
Familien nebeneinander lagen:

| Familie | brutto pro Trade | Maut ist … |
|---|---|---|
| Gegenbewegung M15, 1 voraus | +0,0017 % | **79x so gross** |
| Fortsetzung (das heutige System) | +0,0172 % | 7,9x |
| Orderflow H1, alle Zellen | +0,0340 % | 4,0x |
| Orderflow H1, beste von 30 | +0,0790 % | 1,7x |
| Gegenbewegung H4, groesste 5 %, 32 h | +0,3750 % | 0,4x |

**Das Problem ist nicht, dass wir kein Signal finden. Jedes Signal, das auf
diesen Horizonten findbar ist, ist kleiner als die Maut** — um Faktor 2 bis 80.
Die einzige Zeile, in der es sich umkehrt, hat den **laengsten Horizont und die
groessten Bewegungen**.

**Mean Reversion: erledigt, und zwar mit unabhaengiger Bestaetigung.** Das
Preprint sagt ~1,3 bp brutto auf 15 Minuten; gemessen auf 700.890
Beobachtungen: **0,17 bp**. Dieselbe Groessenordnung, dasselbe Vorzeichen,
netto hoffnungslos gegen 13,5 bp runde Fahrt.

**Orderflow: erledigt.** 30 Zellen Bewegung x Fluss, Grenzen auf den ersten
60 % festgelegt. **Keine einzige Zelle mit positivem Netto.** Fortsetzung
(−0,1019 %) und Erschoepfung (−0,1291 %) trennen sich nicht. Die
Datenluecke ist dabei geschlossen: Taker-Volumen liegt jetzt in `data/flow/`,
62.012 BTC- und 60.102 ETH-Kerzen, keine Luecken.

**Zwei Selbstkorrekturen, beide in dieselbe Richtung:**

1. Imbalance korreliert +0,50 mit der Rendite ihrer **eigenen** Kerze. Keine
   Entdeckung, sondern Buchhaltung — Takerkaeufe sind, was den Kurs
   waehrenddessen bewegt. Als Befund gemeldet waere es die vierte
   Scheinfindung des Tages gewesen.
2. Ich schlug „Maker auf beiden Seiten" als ungepruefen Kostenhebel vor. **Er
   ist schon gezogen.** Einstiege sind Limit und zahlen Maker
   (`broker.py:323`), Zielausstiege ebenfalls — ein Gewinntrade kostet bereits
   0,100 %. Taker sitzt nur auf der Verlustseite, und ein Stop *muss*
   ausfuehren. Gemischte runde Fahrt: **0,1215 %**. **Die Kostenseite ist
   geschlossen.**

**Und ein stiller Datenfehler, gefunden weil ich einen Lueckenbericht gebaut
habe:** die Backfill-Fortsetzung geht nur vorwaerts. Mein 60-Tage-Transportlauf
liess BTCs Historie unerreichbar werden, und der naechste Lauf meldete „0 neu",
als waeren die Daten vollstaendig. Ohne den Bericht haette ich auf 1.439 Kerzen
gemessen und es fuer 2.584 Tage gehalten.

### Die Umsortierung der offenen Familien

Nicht nach Interessantheit, sondern nach **Groesse der Bewegung, die sie fangen
will** — das einzige Kriterium, das die Daten noch stuetzen. Ausdruecklich eine
Vorhersage, keine Messung:

| Familie | Aussicht |
|---|---|
| Volatilitaetsausbruch H4 | **laeuft** — einzige mit gemessen halbierter Maut (cost_r 0,0295 gegen 0,0593) |
| Handelsspannen-Ausbruch | plausibel, wenn auf D1/W1 |
| Trendfolge mit Ruecksetzer | plausibel, wenn Haltedauer lang |
| Regime-Umschaltung | aendert die Bewegungsgroesse nicht |
| Momentum mit Volumen | eher nicht — dasselbe Regal wie Orderflow |
| VWAP und Tageszeit | eher nicht — intraday, kleine Bewegungen |
| Funding / Relative Value | eher nicht — Basispunkte pro Abrechnung |

**Suchraum: 3 von 10 erledigt, 7 offen, 1 nicht testbar.** Register: 16 Arme,
**0 Konsultationen des Prueffensters** — unangetastet.


## 05.10.2026, Abend — Freqtrade als Ausfuehrungskern, und ein Audit gegen mich selbst

Zwei neue Auftragsdokumente. Das erste verlangt Freqtrade + FreqAI als Kern mit lokalem
MCP-Adapter; das zweite prueft meine eigenen Zahlen nach und hat in der Hauptsache recht.

### Was gebaut wurde

**Freqtrade 2026.9 nativ installiert**, eigener venv, Python 3.14.2. Kein Docker — Docker
Desktop ist eine Systemkomponente, die der Auftrag nicht blind anfassen laesst, und WSL2
Ubuntu 26.04 hat kein pip und ein passwortgesperrtes sudo. Es loest trotzdem vollstaendig
auf: TA-Lib, LightGBM, XGBoost, scikit-learn, scipy haben alle cp314-Wheels. Eine frueherere
Notiz von mir sagte das Gegenteil und war falsch.

**Der MCP-Adapter**: zwoelf Werkzeuge, vier korrekt als schreibend und eines als zerstoerend
gekennzeichnet. Kein Werkzeug kann eine Order platzieren — es existiert kein Codepfad dorthin.
Argumente werden gegen Positivlisten gepruefft, nicht gesaeubert; schwere Laeufe sind Jobs mit
Kennung, einer gleichzeitig, mit Dublettenschutz.

### Der unabhaengige Beweis des Kernbefunds

BaselineTrend auf Binance **Spot**, 2.425 Trades, 19 Monate, fremder Codebestand:

| | USDT |
|---|---|
| Brutto | **+171,02** |
| Gebuehren | **−969,08** |
| Netto | **−798,07** |

Positiver Bruttovorteil, Maut **5,7-mal groesser**. Dasselbe Ergebnis wie im eigenen Motor,
auf einer anderen Boerse, mit fremdem Code.

Und der Vergleich, den §6 verlangt: FreqaiCostFiltered macht in 45 Tagen **28 Trades** statt
2.425 und verliert 0,16 % statt 79,81 %, p-Wert 0,864. Der Kostenfilter hat keinen Vorteil
erzeugt — er hat aufgehoert, fuer dessen Abwesenheit zu zahlen.

### Wo ich falsch lag (audit/ZIELRECHNUNG.md)

**Die 56,6 % waren falsch.** Sie entstanden als Terminal-Einzeiler, wurden nie committet, und
setzten stillschweigend Gewinner von +1,371 R voraus. Symmetrisch braucht 20× **66,75 %**;
56,6 % erreicht **2,99×**, also 2.990 statt 20.000. Mit der *gemessenen* Auszahlung (Gewinner
+1,5612 R, Verlierer −1,0384 R) sind es **61,8 %**. Jetzt als `learn/target.py` mit 23 Tests.

**Die „50,0 % Treffsicherheit" sind nirgends gemessen.** Kein Code hier berechnet
`sign(Vorhersage) == sign(Bewegung)`. Die 0,004 ist eine Rangkorrelation; der Schritt zur
Prozentzahl war eine Umformulierung. Barrieren- und Vorzeichen-Labels widersprechen sich auf
**29–33 %** derselben Kerzen.

**Die Maker-Fuellungen sind nicht verdient.** 97,5 % aller Fills nehmen den Open-Zweig, und bei
96,2 % davon ist der Eroeffnungspreis identisch mit dem Limit, in der ersten Minute. Das ist
ein Markteinstieg, als ruhende Order abgerechnet. Taker-Einstieg: **−0,0340 R → −0,0615 R**.
Meine frueherere Korrektur „Maker ist schon gezogen, Kostenseite geschlossen" war falsch.

**Zwei gemessene Populationen, 0,058 R auseinander**, und ich habe die bessere berichtet:
3.300 gelabelte Signale ergeben −0,0340 R bei 38,64 %, die 2.740 tatsaechlich gebuchten
Broker-Trades ergeben **−0,0918 R bei 32,45 %**.

### Die Abdeckung, gezaehlt statt behauptet

Die „fuenf Jahre, 12 Maerkte" gelten fuer **4 von 12**. Und zwei Defekte: die Derivate-Dateien
beginnen 2021-10-01, waehrend `backfill_derivatives.py` laut eigenem Docstring erst ab Maerz
2023 liefern kann — Herkunft steht in keiner Datei. Funding mischt **zwei Boersen**: BTC/ETH/
SOL/XRP ab 2023-01-01 mit 11 Rasterabweichungen, die anderen acht ab 2020 mit je ~3.300.
BNBUSDT hat **49,6 % Funding-Raten von exakt null**.

### Die ungepruefte Achse, jetzt geprueft

Ich hatte laengere Horizonte als die vielversprechende Richtung genannt, weil eine Woche 51,2 %
verlangt und eine Stunde 70 %. Sechs angemeldete Konfigurationen, gepurgte Walk-forward-Folds,
Intervalle aus Wochenbloecken:

| Horizont | Modell | Richtung | 95 % | Basisquote |
|---|---|---|---|---|
| 24 h | logistic | 51,28 % | [49,35; 53,37] | 50,43 % |
| 72 h | logistic | 51,86 % | [49,41; 54,41] | **52,06 %** |
| 168 h | logistic | 49,61 % | [46,28; 52,90] | **51,63 %** |
| 24 h | lightgbm | 50,53 % | [48,90; 52,16] | 50,43 % |
| 72 h | lightgbm | 49,77 % | [47,67; 51,77] | **52,06 %** |
| 168 h | lightgbm | 51,93 % | [49,49; 54,36] | 51,63 % |

**Keine schlaegt ihre Basisquote**, und bei 72 h liegen beide Modelle unter „immer long". Die
Arithmetik war richtig, der Schluss nicht: eine niedrigere Huerde ist keine genommene Huerde.
Vierte Familie geschlossen.

### Was offen bleibt

Die Nicht-Preis-Merkmale — und die sind **gesperrt**, nicht offen: solange die Herkunft der
Derivate-Daten ungeklaert ist, waere jedes Ergebnis nicht deutbar. Die Sperre ist Code
(`learn/panel.py:check_provenance`), nicht ein Kommentar, und das Register zeigt sie als `[!]`.


## 05.10.2026, Abend — Sitzungsende, Stand zum Wiederaufnehmen

### Was laeuft NICHT mehr (sauber angehalten vor dem Herunterfahren)

- **Papierhaendler** gestoppt. Kapital **11.989,99 CHF** ueber 12 Konten, zwei Positionen
  offen (DOGEUSDT, ATOMUSDT) — stehen in `data/paper.sqlite` und laufen beim Neustart
  weiter. Vorwaerts-Protokoll: 7 Trades, Mittel −0,336 R.
  Neu starten: `python scripts/papertrade.py`
- **Zwoelf-Markt-Sammlung** angehalten nach **1 von 12** Maerkten. BTC fertig mit 2.539
  Signalen unter der neuen Signatur (Deckel 0.08). Fortschritt liegt in
  `data/signals.sqlite`, nichts geht verloren; die elf fehlenden Maerkte einfach
  nachholen.

### Die eine offene Frage, fuer die der Lauf da war

Brutto-Differenz zwischen guenstigen und teuren Trades: **+0,0799 R, Intervall
[−0,033; +0,195]**. Ist sie echt, ist das System bei Deckel 0.08 positiv. Ist sie null,
verliert es −0,015 R je Trade statt −0,054. Vier Maerkte konnten das nicht trennen,
zwoelf verdreifachen die Stichprobe.

### Was heute entschieden wurde

- **13 Strategiefamilien gemessen, null offen, keine positiv.** Register: 75 Arme,
  keiner mit einem Intervall ohne Null.
- **Fuenf mechanische Hebel gefallen**: Horizont, Einstiegspreis, Teilmengen-Auswahl,
  Derivate-Merkmale, On-Chain-Daten.
- **Sieben Fehlbefunde abgefangen**, drei davon selbst erzeugt — darunter ein ungepaarter
  Test, der eine von 24 Zellen faelschlich als Gewinn meldete, und eine
  `status-time`, die wie eine Verfuegbarkeitszeit aussah und eine Revalidierungszeit war.
- **Kostendeckel 0.15 → 0.08.** Konservativ gelesen von −0,054 R auf −0,015 R je Trade.
  Ein Drittel davon ist Arithmetik und unbestreitbar, zwei Drittel sind die offene Frage
  oben.
- **Die 56,6 % waren falsch** — sie setzten stillschweigend +1,371 R Gewinner voraus.
  Symmetrisch braucht 20× **66,75 %**, gemessen **61,8 %**. `learn/target.py`, 23 Tests.

### Reihenfolge beim Wiederaufnehmen

1. Papierhaendler starten (laeuft sonst nicht und sammelt keine Vorwaerts-Evidenz).
2. Die elf fehlenden Maerkte sammeln (~4 Stunden, ein Job, zwei Threads).
3. `study_costcap.py --with-refused` ueber alle zwoelf.
4. Ergebnis ins Register, Familie entsprechend schliessen oder oeffnen.

## 06.10.2026 — Code liegt jetzt auf GitHub

Erster Remote des Projekts: `origin` → `https://github.com/MaseSites/TraidingBrain.git`.
Alle drei Branches gepusht, Arbeitsbaum war clean:

- `freqtrade-core` — `5aa7e1c`, der aktuelle Stand (Upstream gesetzt)
- `master` — `1578860`
- `claude/amazing-raman-3ad84b` — `4cf7fb8`, die Risikosperren-Arbeit

**Was *nicht* mitgeht, und das ist Absicht.** `.gitignore` haelt den Laufzeitzustand
dieser Maschine draussen: `/data/`, `/runs/`, `*.parquet`, `*.sqlite`, die Freqtrade-
Marktdaten, Modelle, Logs und Backtest-Ausgaben, dazu `.env*` und
`freqtrade/user_data/config.local.json` (enthaelt JWT- und WebSocket-Schluessel).
Verfolgt sind 312 Dateien, 4,6 MB — Quellcode, Tests, Konfiguration, Research-Notizen.
Ein Scan der verfolgten Dateien nach Schluesselmustern fand nichts; `.env.example` ist
die einzige env-Datei im Index.

**Offener Punkt:** GitHubs Default-Branch zeigt auf `claude/amazing-raman-3ad84b`, weil
das Repo leer war und kein `main` existiert. Das sollte `freqtrade-core` sein — in den
Repo-Einstellungen auf GitHub umstellen (Settings → General → Default branch).
