# P0a — Legacy-Baseline, eingefroren

Erzeugt 2026-10-18T13:36:30Z aus Commit `490f300`.

## 0. Was dieses Dokument ist — und was nicht

Es friert den Zustand ein, auf dem alle bisherigen Messungen dieses
Projekts beruhen, **bevor** die Messmaschine korrigiert wird. Es ist
kein Ergebnisbericht und kein Beleg für eine Handelskante.

Die Legacy-Population heisst ab hier durchgehend:

> **Conditional simulated net R under the Legacy fill and fee model**

Sie ist ausdrücklich **nicht**: eine belegte Live-Kante, eine reine
Marktkante, ein gemeinsames Portfolioergebnis oder eine realisierte
Rendite.

Die Kurzbeschriftung des Laufs lautet:

> Legacy: Binance-Kerzen + DEFAULT_SPEC/Bybit-Regeln, getrennte
> Symbolkonten je 1.000, Platzdeckel 2, teilweise Bybit- bzw.
> fehlendes Funding.

## 1. Identität

| | |
|---|---|
| Commit | `490f3007eb4d59b1f4db232ec0a6e2c856f52d73` |
| Kurz | `490f300` — E16 ist gefallen -- und die Latte, an der gemessen wird, war selbst falsch |
| Branch | `freqtrade-core` |
| Arbeitsbaum sauber | False |
| `run_signature` | `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.08\|M15\|refused-v1\|portfolio\|cap5` |
| `decision_version` | `d8c7f12104e4` |

### Kommandozeilen der Arme

```
C:\Users\sever\OneDrive\Desktop\traidingBrain\.venv\Scripts\python.exe -u C:\Users\sever\OneDrive\Desktop\traidingBrain\scripts\compare_exits.py --cache C:\Users\sever\OneDrive\Desktop\traidingBrain\data\arms_0.jsonl --drop F --at 1 0.5 --target-cap 1 1.5 2 --symbol BTCUSDT --symbol ADAUSDT --symbol BNBUSDT
C:\Users\sever\OneDrive\Desktop\traidingBrain\.venv\Scripts\python.exe -u C:\Users\sever\OneDrive\Desktop\traidingBrain\scripts\compare_exits.py --cache C:\Users\sever\OneDrive\Desktop\traidingBrain\data\arms_1.jsonl --drop F --at 1 0.5 --target-cap 1 1.5 2 --symbol ETHUSDT --symbol AVAXUSDT --symbol LTCUSDT
C:\Users\sever\OneDrive\Desktop\traidingBrain\.venv\Scripts\python.exe -u C:\Users\sever\OneDrive\Desktop\traidingBrain\scripts\compare_exits.py --cache C:\Users\sever\OneDrive\Desktop\traidingBrain\data\arms_3.jsonl --drop F --at 1 0.5 --target-cap 1 1.5 2 --symbol XRPUSDT --symbol DOGEUSDT --symbol ATOMUSDT
```

| PID | Start (UTC) | CPU s | RSS MB |
|---|---|---|---|
| 53812 | 2026-10-16T04:58:57Z | 47,779 | 1220 |
| 54380 | 2026-10-16T04:58:57Z | 47,778 | 1207 |
| 64300 | 2026-10-16T04:58:57Z | 47,752 | 1174 |
| 55252 | 2026-10-16T04:58:57Z | 0 | 4 |
| 58636 | 2026-10-16T04:58:57Z | 0 | 4 |
| 59252 | 2026-10-16T04:58:57Z | 0 | 4 |

Die Prozesse mit 0.0 s CPU sind die `-u`-Starter, nicht die
Arbeiter. Erfasst, solange die Prozesse liefen; nach ihrem Ende
sind die Kommandozeilen nicht mehr abfragbar.

## 2. Umgebung

| Paket | Version |
|---|---|
| python | 3.14.2 |
| ccxt | 4.5.84 |
| pandas | 3.0.6 |
| numpy | 2.5.3 |
| pydantic | 2.13.5 |
| duckdb | 1.5.6 |
| pyarrow | 25.0.1 |
| fastapi | 0.141.1 |
| anthropic | 1.9.0 |
| scipy | 1.18.1 |
| sklearn | 1.9.1 |

## 3. Konfiguration, Kosten- und Fill-Modell

| Datei | SHA-256 | Bytes |
|---|---|---|
| `config/risk.yaml` | `d3b5032298855fde3cc0afcb9238deddd56104e7f64dedc68d54cdf0abbb16f3` | 20,012 |
| `config/settings.yaml` | `790ad0bbed4c03cda8ff4da3a7a76c3d18b914e5eefe3bafaa32b6916bfdcae8` | 11,727 |
| `config/weights.yaml` | `0332034e9288b150199625804804adacf86e513c608f7f9aaa85618b86ebb64c` | 1,744 |

### `DEFAULT_SPEC`

| Feld | Wert |
|---|---|
| `price_tick` | 0.1 |
| `qty_step` | 0.001 |
| `min_qty` | 0.001 |
| `min_notional` | 5.0 |
| `max_leverage` | 100.0 |
| `taker_fee` | 0.00055 |
| `maker_fee` | 0.0002 |
| `maintenance_margin_rate` | 0.005 |

**Herkunft:** domain/market.py:70 -- 'Bybit's USDT perpetual defaults'. Benutzt von compare_exits.py:182 (die Arme), evaluate.py:80, paper.py:93, challenge.py:182 -- auf BINANCE-Kerzen.

### Kostenmodell

| | |
|---|---|
| maker | 0.0002 |
| taker | 0.00055 |
| Slippage | 3.0 bps (auf den **Füllpreis**, nicht auf die Gebühr) |
| Kostendeckel | 0.08 des Risikos |
| **Kostenboden `d_min`** | **1.3125 %** |

### Fill-Modell

| | |
|---|---|
| `fill_on_touch` | False |
| `pessimistic_intrabar` | True |
| `entry_expiry_bars` | 32 |
| `einstieg_gebuehr` | broker.py:493 -- LIMIT => maker, ohne Kreuzungspruefung |
| `ausstieg_gebuehr` | broker.py:746 -- TARGET => maker, sonst taker |

## 4. Daten-Manifest

83 Verzeichnisse: 12 aktiv (gemessen), 56 ungesehen (kerzenbereit), 15 nur W1 (Median 0.0 MB, nicht analysierbar). Nutzbar: 68.

**Kerzen:** 2,589 Parquet-Dateien über 83 Märkte, 3.51 GB. Einzelhashes im Manifest.

**Funding:** 83 Reihen. Herkunftsfeld in der Datei: **False** — Spalten ['ts', 'rate'].

> Vier aktive Maerkte tragen je 4153 Zeilen und beginnen alle exakt am 2023-01-01 -- ein --since-Parameter, kein Venue-Merkmal. Die anderen acht beginnen an ihrem eigenen Listing-Datum 2020. Deckt sich mit dem Kommentar in data/venue.py, ist aber INFERENZ aus der Struktur und keine aufgezeichnete Tatsache.

| Markt | Zeilen | SHA-256 (gekürzt) |
|---|---|---|
| BTCUSDT | 4,159 | `a72d4b95b477257e` |
| ETHUSDT | 4,159 | `1bd5fb6bd2e8b022` |
| SOLUSDT | 4,159 | `42ffcafbca3ee13e` |
| XRPUSDT | 4,159 | `99c40cb38e2ecf5e` |
| ADAUSDT | 7,392 | `8640f907f38f85b1` |
| AVAXUSDT | 6,651 | `93460ee1215744d8` |
| LINKUSDT | 7,399 | `352406d3516dc13e` |
| DOGEUSDT | 6,874 | `b3a5c33dbbd018a8` |
| BNBUSDT | 7,327 | `32f37e4c00829da0` |
| LTCUSDT | 7,423 | `aea7585e1f5a6a05` |
| DOTUSDT | 6,751 | `b7d2d3ca7139c318` |
| ATOMUSDT | 7,338 | `1679945512001ab5` |

**Replay-Fills:**

