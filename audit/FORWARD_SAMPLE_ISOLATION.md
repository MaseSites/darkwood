# Die laufende Vorwärtsstichprobe — identifiziert und isoliert

Erhoben 2026-10-18 15:24Z, vor der ersten Änderung aus Master-Direktive 03.
Voraussetzung dafür, dass spätere Arbeit die Stichprobe nicht kontaminiert.

## Der Prozess

| | |
|---|---|
| Programm | `scripts/papertrade.py` |
| PID (Arbeiter) | **71960** |
| PID (venv-Starter) | 53104 |
| Start | **2026-10-16T04:58:30Z** |
| CPU zum Erhebungszeitpunkt | 7 046.7 s |
| RSS | 316 MB |

Der zweite PID ist kein zweiter Prozess: die venv-`python.exe` ist ein
Starter. Darum hat `os.getpid()` in einer Prüfabfrage auch nicht genügt, um
die eigene Abfrage auszuschliessen — sie erschien unter der PID des Starters.

## Der Code, den er ausführt — aus seinem eigenen Startbanner

```
Entscheidungscode d8c7f12104e4 (de3c0ee)
```

Das ist der Beleg, nicht eine Ableitung aus Dateizeiten. Gegengeprüft am
Reflog: um 04:58:30Z (06:58:30 +0200) stand HEAD auf `de3c0ee`
(2026-10-15 10:56:10 +0200); der nächste Commit `089bf1f` folgte erst
07:01:21 +0200.

| | |
|---|---|
| `decision_version` | **`d8c7f12104e4`** |
| Commit | **`de3c0ee`** |
| `run_signature` | `1000.0\|['A', 'B', 'E', 'F', 'G']\|0.08\|M15\|refused-v1\|portfolio\|cap5` |

**Und die zehn Commits seit `de3c0ee` haben den Entscheidungspfad nicht
bewegt.** Bei HEAD `3b6a4f8` gemessen:

| | |
|---|---|
| `decision_version()` jetzt | `d8c7f12104e4` — **identisch zum Banner** |
| `run_signature()` jetzt | identisch |
| Entscheidungs-Hülle | 59 Module |
| `execution.policy` in der Hülle | **nein** |
| `execution.venuebinding` in der Hülle | **nein** |
| `journal.era` in der Hülle | **nein** |

Ein laufender Python-Prozess liest seine Module beim Start; spätere
Quelltextänderungen erreichen ihn nicht. Zusammen mit dem unveränderten
Stempel heisst das: die Stichprobe ist bis hierher unkontaminiert.

## Das Dashboard läuft auf einem ANDEREN Commit

| | |
|---|---|
| Programm | `scripts/run_dashboard.py` (ohne `--execute`) |
| PID (Arbeiter) | 64976, Starter 42300 |
| Start | 2026-10-18 wäre falsch — **2026-10-16T05:33:21Z** |
| CPU | 2 630.6 s |

05:33:21Z = 07:33:21 +0200. Zu diesem Zeitpunkt stand HEAD auf **`b51160e`**
(07:22:15 +0200), nicht auf `de3c0ee`. Händler und Dashboard führen also
verschiedene Codestände aus. Für die Stichprobe folgenlos — das Dashboard
entscheidet keine Trades und ist ohne `--execute` auch nicht ausführfähig —
aber es gehört festgehalten, damit niemand die beiden als einen Stand liest.

## Konfiguration und Datenpfade

| | |
|---|---|
| Börse | `name='binance' market_type='linear' testnet=True rate_limit_ms=120` |
| Setups | `['A', 'B', 'E', 'F', 'G']` |
| Märkte | 12 aktiv |
| Simulation | `initial_equity 1000.0`, `slippage_bps 3.0`, `fill_on_touch False` |
| Risiko | `basis portfolio`, `max_open_positions 5`, `max_cost_fraction_of_risk 0.08` |

