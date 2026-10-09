# Forschungsplan — Reihenfolge, Status, Abhängigkeiten, Tore

**Grundlage:** `TRADING_BRAIN_DEEP_RESEARCH_V2.md` vom 09.10.2026
**Stand dieses Dokuments:** 08.10.2026, 22:50 UTC · Commit `6074abe`

Dieses Dokument ist die Landkarte. Ergebnisse stehen in den Experimentdateien,
die Vorabregistrierung in `audit/EXPERIMENTS_NEXT.yaml` (derzeit **50**
angemeldete Vergleiche, Niveau 99,9000 %).

---

## Status der Phasen

| Phase | Gegenstand | Status | Abhängig von | Artefakt |
|---|---|---|---|---|
| **P0** | Baseline reproduzieren | **erledigt, mit Lücken** | — | `BASELINE_REPRODUCTION.md` |
| **P1** | Datenintegrität und Betrieb | **teilweise** | — | `DATA_INTEGRITY_AUDIT.md` |
| P2 | E4 Relative Value | **blockiert an Preisen** | Kurse fuer ein Punkt-in-Zeit-Universum | `E4V_RELATIVE_VALUE_VORPRUEFUNG.md` |
| P3 | E5 Streaming / Orderflow | **blockiert** | Collector | `E5_ORDERFLOW.md` |
| P4 | P26 Lead-Lag | **blockiert** | P3 (Streaming + Uhr) | `P26_LEAD_LAG.md` |
| P5 | E7 LLM-Shadow | **registriert** | P0 | `E7_LLM_SHADOW.md` |
| P6 | Fill- und Kostenmodell | **teilweise** | laufend | `EXECUTION_COSTS.md` |
| P7 | Unabhängige Replikation | **nicht begonnen** | ein Kandidat | — |

### Was aus P0 und P1 wirklich belegt ist

**Belegt:** E3 und E9 reproduzieren ziffernidentisch. Der Ratchet steht auf 22
erledigt / 0 offen / 1 nicht testbar. Die Journal-Arithmetik ist in 2 749
Trades fehlerfrei. 0 Duplikate und 0 verdrehte Zeitstempel in 72 OHLCV-Reihen;
1 830 fehlende Kerzen von ~45 Millionen, und alle 12 M1-Reihen lückenlos. Alle
38 Leakage-/Mutations-/Purging-Tests grün. P44 ist behoben und
Ende-zu-Ende geprüft.

**Gefunden:** der Wächtertest über das Experiment-Register war fünf Commits
lang rot (ab `a7e2d50`), weil E8–E10 ohne die Pflichtfelder `arms` und
`acceptance` angelegt wurden. Behoben. Niemand hatte nach dem Hinzufügen
eines Arms die ganze Suite laufen lassen.