| Markt | Fills | SHA-256 (gekürzt) | `decision_version` |
|---|---|---|---|
| ADAUSDT | 732 | `d8ea8375601cbe7f` | `e218664b39c8` |
| ATOMUSDT | 910 | `4b1ae941def51a14` | `e218664b39c8` |
| AVAXUSDT | 694 | `56d5ff5ff3e048d9` | `e218664b39c8` |
| BNBUSDT | 462 | `8cb574b34ce0e5e6` | `e218664b39c8` |
| BTCUSDT | 263 | `eae018a02c9d8c48` | `e218664b39c8` |
| DOGEUSDT | 667 | `8d586c30bd5f0b6e` | `e218664b39c8` |
| DOTUSDT | 654 | `ea75cf6b8b573b9a` | `e218664b39c8` |
| ETHUSDT | 389 | `310915b462c4cfed` | `e218664b39c8` |
| LINKUSDT | 802 | `cc18ee72b6aa266f` | `e218664b39c8` |
| LTCUSDT | 659 | `1cf7d698cb8afc7d` | `e218664b39c8` |
| SOLUSDT | 660 | `4fd45aabcb59d626` | `e218664b39c8` |
| XRPUSDT | 443 | `32840aa0f1ee0893` | `e218664b39c8` |

**Signalspeicher:** `data/signals.sqlite`, 67,964 Zeilen zum Aufnahmezeitpunkt, SHA-256 `4a0fc808e89d3ebe`.

> Diese Datei wird vom laufenden Papierhändler **weiter beschrieben**.
> Der Hash ist eine Momentaufnahme, kein Einfrieren. Die
> Legacy-Teilmenge wird über `run_signature` identifiziert.

| `run_signature` | Zeilen |
|---|---|
| `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.08\|M15\|refused-v1` | 48,035 |
| `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.15\|M15\|refused-v1` | 12,843 |
| `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.15\|M15\|refused-v1\|shadow` | 6,962 |
| `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.15\|M15\|refused-v1\|1200bars\|shadow` | 63 |
| `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.08\|M15\|refused-v1\|portfolio\|cap5` | 33 |
| `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.08\|M15\|refused-v1\|portfolio` | 28 |

## 5. Die Arme

84 von 84 (Regel, Markt)-Paaren.

| Regel | Märkte | fehlend |
|---|---|---|
| ohne (original) | 12/12 | — |
| ohne Setup F | 12/12 | — |
| Einstand bei 1 R | 12/12 | — |
| Einstand bei 0.5 R | 12/12 | — |
| Ziel gedeckelt bei 1 R | 12/12 | — |
| Ziel gedeckelt bei 1.5 R | 12/12 | — |
| Ziel gedeckelt bei 2 R | 12/12 | — |

| Datei | Zeilen | SHA-256 | letzte Änderung |
|---|---|---|---|
| `data/arms_0.jsonl` | 22 | `b23d914e7bd438b37f1b405c118663bc5d8741c898ed1cc3486718e34d873bb4` | 2026-10-18T13:31:11Z |
| `data/arms_1.jsonl` | 21 | `a3fbf4a1c549b370a8180075fa124c4400e5e59ae834008b829da7d572d6c320` | 2026-10-17T10:22:53Z |
| `data/arms_2.jsonl` | 21 | `2a5dc4af61e46856f42c9c547ec75947834474b1c0362e4abe4bdb594483b3b6` | 2026-10-17T09:53:18Z |
| `data/arms_3.jsonl` | 21 | `de36a615489e05719184fd0fe31b8a70e2e67aaa9041bc54d2859fb3062480e1` | 2026-10-17T10:20:29Z |
| `data/arms_4.jsonl` | 1 | `336af1684a1df4054ab0bdfc7f326a63ca1d5923056ee964408b6150301f9e1a` | 2026-10-15T08:52:14Z |
| `data/arms_5.jsonl` | 1 | `97e6a00f3bb4b254bc8ad1ee59b2a7430998d8a64cf07341bf410433903f5261` | 2026-10-15T08:52:14Z |
| `data/arms_6.jsonl` | 1 | `b5bbb101a1588efece432ade35f9a65c25a9652f07df8c7d2f3a5c4dfa785755` | 2026-10-15T08:52:14Z |

**Symbol-Aufteilung je Arm:**

- `arm_0`: BTCUSDT, ADAUSDT, BNBUSDT
- `arm_1`: ETHUSDT, AVAXUSDT, LTCUSDT
- `arm_2`: SOLUSDT, LINKUSDT, DOTUSDT
- `arm_3`: XRPUSDT, DOGEUSDT, ATOMUSDT

`data/arms_4.jsonl` bis `arms_6.jsonl` tragen je eine Zeile aus einer
früheren 7-fach-Aufteilung vom 15.10. Sie sind byte-identisch zu den
am 16.10. neu gerechneten Zeilen derselben (Regel, Markt)-Paare und
werden beim Zusammenführen über den Schlüssel dedupliziert.

## 6. Befunde

Jeder Befund trägt Behauptung, Quelle, gemessene Grösse, Auswirkung,
Schluss, verbleibende Unbekannte, Behebungsschritt und ein Etikett.

**34 Befunde** in 11 Gruppen: 28× BELEGT, 2× HYPOTHESE, 2× MODELLIERT, 2× BELEGT (in-sample)

### Integritaet von Entscheidung und Fill

#### 1. Der Primaerschluessel zwischen Signal und Fill existiert und traegt 98.91 % der Population, aber 80 Fills haengen daneben.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | sim/plan.py:303 (`proposal_id=f"{symbol}-{created_ts}"`), data/signals.sqlite, data/replay_fills/*.json |
| Gemessene Grösse | 7.335 Fills, 7.335 eindeutige proposal_id, 7.333 angenommene Signale. exact_match 7.255 (98.91 %), fill_without_signal 80, signal_without_fill 78, duplicate_candidate 0 auf beiden Seiten. |
| Auswirkung | Eine Verknuepfung ueber (Preis, Zeitfenster) statt ueber den Schluessel erreichte 97.49 % und ordnete dabei 78 Faelle FALSCH zu -- sie verdeckte den Signaturwiderspruch unten vollstaendig. |
| Schluss | Fuzzy-Matching darf nie Primaerschluessel sein. Der exakte Schluessel ist schwaecher als noetig (er unterscheidet weder Venue noch decision_version noch Setup), aber er ist eindeutig. |
| Verbleibende Unbekannte | Ob die 2 Fills ohne jede Signalzeile (80 minus 78) ein dritter Fehlertyp sind oder dieselbe Ursache mit fehlendem Nachbarn. |
| Behebung | P2c: decision_id als Content-Hash ueber venue, symbol, decided_ts, setup_key, setup_timeframe, side, entry, stop, target, run_signature, decision_version. Replay bricht ab, wenn exact_match != fills. |

#### 2. 78 Fills in der 0.08-Population haben ihre Signalzeile nur unter einer ANDEREN run_signature (0.15).

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/signals.sqlite gegen data/replay_fills/{BTCUSDT,ETHUSDT}.json |
| Gemessene Grösse | 80 fill_without_signal, davon 78 unter anderer Signatur bekannt. Verteilung: BTCUSDT 60, ETHUSDT 20. BTC-Signale unter der 0.08-Signatur enden am 2025-10-27, das Replay-Fenster laeuft bis 2026-10-01. |
| Auswirkung | Die Fill-Datei behauptet Kostendeckel 0.08, ihre Signale sagen 0.15. Fuer 78 Trades ist die Konfiguration, unter der sie entstanden, aus den Daten nicht eindeutig. |
| Schluss | Referenzintegritaet war nie geprueft. Counts stimmten zufaellig (7.333 gegen 7.335), die Zuordnung nicht. |
| Verbleibende Unbekannte | Ob die betroffenen Fills unter 0.08 oder 0.15 gerechnet wurden. Ohne das ist ihre Zugehoerigkeit zur Population offen. |
| Behebung | P2c, und bis dahin: diese 78 Trades in jeder Auswertung der Legacy-Population als nicht signatur-belegt markieren. |

#### 3. data/signals.sqlite ist eine LEBENDE Datei; ihr Hash friert nichts ein.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/signals.sqlite, zwei Messungen im Abstand von 2 h |
| Gemessene Grösse | 67.942 Zeilen -> 67.945 Zeilen, der Papierhaendler schreibt weiter. |
| Auswirkung | Ein Dateihash in diesem Manifest ist eine Momentaufnahme mit Zeitstempel, kein Einfrieren. |
| Schluss | Die Legacy-relevante Teilmenge wird ueber run_signature identifiziert, nicht ueber den Dateihash. |
| Verbleibende Unbekannte | - |
| Behebung | P0a speichert zusaetzlich Zeilenzahl je run_signature zum Aufnahmezeitpunkt; spaeter eigene Datei je Lauf. |