| Pfad | |
|---|---|
| `data_dir` | `data/` |
| `parquet_dir` | `data/ohlcv` |
| `funding_dir` | `data/funding` |
| `db_path` | `data/traidingbrain.sqlite` |
| `cache_db_path` | `data/decisions.sqlite` |
| `runs_dir` | `runs/` |

Gelesen und geschrieben werden ausserdem `data/paper.sqlite` (Zustand),
`data/journal.sqlite` (abgeschlossene Trades), `data/signals.sqlite` (jedes
bewertete Signal) und `data/funding/*.parquet` (vom Händler bei jedem Lauf
aufgefrischt, siehe `audit/P0A_LEGACY_FREEZE.md`).

## Was daraus für die weitere Arbeit folgt

1. **Prozess 71960 wird nicht angefasst** — nicht gestoppt, nicht neu
   gestartet, nicht mit neuerem Code versehen.
2. **`data/funding/`, `data/ohlcv/`, `data/paper.sqlite`, `data/journal.sqlite`
   und `data/signals.sqlite` werden nicht umgeschrieben.** Der Händler liest
   und schreibt sie laufend.
3. Jede Schutzmassnahme, die das Schreibverhalten dieser Pfade ändern würde,
   wird **isoliert implementiert und getestet, aber nicht im laufenden Prozess
   aktiviert**. Ein laufender Prozess bekommt sie ohnehin erst bei einem
   Neustart zu sehen — und der findet nicht statt.
4. **Neue Daten gehen in neue Pfade.** Eine Migration bestehender Dateien
   wäre eine irreversible Datenänderung und braucht ausdrückliche Freigabe.
5. Wenn eine Änderung sich nicht sicher von der Stichprobe trennen lässt,
   wird sie **als Blocker dokumentiert statt geraten**.

## Etiketten

| Aussage | |
|---|---|
| PID, Startzeit, CPU, Kommandozeile | **BELEGT** (Prozessabfrage) |
| `decision_version` und Commit des Händlers | **BELEGT** (eigenes Startbanner) |
| Commit zur Startzeit | **BELEGT** (Reflog mit Zeitstempeln, deckt sich mit dem Banner) |
| Entscheidungspfad seit `de3c0ee` unverändert | **BELEGT** (Stempel identisch, drei neue Module ausserhalb der Hülle) |
| Dashboard-Commit `b51160e` | **BELEGT** (Reflog-Zeit gegen Prozess-Startzeit) |
| Stichprobe bis hierher unkontaminiert | **BELEGT** für den Code; **MODELLIERT** für die Daten, weil `data/funding/` vom Händler selbst fortgeschrieben wird und dessen Append-Verhalten nur durch Aufruferdisziplin gesichert ist |

---

# Das ENDE der Stichprobe, 19.10.2026

**Der Prozess läuft nicht mehr.** PID 71960 existiert nicht; in der
Prozessliste stehen nur noch zwei Dashboard-Einträge. Festgestellt am
19.10.2026 um 07:58 Ortszeit (UTC+2), also 73 Minuten nach dem letzten
Schreibzugriff.

## Wann genau, und woran man es sieht

| | |
|---|---|
| letzte gesehene Minute (`last_minute_ts`) | **2026-10-19 04:43:00 UTC** |
| letzte Entscheidung (`last_decided_ts`) | 2026-10-19 04:15:00 UTC |
| letzter Schreibzugriff auf `data/paper.sqlite` | **2026-10-19 04:45:48 UTC** |
| Zyklen insgesamt (BTCUSDT-Zeile) | 10.408 |

Die beiden Zeiten passen auf zwei Minuten zusammen, und sie fallen mit dem
Ende der vorangehenden Arbeitssitzung zusammen: der Papierhändler lief in
einem Hintergrundprozess dieser Sitzung, und als sie endete, endete er mit.
Fünf Hintergrundprozesse wurden dabei als gestoppt vermerkt.

**Das ist keine Vermutung über die Ursache, sondern eine Übereinstimmung von
Zeitpunkten.** Ein Absturz aus eigenem Grund würde genauso aussehen; was
dagegen spricht, ist nur, dass vier weitere Prozesse im selben Moment endeten.

