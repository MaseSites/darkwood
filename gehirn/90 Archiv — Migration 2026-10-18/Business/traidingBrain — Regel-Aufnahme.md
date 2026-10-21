---
typ: projekt-detail
projekt: traidingBrain
status: quellenbasis-enzyklopaedisch
naechster_schritt: Die enzyklopaedische TRADING_ANALYSE_GRUNDLAGEN.md gegen die heutigen Analyzer-Felder mappen und zuerst Datenvertrag, Marktmechanik sowie fehlende reine Beobachtungsobjekte priorisieren.
aktualisiert: 2026-09-30
---

# traidingBrain — Regel-Aufnahme

Severin schickt seine Handelsregeln. Damit daraus direkt Konfiguration wird und
nicht eine Rueckfragerunde, steht hier jede Frage, die beantwortet sein muss —
mit dem Ort, an dem die Antwort landet, und dem Wert, der heute dort steht.

**Wie das zu lesen ist.** Was unter „steht heute auf" nicht bei deinem Wunsch
steht, ist eine Zeile in einer YAML-Datei. Was mit **(muss gebaut werden)**
markiert ist, existiert noch nicht — das ist kein Nein, sondern eine Ansage ueber
Aufwand, damit du weisst, was sofort geht und was einen Tag kostet.

Nichts muss vollstaendig sein. Was offen bleibt, behaelt den heutigen Wert.

---

## 1 — Was gehandelt wird

| Frage | Steht heute auf | Wo es landet |
|---|---|---|
| Welche Maerkte? | nur `BTCUSDT` | `settings.yaml` → `symbols.active` |
| ETH, SOL, XRP dazu? | vorbereitet, nicht aktiv | dieselbe Zeile |
| Spot oder Perpetuals mit Hebel? | Perpetuals (linear, USDT) | `settings.yaml` → `exchange.market_type` |

Die Engine ist seit dem ersten Tag mehrsymbolfaehig. Dass nur BTC aktiv ist, ist
eine Entscheidung, keine Grenze: **die Walk-Forward-Auswertung war auf ETH und
SOL deutlich besser als auf BTC** (5 von 6 Fenstern gegen den Zufall; BTC hatte
zu wenige Trades). Wenn du keinen Grund dagegen nennst, wuerde ich ETH und SOL
dazunehmen.

---

## 2 — Auf welcher Zeitebene du denkst

| Frage | Steht heute auf | Wo es landet |
|---|---|---|
| Welche Kerze ist dein Takt? | H1 — eine Stunde | `settings.yaml` → `timeframes.signal` |
| Welche Ebenen schaut das System mit an? | W1, D1, H4, H1, M15 | `timeframes.context` |
| Feintiming auf M15 oder M5? | M15 | dieselbe Liste; **M5 muss gebaut werden** (Daten waeren da, Ebene ist nicht konfiguriert) |

Wichtig fuer deine Antwort: „ich schaue auf den 15-Minuten-Chart" und „ich handle
den 15-Minuten-Chart" sind zwei verschiedene Saetze. Der Takt bestimmt, wie oft
ueberhaupt gefragt wird — auf M15 sind das viermal so viele Bars wie auf H1, und
damit viermal so viele Modellaufrufe.

---

## 3 — Wann ein Setup ueberhaupt eines ist

Das ist das Tor. Es entscheidet nicht, ob ein Trade gut ist — es entscheidet,
welche Bars das Modell ueberhaupt anschaut. Auf dem Dashboard siehst du es jetzt
durchgehend: jede Bedingung, ihr Stand, und die Zahl dahinter.

| Frage | Steht heute auf | Wo es landet |
|---|---|---|
| Muss die Struktur gebrochen sein (BOS/CHoCH)? | **ja** | `settings.yaml` → `trigger.require_bos_or_choch` |
| Muss Liquiditaet geholt worden sein (Sweep)? | nein | `trigger.require_sweep` |
| Wie viele Indikatoren muessen Stellung beziehen? | 2 | `trigger.min_indicator_confluence` |
| Mindestabstand zwischen zwei Anfragen? | 4 Bars | `trigger.min_bars_between_calls` |
| Nur in bestimmten Sitzungen handeln? | alle erlaubt | `trigger.allowed_sessions` |
| Gar nicht handeln, wenn kein Desk besetzt ist? | nein | `trigger.require_active_session` |
| Sperre um wichtige Termine? | aus | `trigger.news_blackout_minutes` |

