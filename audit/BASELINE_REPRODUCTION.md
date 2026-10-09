# Phase 0 — Reproduktion der Baseline

**Lauf:** 08.10.2026, 22:34–22:47 UTC (lokal 09.10., 00:34–00:47)
**Commit:** `6074abe` — Arbeitsbaum sauber vor dem ersten Lauf
**Zweck:** prüfen, ob die Zahlen im `PROBLEMBERICHT_20X.md` und in den
Audit-Dateien aus den gespeicherten Daten wiederkommen. Keine Zahl wurde
angepasst, damit sie passt.

---

## 1. Daten-Vintage zum Zeitpunkt der Reproduktion

| Datei | Grösse | letzte Änderung | Inhalt |
|---|---|---|---|
| `data/journal.sqlite` | 11 489 280 B | 08.10. 22:10 UTC | 2 749 Trades, letzter 20:28 UTC |
| `data/signals.sqlite` | 34 570 240 B | 08.10. 20:01 UTC | 67 807 Signale |
| `data/paper.sqlite` | 36 864 B | 08.10. 22:34 UTC | 12 Konten, laufend |
| `data/ohlcv/` | 480 Parquet-Dateien | — | 72 Reihen über 12 Märkte |

**Wichtig für jeden Vergleich mit den Audit-Dateien:** das Journal ist seit
E8/E9 gewachsen. E8 lief auf **2 748** Trades und 14 Live-Trades, hier sind es
**2 749** und **15**. Jede Abweichung unten ist zuerst daran zu prüfen.

## 2. Ergebnisse

| Skript | Laufzeit | Ergebnis | gegen Audit-Datei |
|---|---|---|---|
| `ratchet.py` | < 1 s | 22 erledigt, 0 offen, 1 nicht testbar, 0 gesperrt; „KEIN BELEGTER VORTEIL"; Prüffenster 0 Konsultationen | **exakt** |
| `study_exits.py` | 9,4 s | 7 255 Fälle; −0,0205 / −0,0824 / −0,0762 R; gepaart −0,0619 [−0,1316; +0,0071] und −0,0557 [−0,1123; −0,0060] | **exakt**, Ziffer für Ziffer — **und beide Grenzen wurden später korrigiert**, weil der Bootstrap bei 3 000 Ziehungen das korrigierte Perzentil nicht auflösen konnte. Jetzt [−0,1290; +0,0115] und [−0,1091; **−0,0001**]. Die Reproduktion war damit korrekt und reproduzierte einen Defekt mit (`audit/BOOTSTRAP_RAND.md`) |
| `study_fill_realism.py` | 2 min 35 s | 657 647 Orders; gepoolt 0,6 % [0,6; 0,7]; BTC 0,8 / ETH 1,1 / SOL 0,5 / XRP 0,2 / DOGE 0,1 / LINK 0,1 % | **exakt**, alle sechs Märkte |
| `study_beta_alpha.py` | 2,6 s | siehe unten | **mit Abweichungen** |
| `study_basis.py` | läuft | — | offen |
| `study_target_20x.py` | 9 s | 0,00 % Zielerreichung bei 1 % Risiko, Median 657, CVaR5% 347, **0,0 % Liquidationen** | **reproduziert**, siehe `EXECUTION_COSTS.md` §7 |
| `papertrade.py` | **absichtlich nicht gestartet** | — | siehe 2.3 |

### 2.1 E8 — reproduziert, mit kleinen und einer grossen Abweichung

| Zelle | Audit-Datei (n=2748/14) | Reproduktion (n=2749/15) |
|---|---|---|
| Mechanik, eigenes Symbol | a −0,0505, b +0,874 [+0,767; +0,950] | a **−0,0507**, b +0,874 [+0,780; +0,948] |
| **E8.1** alle Journal-Trades | a −0,0823 [−0,1414; −0,0119], b +0,985 [+0,873; +1,105] | a **−0,0827** [−0,1404; −0,0151], b +0,985 [+0,870; +1,104] |
| **E8.2** nur Live | a **+0,0048**, b +1,788 | a **−0,1142**, b **+1,875** |
| Replikationsverhältnis | +2,36× ausserhalb | **+2,36×** ausserhalb |

Die Abweichungen in E8.1 und in der Mechanik liegen in der vierten
Dezimalstelle und erklären sich aus einem zusätzlichen Trade; die
Intervallgrenzen verschieben sich entsprechend. **Der Befund ist unverändert:**
Beta eins, Rest zuverlässig negativ, Replikation ausserhalb des Bandes.

**E8.2 ist die Ausnahme und sie ist lehrreich.** Ein einziger zusätzlicher
Live-Trade (DOT, −1,0665 R, 08.10. 20:28 UTC) dreht den Punktschätzer des
Vorwärts-Alphas von **+0,0048 auf −0,1142 R** — eine Verschiebung um 0,119 R
durch eine Beobachtung. Das ist keine Instabilität des Skripts, sondern genau
die Eigenschaft, die der Problembericht behauptet: **15 Trades sind keine
Verteilung.** Die Reproduktion belegt diese Aussage stärker als die
ursprüngliche Messung.

### 2.2 Journal-Integrität — sechs Prüfungen, alle sauber

