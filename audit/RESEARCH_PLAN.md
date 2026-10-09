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
| P3 | E5 Streaming / Orderflow | **blockiert an Marktdaten** | WS-Auslieferung an diese IP | `E5_ORDERFLOW.md` |
| P4 | P26 Lead-Lag | **blockiert, mit P3** | P3 | `E5_ORDERFLOW.md` §3 |
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

## P3 geprüft — und der Collector ist nicht baubar

**Die Dokumentation ist verifiziert, und das bleibt nutzbar.** Die
Futures-Prozedur liegt wörtlich vor; `pu` ist der Unterschied zur
Spot-Fassung, und wer das Spot-Verfahren anwendet, invalidiert sein Buch
dauernd oder nie. Payloads empirisch belegt statt aus dem Gedächtnis.

**Der Blocker hat sich verschoben.** Nicht „es gibt keinen Collector", sondern:
Produktions-WebSocket-Marktdaten werden an diese IP **nicht ausgeliefert**.
Handshake gelingt, `SUBSCRIBE` wird bestätigt, dann null Nachrichten in 12 s —
gegen rund 95 fällige. Vier Pfade, alle stumm, Client am Echo-Dienst in
Ordnung.

**Und der Host, der liefert, ist der falsche.** `stream.binancefuture.com`
gibt Daten, mit Preisen, die auf den Cent stimmen — und einem Kennraum, der um
**Faktor 11** abweicht, bei einem Sechstel der Rate. Eine Preisprüfung hätte
das nie gefunden. Für P26 wäre er wertlos: ein Strom, der 85 % der Ereignisse
nicht zeigt, kann einen Sekundenvorlauf nicht von einem Uhrenversatz trennen.

Damit bleiben **E5, P26 und das Phase-1-Abnahmekriterium** gemeinsam offen,
und keines davon aus einem Grund, den Code behebt.

## Nächster Schritt — genau einer

**Keiner, der ohne eine Entscheidung des Kontoinhabers vorangeht.**

Das ist die ehrliche Antwort, und sie steht hier statt einer Beschäftigung:

| Weg | Stand |
|---|---|
| E4 Relative Value | blockiert an Kursen; der Schirm E4V war negativ und hat den Download **entbehrlich** gemacht |
| E5 Orderflow | blockiert an WS-Marktdaten für diese IP |
| P26 Lead-Lag | blockiert mit E5 — die einzige Grösse mit offenem Vorzeichen |
| E7 LLM-Shadow | `calibration_proven: false`; kalibrierte Zuversicht von der Basisrate nicht unterscheidbar |
| Phase-1-Abnahme | verlangt Sequenz- und Stale-Zustände, also E5 |
| mehr Märkte, Indikatoren, Hebel, Trades | gemessen erledigt, zehn Wege mit Beleg zugemauert |

**Was weiterläuft, ohne Entscheidung:** der Vorwärtshandel. Er ist die einzige
Evidenzquelle, die noch wächst, und sie wächst mit ~1,9 Trades/Tag. 17
geschlossene Live-Trades; 100 brauchen etwa 52 Tage. Das ist langsam und es
ist echt.

**Was eine Entscheidung bräuchte:**

1. **Zugang zu Produktions-Streamdaten**, auf regulärem Weg. Erst damit sind
   E5, P26 und das Phase-1-Kriterium überhaupt adressierbar. Ich schlage
   keinen Weg um die Beschränkung herum vor.
2. **Oder** die Feststellung, dass das Projekt mit Polling auskommen muss.
   Dann ist P26 nicht entscheidbar und E5 nicht rechenbar, und das wäre
   festzuhalten statt offen zu lassen.

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