#### 4. Die Arme rechnen unter einem anderen Codestand als die replay_fills -- und reproduzieren die Basis trotzdem exakt.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | decision_version der Arme gegen data/replay_fills/*.json |
| Gemessene Grösse | Arme: d8c7f12104e4. replay_fills: e218664b39c8 (alle zwoelf Dateien, eine Signatur, ein Stempel). Basis-Arm: 7.335 Trades, -94.78 R -- identisch zur Replay-Population. Zusaetzlich: drei Basis-Zeilen vom 15.10. sind byte-identisch zu den am 16.10. neu gerechneten (SHA-256 der Trade-Liste). |
| Auswirkung | Die Codeaenderungen zwischen den beiden Staenden haben den Entscheidungspfad nicht veraendert. |
| Schluss | Der Replay-Pfad ist ueber diese Aenderungen hinweg reproduzierbar. Das ist ein Determinismus-Beleg, kein Richtigkeits-Beleg. |
| Verbleibende Unbekannte | - |
| Behebung | Kein Handlungsbedarf; der Stempel gehoert kuenftig in die Cache-Zeile selbst (heute traegt sie nur rule, symbol, trades). |

### Portfolioeffekt

#### 1. Die Legacy-Population ist KEIN Portfolio, sondern zwoelf unabhaengige Einzelmarkt-Konten.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/replay_fills/BTCUSDT.json: summary 'BTCUSDT / guide-all', 'return -8.5% (1,000 -> 915)', eigener max drawdown 27.1 %; run_signature ohne \|cap-Zusatz; journal/version.py:65 CAP_ANCHOR = 2 |
| Gemessene Grösse | 12 Konten x 1.000 Startkapital, je eigener Platzdeckel 2. Gesamtes Legacy-Startkapital 12.000, nicht 1.000. |
| Auswirkung | Der gepoolte Mittelwert -0.0129 R ist der Mittelwert ueber zwoelf getrennte Konten. Er ist weder die Kante eines gemeinsamen Portfolios noch die Population, die ein 1.000-CHF-Konto gehandelt haette. |
| Schluss | Jede Aussage ueber das Zielkonto braucht den gemeinsamen Portfoliomotor. Legacy kann sie nicht liefern. |
| Verbleibende Unbekannte | Die tatsaechlich angenommene Trade-Zahl, die Blockierwahrscheinlichkeit, der Portfolio-Drawdown und die Margin-Auslastung eines gemeinsamen Kontos. |
| Behebung | P3: gemeinsamer chronologischer Portfoliomotor. |

#### 2. Im Replay hat der Platzdeckel NIE abgelehnt.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/signals.sqlite, Filter run_signature = "1000.0\|['A', 'B', 'E', 'F', 'G']\|0.08\|M15\|refused-v1" UND source = 'replay' |
| Gemessene Grösse | 47.918 Signale: kosten 22.942, chance_risiko 17.623, angenommen 7.333, liquidation 20, grenzen 0. Der source-Filter ist noetig: ohne ihn liegen unter derselben Signatur 117 zusaetzliche live-Zeilen (48.035 gesamt, kosten 23.003, chance_risiko 17.663, angenommen 7.349). `grenzen` kommt als Wert in dieser Menge ueberhaupt nicht vor. |
| Auswirkung | Die angenommene Menge ist exakt die wirtschaftlich tragfaehige. Ein gemeinsames 5-Platz-Konto nimmt daraus weniger. |
| Schluss | Es gibt keine aufgezeichnete Menge 'wegen Besetzung verworfen'. Eine Rekonstruktion aus den vorhandenen Fills kann deshalb nur eine Teilmenge auswaehlen und ist keine Gegenfaktualsimulation. |
| Verbleibende Unbekannte | Wie viele Signale bei besetztem Symbol gar nicht erst bewertet wurden. Siehe naechster Befund. |
| Behebung | P3: OCCUPIED-Kandidaten im Motor erneut pruefen. |

#### 3. Die durch Besetzung verdeckte Signalmenge ist etwa 2.7-mal so gross wie die sichtbare -- gemessen an EINEM Markt und einer anderen Kostendeckel-Stufe.

**Etikett:** `HYPOTHESE`

| | |
|---|---|
| Quelle | data/signals.sqlite, run_signature '...\|0.15\|M15\|refused-v1\|shadow' gegen '...\|0.15\|M15\|refused-v1' |
| Gemessene Grösse | BTCUSDT Schatten: 6.962 Signale, 1.485 angenommen. BTCUSDT Basis: 2.861 Signale, 555 angenommen. Verhaeltnis 2.68x. Uebertragen auf die 7.333 der 0.08-Population: Groessenordnung 19.600 Kandidaten. |
| Auswirkung | Die Behauptung 'ein gemeinsames Konto kann nur eine Teilmenge der 7.335 nehmen' ist damit widerlegt: faellt ein frueherer Trade weg, ruecken Kandidaten nach, deren Ausgang nirgends existiert. |
| Schluss | Eine Auswahl aus vorhandenen Fills ist eine Diagnose, keine Wahrheit. |
| Verbleibende Unbekannte | Das Verhaeltnis fuer die 0.08-Population und fuer die anderen elf Maerkte. Ein Markt und eine andere Kostenstufe sind keine Messung der gesuchten Groesse. |
| Behebung | P3: Schattensignale im gemeinsamen Motor mitfuehren und ihre Ausgaenge aus M1 simulieren. |

#### 4. Gleichzeitige Signale sind haeufig, uebersteigen fuenf Plaetze aber fast nie.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/signals.sqlite, angenommene Signale je decided_ts |
| Gemessene Grösse | 5.988 verschiedene decided_ts. Davon 990 (16.5 %) mit mehr als einem gleichzeitigen Signal; Verteilung 1:4.998, 2:731, 3:191, 4:49, 5:12, 6:5, 7:2. Nur 7 Zeitpunkte ueber fuenf. |
| Auswirkung | Die Arbitrationsregel wird an 990 Zeitpunkten gebraucht, entscheidet aber nicht die Hauptmenge. Die Knappheit entsteht durch Belegung aus frueheren Trades (mittlere Haltedauer 33.0 h), nicht durch gleichzeitige Ankunft. |
| Schluss | Eine deterministische Batch-Arbitration ist noetig, ihre Wahl duerfte das Ergebnis aber wenig bewegen. Das ist zu messen, nicht anzunehmen. |
| Verbleibende Unbekannte | Untergrenze: gezaehlt sind nur Signale, die in zwoelf getrennten Konten angenommen wurden. Die Schattenmenge fehlt. |
| Behebung | P3: Batch je decided_ts, neutrale Ordnung ueber stabilen Hash aus (run_signature, decided_ts, symbol, setup_key), Seed im Manifest, Sensitivitaet ueber vorregistrierte Seeds. |

#### 5. Ein arbeitender Auftrag belegt einen Platz, aber nur 0.13 % der Platzstunden.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/signals.sqlite (decided_ts) gegen replay_fills (opened_ts, closed_ts); config/settings.yaml entry_expiry_bars=32 auf M15 |
| Gemessene Grösse | 7.255 gefuellte Auftraege mit bekanntem decided_ts. 6.817 (94.0 %) fuellen sofort (0.00 h). Median 0.000 h, Mittel 0.044 h, max 7.93 h bei einer Frist von 8.0 h. Pending gesamt 318.8 Platzstunden gegen 242.085.3 Haltestunden = +0.13 %. Abgelaufene Auftraege: 78 ueber zwoelf Maerkte, nur als Zaehlung. |
| Auswirkung | Die Blockierung durch wartende Auftraege ist real, aber klein. Abgelaufene Auftraege kaemen bei voller Frist auf hoechstens 624 Platzstunden = 0.26 %. |
| Schluss | PendingEntry gehoert modelliert -- nicht wegen der 0.39 %, sondern weil 94 % Sofortfuellung eine Eigenschaft der Replay-Fuellregel ist und live anders aussehen kann. |
| Verbleibende Unbekannte | expires_ts ist nirgends gespeichert. Es muesste aus der versionierten TTL erschlossen und als 'inferred' markiert werden. |
| Behebung | P3: PendingEntry mit Zustaenden submitted/filled/expired/cancelled/closed, Platz und Margin ab submitted_ts. |