**Was das System an Mustern selbst erkennt** — steht dein Muster hier, ist es
eine Konfigurationszeile; steht es nicht hier, muss es gebaut werden:

- Swing Highs und Lows, und die Folge daraus (HH HL LH LL)
- Break of Structure, Change of Character
- Equal Highs, Equal Lows
- Sweeps (Liquiditaet geholt und abgelehnt), beide Seiten
- Fair Value Gaps (oben, Mitte, unten)
- Range-Hoch und Range-Tief
- Vortageshoch und -tief, Vorwochenhoch und -tief
- Regime: Trend, Range, Manipulation — plus Volatilitaets-Bucket

**Nicht erkannt, muss gebaut werden:** Order Blocks, Breaker, Kerzenmuster
(Engulfing, Pin Bar, Doji), Chartformationen (Schulter-Kopf-Schulter, Dreiecke,
Flaggen), Volumenprofil und POC, gleitende Durchschnitte als Unterstuetzung,
Fibonacci-Retracements.

Die Indikatoren, die gerechnet werden: RSI, EMA schnell und langsam, MACD, ATR,
Bollinger, Volumen-Durchschnitt, sowie die Lage im Tagesbereich.

---

## 4 — Wo der Stop hingehoert

| Frage | Steht heute auf | Wo es landet |
|---|---|---|
| Stop hinter welches Level? | das Modell waehlt ein benanntes Level, Python rechnet den Preis | fest verdrahtet, bewusst |
| Fester ATR-Abstand stattdessen? | nein | **muss gebaut werden** |
| Mindestabstand des Stops? | indirekt ueber die Kostenregel | `risk.yaml` → `max_cost_fraction_of_risk` |
| Stop nachziehen (Trailing)? | nein | **muss gebaut werden** |
| Teilverkauf bei 1R? | nein | **muss gebaut werden** |

Die Kostenregel ist die wichtigste Zeile dieser Tabelle und die unscheinbarste.
Positionsgroesse ist Risiko geteilt durch Stop-Abstand — ein enger Stop kauft also
eine **grosse** Position, und Gebuehren haengen an der Position, nicht am Risiko.
Bei einem Stop 0,18 % vom Einstieg kostet ein Hin und Zurueck 42 % dessen, was du
riskierst. Das holt keine Trefferquote wieder rein. Heute duerfen Kosten
hoechstens **15 %** des Risikobudgets fressen.

---

## 5 — Wie viel Geld

Der Punkt, den fast alle verwechseln, und der Geld kostet:

**Einsatz ist nicht Risiko.** 5 000 CHF Position mit 3 % Stop-Abstand verliert
150 CHF, nicht 5 000. Du kannst also genau das haben, was du wolltest — grosse
Position bei starker Lesart — ohne dass ein Trade das Konto zerlegt.

| Frage | Steht heute auf | Wo es landet |
|---|---|---|
| Kontogroesse? | 10 000 CHF (Testnet) | `risk.yaml` |
| Risiko pro Trade: Prozent oder fester Betrag? | **Prozent** | `risk.yaml` → `sizing.tiers`; **fester CHF-Betrag muss gebaut werden** |
| Wie viel pro Trade? | 0,5 % bis 3 %, nach Zuversicht gestaffelt | `sizing.tiers` |
| Hartes Maximum? | 3 % | `sizing.absolute_max_risk_pct` |
| Maximaler Hebel? | 10× | `leverage.max` |
| Maximaler Tagesverlust? | 5 % | `limits.max_daily_loss_pct` |
| Maximaler Wochenverlust? | 10 % | `limits.max_weekly_loss_pct` |
| Gleichzeitig offene Positionen? | 2 | `limits.max_open_positions` |
| Pause nach Verlustserie? | nach 3 Verlusten, 24 h | `limits.cooldown_after_consecutive_losses` |
| Mindest-Chance-Risiko-Verhaeltnis? | 1,5 | `limits.min_reward_risk` |
| Maximale Anzahl Trades pro Tag? | — | **muss gebaut werden** |

**Eine Sperre, die bleibt, bis Daten sie aufheben.** Die Stufen ueber **1 %** sind
gekappt. Die Zuversichtszahl des Modells ist am Anfang keine Wahrscheinlichkeit,
sondern eine Einschaetzung — und eine unkalibrierte Zahl darf nicht ueber Geld
entscheiden. Erst wenn 200 nicht ueberlappende Faelle zeigen, dass Setups mit
hoher Zuversicht wirklich besser laufen, geht der Deckel hoch. Wenn du „bei
sicheren Trades 3 %" schreibst, ist die Antwort: eingetragen — wirksam aber erst
nach diesem Nachweis.