| Prüfung | Ergebnis |
|---|---|
| Duplikate `trade_id` | **0** |
| `closed_ts <= opened_ts` | **0** |
| Zeitstempel in der Zukunft | **0** |
| `net_pnl` ≠ `r_multiple × risk_amount` (Toleranz 0,2 %) | **0** von 2 749 |
| `gross − fees + funding` ≠ `net` | **0** von 2 749 |
| Gebühren ≤ 0 | **0**; Summe 6 516,53 |
| Funding ≠ 0 | 1 428 Trades; Summe **+219,12** |

Quellen: 15 live, 2 734 replay. Ausgänge: 1 864 stop, 882 target,
**1 liquidation**, 2 manual. Die eine Liquidation und die zwei manuellen
Schliessungen stehen in keiner Audit-Datei — kein Fehler, aber bisher
unerwähnt.

### 2.3 `papertrade.py` wurde absichtlich nicht gestartet

Der Auftrag nennt es als Reproduktionsschritt „nur in sicherem Paper-Modus".
**Ein Händler läuft bereits** (seit 02.10., zuletzt verarbeitete Minute 22:16
UTC). Ein zweiter Start wäre genau der Betriebsfehler P44, der dieses Projekt
schon 58 fehlgeschlagene Zyklen gekostet hat. Stattdessen wurde der laufende
Prozess gelesen (`--status`-Pfad, kein Netz) und in Phase 1 der Lock gebaut,
der diesen Fehler ab jetzt unmöglich macht.

### 2.4 Leakage und Mutation

```
pytest tests/ -k "mutation or vintage or future or leak or purge or embargo"
38 passed
```

Alle 38 Tests grün. Das deckt den Zukunfts-Mutationstest, die
Vintage-Prüfungen und Purging/Embargo ab. **Was es nicht deckt** und was als
Vorbehalt bestehen bleibt: eine Quelle, die ihre eigene Vergangenheit
umschreibt, ist für den Mutationstest unsichtbar — er variiert die Zukunft.

### 2.5 Ein roter Wächtertest, fünf Commits lang — gefunden von dieser Phase

Die vollständige Suite deckte einen Fehlschlag auf, und er liegt in meiner
eigenen Arbeit:

```
FAILED tests/test_experiment_registry.py::test_every_experiment_declares_what_it_will_be_judged_by
AssertionError: E8 ohne ['arms', 'acceptance']
```

`REQUIRED` im Wächtertest verlangt `id, title, priority, status, arms,
comparisons, acceptance`. Die Arme E8, E9 und E10 wurden mit deutschen
Hilfsschlüsseln (`arme`, `zellen`, `tore`) angelegt statt mit dem Schema, das
E0–E7 benutzen. Damit war der Test rot — und zwar:

| Commit | Register |
|---|---|
| `e4c71fa` | sauber |
| `a7e2d50` (E8) | **E8 verletzt** |
| `422cfb7` (E9) | E8, E9 |
| `1e61b02` | E8, E9 |
| `6074abe` (E10) | E8, E9, E10 |

**Fünf Commits mit einem roten Wächter, weil nach dem Hinzufügen eines Arms
nie die ganze Suite lief** — nur der betroffene Teil und das Lint. Der Test
existierte, prüfte genau das Richtige und wurde nicht gefragt.

Behoben: alle drei Arme tragen jetzt `arms` (mit eindeutigen Kennungen) und
`acceptance`, und die Annahmekriterien stehen damit im Register statt nur im
Bericht. `total_comparisons: 50` stimmt weiter mit der Summe der angemeldeten
Vergleiche überein.

**Das ist der Fund, der diese Phase gerechtfertigt hat.** Ohne sie wäre eine
Vorabregistrierung im Umlauf gewesen, deren eigene Prüfung fehlschlägt.

## 3. Nicht reproduziert

| Was | Grund |
|---|---|
| ~~`study_target_20x.py`~~ | **nachgeholt.** Es stimmt mit meiner eigenen Rechnung im Vorzeichen und in der Grössenordnung überein (0,00 % Zielerreichung), ist aber reicher: es führt hypothetische Vorteile mit, und daraus folgt die wichtigste Zahl des Projekts — **das Ziel verlangt +0,7280 R je Trade**, und selbst +0,40 R endet bei 5 200 CHF. Siehe `EXECUTION_COSTS.md` §7. |
| `study_basis.py` (E6) | lief zum Berichtszeitpunkt noch |
| `FREQAI_VERGLEICH.md` | braucht einen Freqtrade-Lauf, nicht in diesem Block |
| `TAPE_*`-Befunde | gegen `data/quarantine/` reproduzierbar, in diesem Block nicht erneut gerechnet; die Korrektur auf volle Abdeckung liegt in `TAPE_VOLLE_ABDECKUNG.md` vom selben Tag |

## 4. Befund

**Die zentralen Kennzahlen halten.** E3 und E9 reproduzieren ziffernidentisch,
der Ratchet und die Journal-Arithmetik sind konsistent, E8 reproduziert bis auf
Vintage-Effekte. Es gibt in diesem Block **keinen Hinweis**, dass eine der
berichteten Zahlen falsch gerechnet wäre.

**Eine Zahl ist weniger belastbar als sie aussah:** das Vorwärts-Alpha E8.2
verschiebt sich um 0,119 R, wenn ein Trade hinzukommt. Als Punktschätzung ohne
Intervall ist sie nicht zitierfähig, und das war vorab festgelegt.

**Offen:** `study_target_20x.py` gegen die eigene Monte-Carlo-Rechnung, E6, und
der FreqAI-Vergleich.