### Identitaet des Laufs

#### 1. Die Arme laufen unter einer ANDEREN run_signature als die replay_fills -- und reproduzieren die Basis trotzdem exakt. Der Grund ist mechanisch, nicht zufaellig.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | scripts/compare_exits.py:169-186 (load_config, load_engine, engine.run); config/risk.yaml max_positions_per_symbol: 1; data/replay_fills/*.json run_signature |
| Gemessene Grösse | Arme: '...\|0.08\|M15\|refused-v1\|portfolio\|cap5', Stempel d8c7f12104e4. replay_fills: '...\|0.08\|M15\|refused-v1', Stempel e218664b39c8. Basis-Arm dennoch 7.335 Trades, -94.78 R -- identisch. |
| Auswirkung | Zwei Unterschiede, beide folgenlos fuer R. Erstens die Groessenbemessung: `portfolio` gegen flache 10 USDT aendert risk_amount und qty, aber R ist groessen-invariant (net_r = (gefangene Bewegung - Gebuehr)/Stop-Anteil). Zweitens der Platzdeckel: in einem EINZELMARKT-Lauf bindet max_positions_per_symbol = 1 zuerst, also kann der Portfolio-Deckel (2 oder 5) nie greifen. Bestaetigt durch grenzen = 0 in allen 47.918 Replay-Signalen. |
| Schluss | Die Signatur der Arme ueberzeichnet den Unterschied. Fuer die Legacy-Population ist der Lauf aequivalent -- aber nur, weil beide Unterschiede in einem Einzelmarkt-Lauf wirkungslos sind. In einem gemeinsamen Portfolio waeren sie es NICHT. |
| Verbleibende Unbekannte | - |
| Behebung | P2c: der Stempel gehoert in die Cache-Zeile (heute nur rule, symbol, trades). P3: im gemeinsamen Motor binden beide. |

### Venue-Reinheit

#### 1. Es gibt einen Pfad, auf dem Binance-Daten einen Bybit-Trade bepreisen und bestaetigen.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | config/settings.yaml (exchange.name = binance); execution/order.py:91 (venue_name: str = 'bybit' als Vorgabe); scripts/run_dashboard.py:144 und scripts/run_live.py:230 (BybitExecutor ohne venue_name); api/app.py:813 (_price_drift liest services.prices) |
| Gemessene Grösse | Kerzen, Analyse, Entry/Stop/Ziel und die Driftpruefung (15 bps) kommen von BINANCE. Instrumentregeln (Tick, min_qty, MMR, max_leverage) und die Order selbst gehen an BYBIT. |
| Auswirkung | Derzeit schlafend: das Dashboard laeuft ohne --execute, kein Executor ist scharf. Bybit-TESTNET-Schluessel sind in .env hinterlegt und konfiguriert. Mit --execute waere der Pfad aktiv. |
| Schluss | --execute darf bis P1 nicht benutzt werden. Ein blosses venue_name=config.engine.exchange.name waere falsch -- es ergaebe einen Binance-Executor mit Bybit-Zugangsdaten. |
| Verbleibende Unbekannte | - |
| Behebung | P1: Hard-Fail auf analysis_venue == price_check_venue == instrument_spec_venue == sizing_spec_venue == fee_schedule == execution_venue; Venue als Pflichtargument; Venue in Proposal-Fingerprint, run_signature und Intent. |

#### 2. Die Legacy-Messungen rechnen Binance-Kerzen mit Bybit-Gebuehren.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | domain/market.py:70 -- Kommentar woertlich „Bybit's USDT perpetual defaults, and the fees are the part that matters“; benutzt von scripts/compare_exits.py:182 (den Armen), evaluate.py:80, paper.py:93, challenge.py:182 |
| Gemessene Grösse | DEFAULT_SPEC: maker 0.00020, taker 0.00055, maintenance_margin_rate 0.005, max_leverage 100, min_notional 5.0, qty_step 0.001, price_tick 0.1. Unabhaengig geprueft: Bybit VIP 0 ist 0.020 %/0.055 %, Binance Standard 0.020 %/0.050 %. |
| Auswirkung | Kostenboden 1.3125 % statt 1.2500 %. Direkte Wirkung auf die 7.335 Fills: +0.001473 R je Trade (korrigiert [+0.001413, +0.001532]), Summe +10.81 R, Mittel -0.0129 -> -0.0114 R. Zusaetzlich 493 Signale, die den Deckel neu passieren wuerden. |
| Schluss | Nicht nur die Gebuehr ist venue-fremd: price_tick, qty_step, min_qty, min_notional, max_leverage und maintenance_margin_rate sind ebenfalls generisch und boersenspezifisch. |
| Verbleibende Unbekannte | Die Wirkung der 493 neu zugelassenen Signale. Sie haben keinen Ausgang in den Daten, und ihre cost_fraction (0.0800-0.0840] liegt OBERHALB des teuersten vorhandenen Fuenftels (max 0.0800). |
| Behebung | P2: venue-reine, versionierte VenueSpecSnapshots je Symbol. |

#### 3. Vier der zwoelf Maerkte tragen vermutlich Bybit-Funding auf Binance-Kerzen -- und die Dateien sagen es nicht.

**Etikett:** `HYPOTHESE`