**Nicht belegt:** das Phase-1-Abnahmekriterium („ein absichtlich eingeführter
Fehler führt zu einem klaren ungültigen Status") ist **nicht** erfüllt — es
verlangt den Streaming-Collector aus P3. `study_target_20x.py`, E6 bei 180
Tagen Haltedauer und der FreqAI-Vergleich sind nicht reproduziert.

**Zwei eigene Vermutungen widerlegt:** der Vorwärtshandel löst *doch* minütlich
auf (im Speicher, nicht aus dem Archiv), und der M1-Rückstand kostet nur 0,1 %
der nachsimulierbaren Signale.

## Tore für jeden Kandidaten

Unverändert aus dem Auftrag und aus der bestehenden Registrierung. Ein
Kandidat geht nur weiter, wenn **alle** zutreffenden erfüllt sind:

1. Datenintegrität belegt, bekannte Lücken markiert
2. Kein Look-ahead, kein Leakage, keine revidierten Daten im
   Entscheidungszustand
3. Netto-Erwartungswert nach **allen** Kosten positiv
4. Vorab registriertes Unsicherheitskriterium erfüllt
   (korrigiertes Intervall ohne Null, Bonferroni auf 50)
5. Mehrfachtest-/Selektionskorrektur berücksichtigt
6. **Inkrementell gegenüber einer Baseline, nicht bloss Markt-Beta**
7. Robust gegen konservative Kosten- und Latenzannahmen
8. Unabhängige Replikation im Band **0,5–2,0×**
9. Nicht von einem einzelnen Markt oder wenigen korrelierten Ereignissen
   getragen
10. Ausführung im Papiersystem technisch plausibel
11. Sicherheits- und Rechtsfragen unabhängig geklärt

Reicht die Datenmenge nicht, lautet der Befund **„unklar — mehr Evidenz
erforderlich"**, nicht „profitabel".

### Tor 6 ist das Tor, an dem bisher alles gescheitert ist

E8 hat gemessen, dass die Trades ein Beta von **+0,985** [+0,870; +1,104] zum
Kryptomarkt tragen und daneben **−0,0827 R** [−0,1404; −0,0151] übrig lassen.
Jeder neue Kandidat muss gegen diese marktgerichtete Baseline antreten, nicht
gegen Null.

## P2 abgeschlossen — mit einer Korrektur und einer Entscheidung

**E4 war nie entsperrt.** Die Punkt-in-Zeit-Tabelle nennt, *welche* Symbole
wann handelbar waren, nicht deren Kurse. Gemessen: 232 handelbare Perps am
01.06.2022, **749** am 01.06.2026 — Kurse liegen für **zwölf** vor. E4 steht
wieder auf `blockiert_an_preisen`.

**Der Schirm E4V ist gelaufen und negativ.** 2 221 Tage, netto −12,43 bp/Tag
[−22,46; −1,33], Intervall ohne Null auf der falschen Seite, Replikation
+1,76× im Band, kein einzelner Markt trägt es. Und das Spiegelbild verliert
ohne zweiten Lauf: Brutto 5,20 bp gegen eine Maut von 7,15 bp.

**Entscheidung nach der vorab festgelegten Asymmetrie:** E4 bleibt blockiert,
und der Kursdownload für 232–749 Symbole plus 138 delistete **unterbleibt**.
Das war der grösste offene Einzelbau dieses Plans.

## Nächster Schritt — genau einer

**Den Streaming-Collector bauen (Phase 3, E5).** Er ist jetzt der einzige
Weg, der noch irgendwo hinführt, und er trägt drei Dinge auf einmal:

1. **E5** (Orderflow auf handelbarem Horizont) ist ohne ihn nicht rechenbar.
2. **P26** (die Lead-Lag-Asymmetrie) ist die *einzige* gemessene Grösse des
   Projekts mit möglicherweise positivem Vorzeichen — und ohne getrennte
   Event- und Empfangszeit nicht von einem Uhrenversatz zu trennen.
3. Das **Phase-1-Abnahmekriterium** („ein absichtlich eingeführter Fehler
   führt zu einem klaren ungültigen Status") verlangt ihn.

Zuerst nur BTC und ETH als technische Prüfung: Diff Depth, Book-Ticker,
Aggregated Trades, mit Sequenzkontrolle nach dem **USDⓈ-M-Futures**-Verfahren
(nicht dem Spot-Beispiel), Reconnect, Stale-Erkennung, append-only Rohdaten
und Lückenmetriken. Erst wenn der Collector stabil läuft, Features.

**Was E4V darüber sagt, und es ist eine Warnung:** die Maut war 7,15 bp gegen
ein Brutto von 5,20. Jeder Kandidat aus E5 wird gegen dieselbe Struktur
antreten, nur auf einem kürzeren Horizont, wo die Maut je Zeit noch grösser
ist. Der Collector ist zu bauen, um die Frage zu *beantworten* — nicht in der
Erwartung, dass sie positiv ausgeht.

## Nicht als nächstes, und warum

| | |
|---|---|
| **E4 selbst** | Blockiert an Kursen für ein Punkt-in-Zeit-Universum. Der Schirm E4V hat den Download entbehrlich gemacht, nicht möglich. |
| **E7** | `calibration_proven` bleibt `false`. Die kalibrierte Zuversicht ist von der Basisrate nicht unterscheidbar (−0,00005 [−0,00011; +0,00001]). Ein weiterer Lauf gegen dieselbe Null kostet Budget ohne Aussicht. |
| **Mehr Märkte, Indikatoren, Hebel, Trades** | Gemessen erledigt. Siehe `PROBLEMBERICHT_20X.md` §6: zehn Wege mit Beleg zugemauert. |

## Trial-Ledger

Noch nicht als `audit/TRIAL_LEDGER.csv` angelegt. Die Funktion erfüllt derzeit
`audit/EXPERIMENTS_NEXT.yaml` (angemeldete Arme, Zellen,
`total_comparisons: 50`, ein Amendment mit Datum und Grund) zusammen mit
`scripts/ratchet.py` (124 registrierte Versuche, 87 verschiedene Arme, 16+6
geschlossene Familien). **Offen:** eine Tabelle, die *jede* verworfene Variante
einzeln führt, statt sie in Familien zusammenzufassen.

## Sicherheitsregeln

Unverändert gültig und in `PROBLEMBERICHT_20X.md` §8 ausgeschrieben. Für diese
Phase relevant und eingehalten: keine Live-Ausführung, kein Netzzugriff mit
Schlüsseln, kein zweiter Papierhändler gestartet, keine Strategieparameter
geändert, das Prüffenster bei **0 Konsultationen**.