Der Hebel kommt **nicht** von dir und nicht vom Modell. Er wird so gesetzt, dass
die Liquidation mindestens 2,5 Stop-Abstaende hinter dem Stop liegt. Senken
darfst du ihn im Dashboard immer: Senken vergroessert den Abstand.

---

## 6 — Was einen Trade beenden muss

| Frage | Steht heute auf | Wo es landet |
|---|---|---|
| Wie lange darf ein Trade offen bleiben? | unbegrenzt | **muss gebaut werden** |
| Vor dem Wochenende schliessen? | nein | **muss gebaut werden** |
| Vor wichtigen Terminen schliessen? | nein | **muss gebaut werden** (die Termine liegen vor, die Regel fehlt) |
| Was macht das Setup ungueltig? | das Modell nennt es pro Trade | steht schon in jedem Vorschlag |

---

## 7 — Was sich nicht verhandeln laesst

Nicht aus Sturheit, sondern weil es die Stellen sind, an denen ein Handelssystem
Geld verliert, ohne dass jemand es merkt.

- **Nichts wird ohne gehaltene Bestaetigung gesendet.** 1,2 Sekunden Knopf
  halten. Das System bereitet den ganzen Trade vor; abschicken tut ein Mensch.
- **Die Sperren gelten auch fuer dich.** Tagesverlust, Hebel, Auszahlungsrechte.
  Ein Limit, das man im Moment des Aergers aufheben kann, ist kein Limit.
- **Kein Auszahlungsrecht auf dem API-Schluessel.** Der Vorflug lehnt einen
  Schluessel ab, der auszahlen darf.
- **Regeln werden gemessen, bevor sie zaehlen.** Eine Einschraenkung, die nie
  getestet wurde, verkleinert nur die Stichprobe — und dieselbe Kante auf
  weniger Trades sieht besser aus, ohne es zu sein. Neue Regeln kommen mit
  Standard „aus" und werden im Backtest gegeneinander gehalten.
- **Das Konto gehoert einem Erwachsenen.** Dann haelt auch dieser Erwachsene den
  Bestaetigungsknopf. Es ist sein Geld und seine Verantwortung.

---

## 8 — Der ehrliche Stand der Strategie

Damit du deine Regeln nicht gegen eine Zahl schreibst, die es nicht gibt.

Ueber 1430 Tage ist die heutige Strategie **nicht belegt**:

- In-Sample (2022-10 bis 2024-10): 231 Trades, Erwartung **−0,028 R**
- Out-of-Sample (2024-10 bis 2026-09): 230 Trades, Erwartung **+0,298 R**

Negativ frueher und positiv spaeter ist das **Gegenteil** von Ueberanpassung — die
letzte Periode war schlicht freundlich. Was ueber das ganze Fenster haelt, ist
etwas anderes: die Zufallskontrolle liegt bei −0,04 R und damit **flach statt
blutend**, seit die Kostenregel drin ist. Vorher waren es −0,179 R.

Deine Regeln sind also nicht „statt einer funktionierenden Strategie" — es gibt
noch keine belegte. Sie sind der naechste Kandidat, und werden genauso gemessen.

---

## Wenn du wenig Zeit hast

Diese fuenf reichen fuer den ersten Durchgang:

1. Welche Maerkte, welcher Takt?
2. Was muss auf dem Chart passiert sein, damit du ueberhaupt hinschaust?
3. Wo liegt dein Stop — hinter welchem Level?
4. Wie viel verlierst du pro Trade, wenn der Stop greift — Prozent oder CHF?
5. Wann hoerst du am Tag auf?

Verwandt: [[traidingBrain]]

---

## Quellenbasis aus der Playlist (2026-09-30)

Von ChatGPT wurden alle 13 Playlist-Videos einzeln erfasst. Die vollständige,
quellentreue Synthese liegt im Projektordner in `DAYTRADING_MASTER_GUIDE.md`, die
Audit-Tabelle in `video_sources.md`. Die Videos liefern mehrere **getrennte**
Modelle, keine gemeinsame fertige Strategie:

- Momentum-Breakout mit Body-/Drei-Kerzen-Bestätigung und Zwei-Stufen-Exit;
- Trendlinien-Break, Fakeout und Break-Retest;
- Supply-/Demand-First-Retest mit BOS, FVG und langsamer Annäherung;
- MTF-Liquiditäts-Sweep mit CHoCH und nachfolgendem BOS;
- Orderblock-Validierung über Sweep, FVG und CHoCH;
- Inducement-/True-Zone-Modell mit 1H- und 15M-Bestätigung;
- zwei abweichende FVG-Modelle, insbesondere bei bereits mitigierten Gaps.