## Der Endstand

| | |
|---|---|
| `portfolio.equity` | **11.775,2601 USDT** |
| `portfolio.peak_equity` | 12.075,5607 USDT |
| Rückgang vom Hoch | **2,487 %** |
| offene Positionen beim Stillstand | **2 von 12** |
| `live`-Trades im Journal insgesamt | 33, vom 02.10. 08:00 bis 19.10. 00:52 |

**Die zwei offenen Positionen sind der wichtigste Punkt dieses Abschnitts.**
Sie werden nie schliessen. Für sie gibt es kein Ergebnis — sie sind weder
Gewinner noch Verlierer, und jede Auswertung, die sie mitzählt, zählt zwei
Trades mit, die nie entschieden wurden. Wer die Stichprobe auswertet, muss sie
**ausschliessen und die Zahl nennen**, nicht stillschweigend weglassen.

Die 33 `live`-Trades sind **nicht** die homogene Stichprobe. Sie reichen bis
zum 02.10. zurück und umfassen frühere, anders gestempelte Läufe; die
homogene Teilmenge steht oben in diesem Dokument.

## Was jetzt NICHT passieren darf

**Ein Neustart erzeugt eine NEUE Stichprobe, keine Fortsetzung.** Der
Papierhändler lief unter dem Entscheidungsstempel `d8c7f12104e4`. Der
Arbeitsbaum steht heute auf **`b0331f2e42c3`** — zwischen beiden liegen die
Phasen 0 bis 6 samt der Herkunftsaufzeichnung im Simulator.

Einen neuen Lauf mit dem alten zusammenzuwerfen wäre genau die Verunreinigung,
gegen die dieses Dokument geschrieben wurde. Ob neu gestartet wird, ist darum
eine **Produktentscheidung** und keine Wiederherstellung:

* *Nicht neu starten* heisst: die Vorwärtsstichprobe ist mit 17 Tagen und
  33 Trades (davon zwei unentschieden) abgeschlossen.
* *Neu starten* heisst: eine zweite Stichprobe unter `b0331f2e42c3` beginnt,
  getrennt geführt, mit eigenem Startbanner und eigener Auswertung.

Beides ist vertretbar. Stillschweigend weiterlaufen lassen und die Zahlen
addieren ist es nicht.

## Eine Korrektur am Stempel-Protokoll

Der Commit `e089071` („Phase 6d") nennt in seiner Botschaft den resultierenden
Entscheidungsstempel als `ca9a67ffb4de`. **Das ist ein Zwischenwert.** Er galt
nach dem ersten Broker-Edit und vor dem Hinzufügen von `planned_stop` und
`planned_target`; der Stempel des fertigen Commits ist `b0331f2e42c3`.

Nachgerechnet am 19.10.2026 an drei Commits (`e089071`, `7ed3383`, `8915020`):
alle drei tragen `b0331f2e42c3`, und `planned_stop` steht in allen drei schon
in `sim/broker.py` — Phase 6d liegt also vor dem Blindfleck-Audit, und die
Reihenfolge stimmt.

Derselbe Fehler wie bei der Marke `+0.42 R`: eine Zahl zu einem Zeitpunkt
gemessen und als Endwert zitiert. Die Commit-Botschaft bleibt stehen; die
Korrektur steht hier.

## Etiketten für diesen Abschnitt

| Aussage | |
|---|---|
| Prozess läuft nicht mehr | **BELEGT** (Prozessabfrage, eigene Abfrage ausgeschlossen) |
| Zeitpunkt des Endes | **BELEGT** (`last_minute_ts` und Datei-mtime, zwei Minuten auseinander) |
| Endstand der Kasse, zwei offene Positionen | **BELEGT** (`data/paper.sqlite`) |
| Ursache „Sitzungsende" | **MODELLIERT** — Zeitgleichheit mit vier weiteren Prozessen, kein Protokolleintrag des Händlers selbst |
| Stempel `b0331f2e42c3` an drei Commits | **BELEGT** (je Commit nachgerechnet) |