| | |
|---|---|
| Quelle | data/funding/*.parquet (Spalten nur ts, rate); data/venue.py Kommentar |
| Gemessene Grösse | BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT: je 4.153 Zeilen, alle beginnend exakt 2023-01-01. Die anderen acht: 6.645-7.417 Zeilen, je eigenes Listing-Datum 2020. Alle im 8-h-Takt, keine Luecken. Diese vier sind 1.755 von 7.335 Trades = 23.9 % der Population. |
| Auswirkung | Ein identisches Startdatum fuer genau vier Maerkte ist ein --since-Parameter, kein Venue-Merkmal. Die Zuordnung deckt sich mit dem Kommentar, ist aber INFERENZ aus der Struktur. |
| Schluss | Herkunft gehoert als Feld in die Datei, nicht in einen Kommentar. Ein falscher Kommentar hat in diesem Projekt schon einmal eine Forschungsachse fuer einen Tag blockiert. |
| Verbleibende Unbekannte | Die tatsaechliche Herkunft jeder Reihe. Ohne Feld ist sie nicht belegbar, nur plausibel. |
| Behebung | P2b: Binance-Funding fuer die vier vollstaendig nachladen; Herkunftsfeld je Reihe; Hard-Fail bei candle_venue != funding_venue. |

#### 4. 96 Trades tragen Funding = 0, weil es dort keine Reihe gibt -- nicht weil keines anfiel.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/replay_fills/{BTC,ETH,SOL,XRP}USDT.json gegen data/funding/*.parquet |
| Gemessene Grösse | 96 Trades vor 2023-01-01 in den vier Maerkten (BTC 12, ETH 13, SOL 47, XRP 24), davon 94 mit funding = 0.0. Mittleres Funding dieser vier nach 2023: +0.00355 R (n=1.659). Unterstellte Verzerrung: 96 x 0.00355 = +0.341 R von -94.78 R (0.36 %). |
| Auswirkung | Zahlenmaessig unwesentlich. Als Muster erheblich: fehlende Daten werden als „keine Kosten“ gelesen. |
| Schluss | Fehlend und null sind verschiedene Zustaende und muessen es bleiben. |
| Verbleibende Unbekannte | - |
| Behebung | P2: fehlende Abdeckung ist ein expliziter Status; entweder vollstaendige venue-passende Abdeckung oder harter Abbruch. |

### Lebende Dateien unter einer eingefrorenen Baseline

#### 1. data/funding/ wird vom laufenden Papierhaendler weiter geschrieben. Die Hashes in diesem Manifest sind Momentaufnahmen.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | scripts/papertrade.py:248 top_up_funding(); data/funding/*.parquet mtime; unabhaengige Nachpruefung |
| Gemessene Grösse | Alle zwoelf Funding-Dateien wurden am 2026-10-17 um 09:58:59-09:59:02Z neu geschrieben. KEINER der zwoelf SHA-256 aus der ersten Belegsammlung (16.10.) stimmte danach noch; BTCUSDT ec322d51... -> e86bfdf0.... Zeilenzahl je Markt +3 pro Tag (drei Abrechnungen im 8-h-Takt). Ebenso signals.sqlite: 67.945 -> 67.961 Zeilen. |
| Auswirkung | Die Legacy-Population ist NICHT betroffen: alle 39 seit dem Replay-Ende angehaengten Zeilen liegen nach 2026-10-04 11:45Z, dem spaetesten Replay-Zeitpunkt. Geprueft fuer BTCUSDT und ADAUSDT; die ersten Zeitstempel sind unveraendert. |
| Schluss | Ein Hash friert nur ein, was niemand schreibt. Das Manifest muss unmittelbar vor dem Einfrieren erzeugt werden, und lebende Verzeichnisse muessen als solche benannt sein. |
| Verbleibende Unbekannte | - |
| Behebung | P2: Daten je Lauf in ein unveraenderliches, versioniertes Verzeichnis kopieren statt ein gemeinsames zu lesen, das ein Live-Prozess fortschreibt. |

#### 2. Der Funding-Speicher ist ein UPSERT, kein Append -- historische Saetze koennten stillschweigend ueberschrieben werden.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/funding.py:78-82 (`drop_duplicates(subset='ts', keep='last')`, Eingehendes wird HINTER Bestehendes gehaengt); scripts/papertrade.py:273 (`since = (last + 1) if last else now - FUNDING_DAYS * DAY_MS`) |
| Gemessene Grösse | Der Speicher erlaubt die Revision jedes ts. Der einzige Aufrufer im Live-Pfad fragt aber ausschliesslich ts > last ab, also wird kein bestehender Zeitstempel je neu geholt. FUNDING_DAYS = 7 gilt nur beim allerersten Befuellen. |
| Auswirkung | Faktisch append-only -- aber durch Aufruferdisziplin in EINER Zeile, nicht durch den Vertrag des Speichers. Ein zweiter Aufrufer mit anderem `since` wuerde Geschichte revidieren, ohne dass es irgendwo auffaellt. |
| Schluss | Fuer eine Point-in-time-Garantie reicht das nicht. Der Master-Auftrag verlangt sie ausdruecklich (D3: keine spaeter revidierten Daten ohne Point-in-time-Version). |
| Verbleibende Unbekannte | Ob die Boerse je einen bereits abgerechneten Satz korrigiert. Das waere der Fall, in dem der Upsert gebraucht WIRD -- dann muessten beide Fassungen erhalten bleiben. |
| Behebung | P2: Revisionen als neue Version speichern statt an Ort und Stelle; `first_seen_ts` und `revision_ts` je Zeile. |

### Execution Feasibility

#### 1. Der Simulator nimmt Maker-Einstieg und Maker-Target an; der Executor erzwingt beides nicht.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | sim/broker.py:493 (LIMIT => maker, ohne Kreuzungspruefung), sim/broker.py:746 (TARGET => maker); execution/order.py:265 (create_order mit timeInForce GTC, ohne PostOnly; takeProfit ohne tpslMode/tpOrderType/tpLimitPrice; stopLoss ohne slOrderType) |
| Gemessene Grösse | Obere Schranke (Einstieg und Ausgang beide Taker) auf den identischen 7.335 Fills: -0.021979 R je Trade, korrigiert 99.932 % [-0.022488, -0.021477], Summe -161.21 R, Mittel -0.0129 -> -0.0349 R. Einzeln: nur TP wird Market -0.005835 R (nur die 2.684 Target-Ausgaenge, je -0.015948 R); nur Einstieg crosst -0.016143 R. |
| Auswirkung | Die obere Schranke ist 1.7-mal groesser als die gesamte gemessene Erwartung von -0.0129 R. Die Ausfuehrungs-Semantik ist damit ein groesserer Posten als alles, was E14 bis E17 untersuchen. |
| Schluss | Legacy-Zahlen sind Kosten des SIMULATORS, nicht des Executors. Bezeichnung durchgehend „Legacy Simulator-Kostenmodell“. |
| Verbleibende Unbekannte | Wie oft ein GTC-Einstieg tatsaechlich Maker wird. Das ist eine Eigenschaft des Buches zum Absendezeitpunkt und aus Kerzen nicht bestimmbar. |
| Behebung | P1: ExecutionPolicy je Venue. Policy A (alles Taker) als kostenkonservative Baseline; Policy B erst nach bestaetigter Liquidity Role. |

#### 2. Der Simulator hat diese Abweichung selbst aufgeschrieben, als er sie einbaute.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | sim/broker.py:741-745 |
| Gemessene Grösse | Woertlich: „It is also a constraint on the live side, not only a model change. It is only true if the executor places a resting limit at the target. A take-profit-market order ... crosses the spread and pays taker -- and then this line would be quietly optimistic about every winner.“ Derselbe Kommentar beziffert den Vorteil mit 0.0092 R je Trade ueber 1.862 Trades. |
| Auswirkung | Ein notierter, nie durchgesetzter Vertrag. Zwei Dateien, die zusammengehoeren, und niemand hat sie verbunden. |
| Schluss | Ein Kommentar ist keine Durchsetzung. Was als Vertrag gemeint ist, braucht einen Test. |
| Verbleibende Unbekannte | - |
| Behebung | P1-Test: Simulator und Executor muessen dieselbe deklarierte ExecutionPolicy verwenden; unbekannte Policy bricht vor Tokenvergabe ab. |

#### 3. Ein realistischer Kostenboden wuerde ein Drittel der Population nicht zulassen -- und es waere das schlechtere Drittel.

**Etikett:** `MODELLIERT`

| | |
|---|---|
| Quelle | Rechnung auf data/replay_fills/*.json, c = taker+taker+slippage = 0.00140, Deckel 0.08 |
| Gemessene Grösse | d_min 1.75 % statt 1.3125 %. 2.529 von 7.335 Fills (34.5 %) liegen darunter; nach Zeitebene M15 1.575, H1 751, H4 192, D1 11. Deren R-Mittel -0.0287 gegen -0.0046 beim Rest. Je Pool: 'nur A auf D1+H4' verliert 157 von 876 (17.9 %) und geht von +0.0856 auf +0.0728 R; der Gesamtpool von -0.0129 auf -0.0214 R. |
| Auswirkung | Zwei grosse Effekte in entgegengesetzter Richtung: Taker-Kosten verschlechtern dieselben Trades um Faktor 1.7, der strengere Boden entfernt aber die schlechteren. |
| Schluss | Der Nettoeffekt ist ohne Motorlauf unbekannt, weil wegfallende Trades Plaetze freigeben. Obere Zeitebenen sind strukturell weniger betroffen (breitere Stops, kleinere Kostenanteile). |
| Verbleibende Unbekannte | Der Nettoeffekt. Und ob 1.75 % ueberhaupt die richtige Zahl ist -- sie ist eine Schranke, keine gemessene Live-Kostenquote. |
| Behebung | P4: neue Baseline unter deklarierter ExecutionPolicy. |

### Fill-Wahrscheinlichkeit

#### 1. Die Fill-Wahrscheinlichkeit ist aus historischen Daten nicht beweisbar, auch nicht mit L1 und Trade-Tape.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | config/settings.yaml fill_on_touch: false; frueher gemessene Orderbuch-Reihe; data/flow/ |
| Gemessene Grösse | Bis zu 49 % ruhender Auftraege verschwinden je 17 Sekunden unerreicht; 1.000 USD Notional uebersteigen die gesamte XRP-Touch. Vorhandene Mikrostrukturdaten: data/flow/ mit ZWEI Dateien (BTCUSDT-H1, ETHUSDT-H1), 3.5 MB, Spalten ts, volume, taker_buy, trades -- H1-Aggregate, kein best bid, kein best ask, kein Quote-Zeitstempel. |
| Auswirkung | fill_on_touch: false ist eine konservative Fill-Proxy, kein Fill-Beweis. Ein Trade-Tape belegt, dass am Preis gehandelt wurde, nicht dass unsere Order an der Reihe war. |
| Schluss | Ohne Queue-Position bleibt jedes Fill-Modell eine Annaeherung. Die staerkste Evidenz waeren eigene Order- und Execution-Daten. |
| Verbleibende Unbekannte | Ob ein PostOnly-Einstieg gefuellt worden waere, wann in der Queue, wie viel vor ihm stand, ob vor Expiry, und welche Adverse Selection passive Fills erzeugen. |
| Behebung | D0: venue-nativer Collector mit L1/L2, Sequenznummern und Receive-Timestamps. Spaeter Mainnet-Kleinstorders -- nur nach ausdruecklicher Freigabe. |

### Gebuehren und Slippage

#### 1. Das Gebuehrenmodell des Simulators ist exakt rekonstruiert.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | sim/broker.py:493, 746; data/replay_fills/*.json |
| Gemessene Grösse | fees = Einstiegs-Notional * maker + Ausstiegs-Notional * (maker wenn reason == target, sonst taker). Reproduziert alle 7.335 gespeicherten Gebuehren, groesster Fehler 0.0e+00. Ausgaenge: stop 4.648, target 2.684, manual 3. |
| Auswirkung | Jede Gebuehren-Sensitivitaet auf fester Population ist damit exakt rechenbar, ohne Motorlauf. |
| Schluss | Das Modell ist geprueft, nicht unterstellt -- Voraussetzung dafuer, dass die Sensitivitaet unten ueberhaupt zaehlt. |
| Verbleibende Unbekannte | - |
| Behebung | - |

#### 2. Die Slippage steckt im Fuellpreis, nicht in der Gebuehr -- gross_market_r und modeled_execution_cost_r sind aus Legacy NICHT trennbar.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/replay_fills/*.json: fees/Notional = 0.000762 ~ maker+taker, ohne die 3 bps; config/settings.yaml slippage_bps: 3.0 |
| Gemessene Grösse | Je Fill gespeichert: gross_pnl, fees, funding, net_pnl, risk_amount. gross_pnl ist die Preisbewegung NACH Slippage. |
| Auswirkung | Von den sechs geforderten Feldern sind aus Legacy herstellbar: funding_r (mit Vorbehalt) und conditional_simulated_net_r. NICHT herstellbar: gross_market_r sauber, modeled_execution_cost_r vollstaendig, realized_live_net_r, fill_rate/fill_uncertainty. |
| Schluss | Der unverschlechterte Referenzpreis muss im neuen Motor ZUSAETZLICH gespeichert werden, sonst bleibt die Zerlegung auch kuenftig unmoeglich. |
| Verbleibende Unbekannte | Der Slippage-Anteil je Legacy-Trade. Er wird nicht geschaetzt. |
| Behebung | P3: Referenzpreis, modellierter Fillpreis, tatsaechlicher Fillpreis und Kostenbestandteile einzeln speichern. |

#### 3. Die Gebuehrenkorrektur schliesst 0.3 % der gesuchten Luecke.

**Etikett:** `MODELLIERT`

| | |
|---|---|
| Quelle | Sensitivitaet auf data/replay_fills/*.json |
| Gemessene Grösse | Binance Standard (2.0/5.0 bps): +0.001473 R je Trade, korrigiert [+0.001413, +0.001532], Null ausgeschlossen. Binance mit hypothetischem BNB-Rabatt (1.8/4.5 bps): +0.004202 R, [+0.004077, +0.004322]. Target-Ausgaenge gewinnen unter Binance Standard exakt +0.000000 R, weil Maker unveraendert bleibt. Gesuchte Kante: +0.49 bis +0.75 R. |
| Auswirkung | Beide Effekte sind real und reproduzierbar und beide sind drei Groessenordnungen zu klein. |
| Schluss | Gebuehren sind nicht der Hebel. Sie sind eine Korrektur der Beschriftung, kein Weg zum Ziel. |
| Verbleibende Unbekannte | Das BNB-Szenario ist HYPOTHETISCH. Es wurden keine Kontodaten gelesen und kein Rabatt als aktiv unterstellt. |
| Behebung | P2: tatsaechliche Rate des Zielkontos bestaetigen und als versionierte Annahme speichern. |

### Messapparat

#### 1. Der Apparat loest bei zwoelf Maerkten 0.0774 R auf. Kleinere Effekte sind nicht entscheidbar, egal wie lange gerechnet wird.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | reporting/intervals.py (Blockbootstrap), Skalierung 1/sqrt(n) |
| Gemessene Grösse | Halbbreite bei 73 Vergleichen: 12 Maerkte (7.335 Trades) 0.0774 R; 59 Maerkte (36.064) 0.0349 R; 83 Maerkte (50.734) 0.0294 R. Um +0.0061 R aufzuloesen braeuchte es das 160-fache: 1.175.000 Trades, etwa 1.922 Maerkte. |
| Auswirkung | E16 (+0.0061 R) war nie entscheidbar. Die Zielkante (+0.42 bis +0.75 R) liegt dagegen weit ueber der Grenze. |
| Schluss | Rechenzeit nur fuer Arme, deren plausible Wirkung ueber der Grenze liegt. Als Ablehnungsregel im Register eingetragen. |
| Verbleibende Unbekannte | - |
| Behebung | - |

#### 2. Die Bonferroni-Korrektur ist NICHT der Engpass.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | reporting/intervals.py, Halbbreite je Vergleichszahl |
| Gemessene Grösse | 1 Vergleich 0.0463 R; 20 -> 0.0673 (+45 %); 67 -> 0.0772; 73 -> 0.0774; 74 -> 0.0777 (+0.4 %); 150 -> 0.0825 (+6.6 %). |
| Auswirkung | Eine Zelle anzumelden kostet 0.4 %. Auch unkorrigiert waere die Halbbreite 0.0463 R und E16 fiele. |
| Schluss | Das Argument „die Korrektur ist zu streng“ ist erledigt. Der Engpass ist die Streuung je Trade. |
| Verbleibende Unbekannte | - |
| Behebung | - |

#### 3. Die Takt-Obergrenze rechnete mit dem Median statt dem Mittelwert -- Little verlangt den Mittelwert.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | scripts/goal.py (vorher np.median, Docstring sagte „mittlere Haltedauer“); jetzt learn/target.py:sustainable_rate; tests/test_sustainable_rate.py |
| Gemessene Grösse | Replay: Mittel 33.0 h gegen Median 6.7 h, Faktor 4.9. Live entschieden: 28 Abschluesse in 13.04 Tagen = 2.15/Tag; Haltedauer Median 9.8 h, Mittel 19.6 h; Deckel ueberwiegend 2. Aus dem Mittel 2.45/Tag (12 % daneben), aus dem Median 4.90/Tag (128 % zu hoch). |
| Auswirkung | Obergrenze 17.9 -> 3.64 Trades/Tag. Chancen bis zur Frist 269 -> 51. Noetige Kante +0.081 -> +0.42 R. Saettigung bei 11 statt 53 Maerkten -- die zwoelf laufenden sind bereits gesaettigt. |
| Schluss | Mehrere Schlussfolgerungen standen auf der falschen Zahl. Wenn Code und eigener Docstring sich widersprechen, ist das ein Defektbericht, und der Live-Verlauf ist der Schiedsrichter. |
| Verbleibende Unbekannte | Der Vorwaerts-Durchsatz der laufenden cap5-Epoche. Sie hat erst zwei Abschluesse; die 2.15/Tag mischen vier Epochen. |
| Behebung | Erledigt in learn/target.py. Durchsatz kuenftig je Era berichten. |

#### 4. Von 83 Marktverzeichnissen sind nur 68 analysierbar.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/ohlcv/, data/unseen_markets.txt, data/universe/binance_um_perps.json |
| Gemessene Grösse | 83 Verzeichnisse: 12 aktiv (Median 70.2 MB), 56 ungesehen (Median 50.0 MB), 15 in keiner der beiden Listen. Von diesen 15 tragen 14 NUR W1 (ICP, IOTX, KSM, MANA, MASK, ONE, RSR, RVN, SAND, SFP, SUSHI, TRB, UNI, ZEN; bei UNIUSDT sechs Dateien mit 13-53 Wochenkerzen). Das fuenfzehnte, KNCUSDT, hat D1 (1.838 Kerzen), H4 (11.031) und W1 (262), zusammen 431 kB -- aber kein H1, M15 oder M1. Alle 83 stehen in der Universe-Tabelle auf TRADING. |
| Auswirkung | Eine frueher berichtete Hochrechnung auf 83 Maerkte war um 22 % zu gross. Korrigiert auf 68. |
| Schluss | Handelbar und analysierbar sind verschiedene Mengen. Ein Verzeichnis sind keine Kerzen -- und „nur W1“ war fuer eines der 15 falsch: die Restkategorie hat 15 Mitglieder, das Etikett trifft auf 14 zu. Die Folgerung „nutzbar 68“ bleibt, weil KNCUSDT die Ausfuehrungsebene M15/M1 fehlt. |
| Verbleibende Unbekannte | Ob die 15 nachgeladen werden sollen. Das ist eine Entscheidung, keine Messung. |
| Behebung | P2: Datenabdeckung je Markt und Ebene explizit, mit Status statt mit Anwesenheit eines Verzeichnisses. |

### Signal- und Marktausgang (in-sample)

#### 1. Setup A hat einen geordneten Verlauf ueber alle vier Zeitebenen, bei fester Auszahlung.

**Etikett:** `BELEGT (in-sample)`

| | |
|---|---|
| Quelle | data/replay_fills/*.json nach fills.setup und fills.timeframe |
| Gemessene Grösse | A auf D1: n=172, 47.1 % Treffer, +1.487/-1.028, Schwelle 40.9 %, +0.1565 R. H4: n=704, 44.2 %, +1.478/-1.048, 41.5 %, +0.0682 R. H1: n=1.309, 41.0 %, 41.6 %, -0.0147 R. M15: n=1.344, 38.5 %, 41.6 %, -0.0774 R. Die Zerlegung p*Gewinner + (1-p)*Verlierer reproduziert den Mittelwert ueber alle 20 Zellen auf 2.8e-16 R. |
| Auswirkung | Nur A traegt den Verlauf. B ist nicht geordnet (D1 -0.5042 bei 31 Trades ist seine schlechteste Zelle), G ist umgekehrt (H1 +0.1845 am besten), E hat auf D1 fuenf Trades. |
| Schluss | Bei fester Auszahlung ist die Kante exakt eine Quotenfrage. Die uebliche Warnung vor der Trefferquote gilt hier NICHT -- und nur deshalb. |
| Verbleibende Unbekannte | Ob der Verlauf ausserhalb dieser zwoelf Maerkte haelt. Er wurde IN ihnen gefunden. |
| Behebung | P5: Pruefung auf den 56 ungesehenen Maerkten. |

#### 2. Der beste Kandidat liegt bei +0.0856 R -- und reicht nicht.

**Etikett:** `BELEGT (in-sample)`

| | |
|---|---|
| Quelle | data/replay_fills/*.json, Pool-Bildung nach Setup/Ebene |
| Gemessene Grösse | nur A auf D1+H4: n=876, +0.0856 R, 11.9 % der Signale. A+B auf D1+H4: n=1.112, +0.0701 R. alles ohne M15: n=3.718, +0.0121 R. Basis: n=7.335, -0.0129 R. Benoetigt fuer 20x in 183 Tagen bei 1 % Risiko und 3.64 Trades/Tag: +0.454 R; bei 3 % Risiko: +0.151 R, dann aber nur 1 Platz (floor(5 %/3 %)) und damit +1.268 R. |
| Auswirkung | Der beste Pool ist 5.7- bis 8.8-fach zu klein, je nach Deckelannahme. Unter Taker-Kosten faellt er auf +0.0669 R, auf der nach dem strengeren Boden verbleibenden Menge +0.0728 R. |
| Schluss | Es gibt in der Legacy-Population keinen Pool, der das Ziel erreicht. Der Abstand ist nicht durch Gebuehren, Hebel oder Kapitalauslastung zu schliessen. |
| Verbleibende Unbekannte | Ob +0.0856 R out-of-sample ueberlebt. In-sample und nach Betrachtung der Tabelle ausgewaehlt. |
| Behebung | P5 nach P4, auf sauberer Messmaschine. |

#### 3. E16 ist gelaufen und gefallen: Setup F abzuschalten ist nicht belegt.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | audit/EXPERIMENTS_NEXT.yaml E16; data/arms_*.jsonl |
| Gemessene Grösse | ohne (original) n=7.335 -0.0129 R [-0.067, +0.040], -94.78 R. ohne Setup F n=7.331 -0.0068 R [-0.062, +0.047], -49.88 R. Differenz +0.0061 R [-0.070, +0.082] -- Null eingeschlossen. Replikation +0.86x. Population aendert sich um 3.6 %: 7.200 identisch, 135 entfallen, 131 neu. |
| Auswirkung | Tor 1 haelt nicht, F bleibt an. Die Vorab-Schaetzung (-0.0060 R) traf auf 0.0008 R. Der Platz-Effekt ist doppelt so gross wie F's eigene Trade-Zahl (68). |
| Schluss | R total halbiert sich (+44.91 R), war aber vorab als berichtete Nebenkennzahl verlangt und ist kein Tor. Mal n ist auch das noch Rauschen. |
| Verbleibende Unbekannte | - |
| Behebung | - |

### Ergebnisse der Legacy-Arme

#### 1. E14 (Einstand-Stop) ist gefallen -- und macht das Ergebnis MONOTON schlechter, je frueher der Stop nachgezogen wird.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/arms_alle.jsonl (84 Paare, 12 Maerkte); scripts/compare_exits.py --only-report; Niveau 99.932 % (73 angemeldete Vergleiche, Bonferroni) |
| Gemessene Grösse | Basis n=7.335 -0.0129 R. Einstand bei 1 R: n=8.414, -0.0147 R, Differenz -0.0018 R [-0.069, +0.066], Replikation -2.56x (frueh +0.0023, spaet -0.0060). Einstand bei 0.5 R: n=9.736, -0.0308 R, Differenz -0.0178 R [-0.080, +0.045], Replikation +4.27x (frueh -0.0068, spaet -0.0289). Beide Tore verfehlt. |
| Auswirkung | Der Einstand-Stop TUT, was er soll: der Anteil der Trades unter -1 R faellt von 60.3 % auf 47.5 % (bei 1 R) und auf 31.5 % (bei 0.5 R), und die Regel feuert oft (43.9 % von 4.166 scharfen Trades bei 1 R, 72.4 % von 6.561 bei 0.5 R). Das Ergebnis wird trotzdem schlechter, und zwar umso mehr, je strenger die Regel. |
| Schluss | Die geretteten Vollverluste werden von abgeschnittenen Gewinnern mehr als aufgewogen. Der Rueckgabe-Befund (Durchschnittstrade erreicht +1.1840 R, endet bei -0.0129 R) gibt diesem Hebel nicht nach -- er verschaerft ihn. |
| Verbleibende Unbekannte | Ob ein Einstand-Stop mit Mindestabstand oder zeitlicher Verzoegerung anders ausfaellt. NICHT gerechnet: das waere eine neue Zelle und zaehlt als neuer Vergleich. |
| Behebung | Kein Handelsparameter wird geaendert. E14 ist geschlossen. |

#### 2. E15 (Ziel-Deckel) ist in allen drei Zellen gefallen; die beste scheitert an der Replikation, nicht am Vorzeichen.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | wie E14 |
| Gemessene Grösse | Ziel bei 1 R: n=9.528, -0.0052 R, Differenz +0.0077 R [-0.057, +0.071], Replikation +0.06x (frueh +0.0146, spaet +0.0009). Ziel bei 1.5 R: n=8.175, -0.0168 R, Differenz -0.0038 R [-0.075, +0.067], Replikation -1.77x. Ziel bei 2 R: n=7.566, -0.0075 R, Differenz +0.0054 R [-0.069, +0.078], Replikation -0.29x. |
| Auswirkung | Der Deckel bei 1 R ist der beste Arm des ganzen Satzes (-0.0052 R gegen -0.0129 R der Basis, +0.0077 R Differenz). Sein Intervall spannt die Null UND seine Replikation liegt bei 0.06x, also weit ausserhalb des vorab festgelegten Bandes 0.5-2.0x: frueh +0.0146 R, spaet +0.0009 R. Der Effekt verschwindet in der zweiten Haelfte. |
| Schluss | Zwei Tore, zwei unabhaengige Gruende zu verwerfen. Der Fall, fuer den das Replikationstor geschrieben wurde: ein plausibler positiver Punktwert, der nur in einer Haelfte existiert. |
| Verbleibende Unbekannte | - |
| Behebung | Kein Handelsparameter wird geaendert. E15 ist geschlossen. |

#### 3. SECHS von sechs Armen gefallen, und kein einziges Intervall verlaesst die Null -- in keiner Richtung.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/arms_alle.jsonl, vollstaendiger Bericht |
| Gemessene Grösse | Differenzen und korrigierte Intervalle: ohne F +0.0061 [-0.070, +0.082]; Einstand 1 R -0.0018 [-0.069, +0.066]; Einstand 0.5 R -0.0178 [-0.080, +0.045]; Ziel 1 R +0.0077 [-0.057, +0.071]; Ziel 1.5 R -0.0038 [-0.075, +0.067]; Ziel 2 R +0.0054 [-0.069, +0.078]. Alle sechs Halbbreiten liegen zwischen 0.060 und 0.064 R; alle sechs Punktwerte zwischen -0.018 und +0.008 R. |
| Auswirkung | Die gemessenen Effekte sind um den Faktor 4 bis 35 kleiner als die Auflosungsgrenze dieses Apparats. Das ist kein knappes Scheitern, sondern ein Satz von Messungen, der nie haette entscheiden koennen. |
| Schluss | Der Ausstiegs-Mechanismus ist auf dieser Population kein Hebel. Gleichzeitig bestaetigt der Satz die Ablehnungsregel, die nach E16 eingetragen wurde: Rechenzeit nur fuer Arme, deren plausible Wirkung ueber 0.0774 R liegt. Nach dieser Regel haetten E14 und E15 nicht gerechnet werden duerfen -- die Regel entstand aber erst, als sie schon liefen. |
| Verbleibende Unbekannte | Ob ein grosser Effekt auf einer Teilmenge steckt (etwa nur Setup A auf D1+H4). NICHT gerechnet: eine Teilmenge nach Betrachtung zu waehlen waere Auswahl. |
| Behebung | P4: neue Baseline. Danach duerfen Ausstiegsregeln nur noch mit vorab begruendeter Wirkungsgroesse ueber der Auflosungsgrenze angemeldet werden. |

#### 4. Alle Regeln erzeugen MEHR Trades als die Basis -- der Platz-Effekt ist in jedem Arm sichtbar.

**Etikett:** `BELEGT`

| | |
|---|---|
| Quelle | data/arms_alle.jsonl, Trade-Zahlen je Arm |
| Gemessene Grösse | Basis 7.335. ohne F 7.331. Einstand 1 R 8.414 (+14.7 %), Einstand 0.5 R 9.736 (+32.7 %), Ziel 1 R 9.528 (+29.9 %), Ziel 1.5 R 8.175 (+11.5 %), Ziel 2 R 7.566 (+3.1 %). |
| Auswirkung | Ein frueher beendeter Trade gibt den Platz frei, also entstehen mehr Trades. Verglichen werden damit nicht dieselben Trades mit anderen Ausstiegen, sondern zwei verschiedene Mengen -- darum ungepaart gerechnet. |
| Schluss | Selbst in EINZELMARKT-Laeufen mit nur einem Platz je Symbol ist der Effekt bis zu 33 %. In einem gemeinsamen Portfolio mit fuenf geteilten Plaetzen waere er groesser und wuerde ausserdem zwischen den Maerkten wirken. |
| Verbleibende Unbekannte | Die Groesse im gemeinsamen Portfolio. Legacy kann sie nicht zeigen. |
| Behebung | P3. |

## 7. Der Armbericht, woertlich

```
Nur Bericht: 84 Paare, 12 M�rkte aus arms_alle.jsonl

Niveau 99.932%  (73 angemeldete Vergleiche, Bonferroni)

  ohne (original)        n= 7335  -0.0129 R  [-0.067, +0.040] (Block 19, n=7335)
                         unter -1R 60.3%  schlimmster -1.89 R  5%-Quantil -1.08 R  abgeschnitten n/a (Regel aus)

  ohne Setup F           n= 7331  -0.0068 R  [-0.062, +0.047] (Block 19, n=7331)
                         unter -1R 60.2%  schlimmster -1.89 R  5%-Quantil -1.08 R  abgeschnitten n/a (Regel aus)
                         Differenz +0.0061 R  [-0.070, +0.082] (Block 19, n=7331)
                         Replikation +0.86x  (fr�h +0.0066, sp�t +0.0056)
                         -> gefallen (Intervall nein, Replikation ja)

  Einstand bei 1 R       n= 8414  -0.0147 R  [-0.057, +0.026] (Block 20, n=8414)
                         unter -1R 47.5%  schlimmster -1.89 R  5%-Quantil -1.07 R  abgeschnitten 43.9% von 4166 scharfen
                         Differenz -0.0018 R  [-0.069, +0.066] (Block 20, n=7335)
                         Replikation -2.56x  (fr�h +0.0023, sp�t -0.0060)
                         -> gefallen (Intervall nein, Replikation nein)

  Einstand bei 0.5 R     n= 9736  -0.0308 R  [-0.063, +0.002] (Block 21, n=9736)
                         unter -1R 31.5%  schlimmster -1.89 R  5%-Quantil -1.07 R  abgeschnitten 72.4% von 6561 scharfen
                         Differenz -0.0178 R  [-0.080, +0.045] (Block 21, n=7335)
                         Replikation +4.27x  (fr�h -0.0068, sp�t -0.0289)
                         -> gefallen (Intervall nein, Replikation nein)

  Ziel gedeckelt bei 1 R n= 9528  -0.0052 R  [-0.041, +0.029] (Block 21, n=9528)
                         unter -1R 47.1%  schlimmster -1.89 R  5%-Quantil -1.07 R  abgeschnitten n/a (Regel aus)
                         Differenz +0.0077 R  [-0.057, +0.071] (Block 21, n=7335)
                         Replikation +0.06x  (fr�h +0.0146, sp�t +0.0009)
                         -> gefallen (Intervall nein, Replikation nein)

  Ziel gedeckelt bei 1.5 R n= 8175  -0.0168 R  [-0.062, +0.030] (Block 20, n=8175)
                         unter -1R 56.9%  schlimmster -1.89 R  5%-Quantil -1.08 R  abgeschnitten n/a (Regel aus)
                         Differenz -0.0038 R  [-0.075, +0.067] (Block 20, n=7335)
                         Replikation -1.77x  (fr�h +0.0100, sp�t -0.0177)
                         -> gefallen (Intervall nein, Replikation nein)

  Ziel gedeckelt bei 2 R n= 7566  -0.0075 R  [-0.059, +0.045] (Block 20, n=7566)
                         unter -1R 59.4%  schlimmster -1.89 R  5%-Quantil -1.08 R  abgeschnitten n/a (Regel aus)
                         Differenz +0.0054 R  [-0.069, +0.078] (Block 20, n=7335)
                         Replikation -0.29x  (fr�h +0.0153, sp�t -0.0044)
                         -> gefallen (Intervall nein, Replikation nein)

Die Trade-Zahlen unterscheiden sich, weil ein fr�her beendeter Trade den n�chsten
Einstieg freigibt. Verglichen werden damit nicht dieselben Trades mit anderen
Ausstiegen, sondern zwei verschiedene Mengen -- darum ungepaart.
```

## 8. Was aus dieser Baseline nicht folgt

- Keine Aussage über ein gemeinsames 1.000-CHF-Konto. Die Population
  sind zwölf getrennte Konten.
- Keine Aussage über Live-Ausführungskosten. Das Kostenmodell ist das
  des Simulators, und der Executor erfüllt seine Maker-Annahmen nicht.
- Keine Aussage über Fill-Wahrscheinlichkeit. `fill_on_touch: false`
  ist eine konservative Proxy, kein Beweis.
- Keine saubere Trennung von Marktausgang und Ausführungskosten. Die
  Slippage steckt im Füllpreis.
- Keine out-of-sample-Aussage. Alle Kanten wurden in denselben zwölf
  Märkten gefunden, in denen sie gemessen wurden.

## 9. Reihenfolge danach

| | |
|---|---|
| P1 | Venue- und Execution-Policy, fail-closed |
| P2 | venue-reine Spec-, Fee- und Funding-Snapshots |
| P2b | Binance-Funding für BTC/ETH/SOL/XRP nachladen |
| P2c | `decision_id` und Referenzintegrität |
| D0 | venue-nativer öffentlicher Collector |
| P3 | gemeinsamer chronologischer Portfoliomotor |
| P4 | neue 1.000-USDT-Baseline |
| D1–D3 | Orderflow, kostenbewusste Abstention, Regimefilter |
| P5 | ungesehene Märkte und Stabilität |
| P6 | (f,H)-Frontier und Shadow-Konto |