Breaker Blocks, IFVG, Sessions und eine vollständige Positionsgrössenformel sind
in der Primärplaylist nicht definiert und wurden nicht ergänzt. Die
Zusatzrecherche hat 329 Kandidaten gefunden; YouTube blockiert derzeit den
vollständigen Caption-Abruf, deshalb sind daraus noch keine Regeln übernommen.

## Erweiterte Grundlagenbasis (2026-09-30)

`TRADING_ANALYSE_GRUNDLAGEN.md` im Projektordner ergänzt die Playlist-Synthese um
eine für Obsidian und den Analyzer strukturierte Funktionslandkarte. Sie trennt
direkte Beobachtung, Framework-Interpretation und Hypothese und enthält:

- Marktstruktur, S/R, Supply/Demand, Liquidität, Sweeps, BOS/CHoCH/MSS,
  Order-/Breaker-Blöcke, FVG/IFVG, Patterns, Breakouts und Multi-Timeframe-Kontext;
- Volumen, VWAP/AVWAP, Volume-/Market-Profile, Delta/CVD/Footprint sowie
  Open Interest, Funding und Liquidationen;
- Trend-, Momentum-, Volatilitäts-, Volumen- und Level-Indikatoren mit Zweck,
  Eingabedaten, Grenzen und Redundanzprüfung;
- Wirtschaftskalender, Eventfamilien, Newswirkung und Regeln gegen Look-ahead;
- ein maschinenlesbares Obsidian-Schema mit `observation`, `interpretation`,
  `hypothesis`, `confirmation`, `invalidation` und unveränderlichem `outcome`.

Die Datei ist **keine Strategie**. Feste Parameter, Schwellen, Entry/Exit und
Positionsgrössen werden daraus nicht automatisch abgeleitet. Zusatzquellen sind
nach Volltranskript, substantieller Kapitel-/Transkriptevidenz und bloßem
Recherchekandidaten getrennt; blockierte Caption-Spuren werden nicht als gelesen
ausgegeben.

Die Grundlagenbasis wurde danach von einer Charttechnik-Übersicht zu einer
Markt-Enzyklopädie erweitert. Neu dokumentiert sind insbesondere Preisbildung im
Orderbuch, Auktion und Matching, Teilnehmer/Motive, Venue- und Ordertypen,
Slippage/Market Impact, Aktien/ETFs/Zinsen/FX/Rohstoffe/Futures/Perpetuals/
Optionen, Basis und Terminkurve, Greeks und IV, Makro-Übertragungskanäle,
Short-/Borrow-/Margin-/Liquidationsmechanik, Erwartungswert und Drawdown,
Backtest-Biases, Cross-Asset-Beziehungen, Corporate Actions, Contract Rolls,
operative Risiken sowie eine wesentlich breitere Indikator- und Glossarmatrix.
Die Quelle `video_sources.md` trennt weiterhin Volltranskripte von B-Evidenz;
keine begrenzt sichtbare Quelle wird als vollständig transkribiert ausgegeben.

### Verlauf

- **2026-09-30, von: ChatGPT, Commit: 39308cc (Enzyklopädie-Erweiterung uncommitted)** —
  `TRADING_ANALYSE_GRUNDLAGEN.md` um Marktmechanik, Teilnehmer, Instrumente,
  Derivate, Makro-/Cross-Asset-Kanäle, Execution, Risikomathematik, Datenqualität,
  Testmethodik, operative Risiken, erweitertes Indikatorinventar und Glossar
  ergänzt; Quellenstatus in `video_sources.md` transparent nachgeführt.

- **2026-09-30, von: ChatGPT, Commit: 39308cc (Grundlagenbasis uncommitted)** —
  breite technische Analyse-, Indikator-, Liquiditäts-, Orderflow-, News- und
  Historiendatenbasis als separate Obsidian-taugliche Markdown ergänzt; keine
  neue Strategie oder unbelegte Profitabilitätsregel daraus erzeugt.

- **2026-09-30, von: ChatGPT, Commit: 84ad7c3 (Wissensbasis uncommitted)** —
  Playlist-Wissensbasis und Quellen-Audit erstellt; nächste Entscheidung ist die
  Auswahl eines unvermischt zu testenden Creator-Setups.
