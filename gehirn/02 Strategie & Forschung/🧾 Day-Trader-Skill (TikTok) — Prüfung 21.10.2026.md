---
typ: produkt-teil
projekt: TradingBrain
bereich: forschung
status: abgeschlossen
aktualisiert: 2026-10-22
tags: [extern, skill, orb, time-machine, verworfen]
---

# Day-Trader-Skill (TikTok) — Prüfung 21.10.2026

Quelle: `github.com/Jakeschincariol/day-trader-skill` (Commit `3d0f4ef`, MIT), elf
Claude-Skills für US-Aktien-Daytrading. Frage des Owners: Sind wir **mit** dem Skill als
Zusatz besser dran als **ohne**? Wenn ja einbauen, sonst weglassen.

**Entscheidung: weglassen.** Kein Teil hat in irgendeinem Test einen Vorteil gezeigt, der
sich auf einem zweiten Datensatz wiederholt hat. Nichts wurde eingebaut, keine Config und
kein Entscheidungspfad berührt.

## Was der Skill ist (BELEGT, Code gelesen)

- US-Aktien, nur Long, nur innerhalb eines Tages; `trader-risk` blockt Krypto ausdrücklich.
- Kernstrategie: Opening-Range-Breakout (15 min), Einstieg beim ersten 5-min-Schluss über
  dem Range-Hoch (09:45–15:30), Stop in der Range-Mitte, Ziel 1R, flat 15:55.
- „Time Machine“: Bootstrap der restlichen Session aus den 59 Vortagen nach Tageszeit, ±2 Bars.
- Rest (News, SEC-Analyst, Pelosi-Tracker, Alerts, Broker-Ticket) ist US-Aktien-Datenzugang
  ohne Gegenstück in unserem Krypto-System; Budget/Risk haben wir bereits.
- Code sauber (nur Standardbibliothek, öffentliche Endpunkte); 315/315 Repo-Tests grün bei uns.

## Messungen (BELEGT)

Nachbau in numpy, gegen das Repo-eigene TSLA-Beispiel validiert: 33 Trades, 13/15/5,
Ø −0,062 R exakt; Time Machine 29,2 % vs. 29,4 % (Zufallsrauschen). Intervalle: 95 %
Bootstrap über ganze ISO-Wochen ([[📊 Evidenzstand]]: Wochenfaktor), 5 000 Ziehungen.

| Test | n | brutto R/Trade | netto | Befund |
| --- | --- | --- | --- | --- |
| ORB Long, Krypto, NY-Öffnung, 67 Perps, 2020–2026 | 64 379 | −0,042 [−0,068, −0,017] | −0,230 (10 bp) | jedes Jahr negativ; schlechter als Zufallseinstieg: −0,082 [−0,107, −0,056] |
| ORB Long, Krypto, 00:00 UTC | 95 247 | −0,026 [−0,049, −0,004] | −0,268 | schlechter als Zufallseinstieg: −0,074 |
| ORB Long, US-Aktien (Heimatmarkt), 154 Titel, 29.07.–20.10.2026 | 4 784 | −0,014 [−0,071, +0,042] | −0,067 (4 bp) | nur 60 Tage verfügbar (Yahoo-Grenze) |
| Time Machine als Filter auf **unseren** 7 310 Replay-Trades | 7 310 | — | — | Rangkorrelation Prognose↔Ergebnis −0,07 brutto / −0,12 netto; kein Filter besser als „alle“ |

Time Machine als Filter auf ORB: „tendiert zum Ziel“ vs. alle — NY −0,012 [−0,058, +0,036],
UTC **+0,036 [+0,008, +0,064]**, US −0,007 [−0,044, +0,043]. Der eine positive Wert
repliziert nicht und bleibt netto tief negativ (+0,03 R brutto gegen ~0,19 R Kosten).

Tages-Scanner (Original `find_setups`), Überschuss gegen den Querschnitt desselben Tages,
Intervalle Bonferroni über 20 Tests:

- US, 10 Jahre, 356 000 Aktientage: nichts positiv gesichert; `oversold_bounce` am Folgetag
  **−15,1 bp [−28,3, −1,5]** — verlässlich schädlich.
- Krypto D1, 126 000 Markttage: `oversold` 5-Tage +31,4 bp [+0,3, +63,9], an der Grenze und
  instabil (2024 +6, 2026 −7) — derselbe Reversionseffekt, den die Kosten schon schlagen
  ([[🧠 Strategie-Universum]]: Querschnitt-Toll).
- Kette Scanner → ORB (die vom Skill gedachte Pipeline): Krypto kein Tag besser als alle;
  US `reclaim_ma20` +0,118 R auf n = 229 in einem 60-Tage-Fenster, auf Krypto −0,019 —
  nicht repliziert, Mehrfachtest-Rauschen.

## E-TM: der letzte Kandidat auf 56 ungesehenen Märkten (22.10.2026) — GEFALLEN

Vorregistriert vor dem Lauf (`research/day_trader_skill_eval/E_TM_VORREGISTRIERUNG.md`,
SHA-256 `832ac7bf…`, 06:18 UTC). Arm: Trade behalten, wenn `lean ≥ −0,05` („Stop-Tendenz
weg“, der beste von drei in-sample-Filtern). Quelle `data/replay_fills_0311` (wie E17),
Intervalle zweiwegig Markt × 7-Tage-Block, Bonferroni über 86 Vergleiche (z = 3,44).

| | Trades | Basis R/Trade | Arm R/Trade | Arm − Basis |
| --- | --- | --- | --- | --- |
| 56 ungesehene Märkte | 30 821 / 24 160 | −0,0345 | −0,0363 [−0,0970, +0,0243] | **−0,0018** [−0,0291, +0,0255] |
| 12 gesehene (Stand 0311) | 8 226 / 6 351 | −0,0133 | −0,0093 | +0,0040 [−0,0228, +0,0307] |

Tor 1 (absolut profitabel) und Tor 2 (echte Verbesserung) beide gefallen; auf den neuen
Märkten kehrt der Effekt das Vorzeichen um. Die Prognose der Time Machine korreliert auch
dort negativ mit dem Ergebnis (Spearman −0,078). Schwanz des Arms: 69,6 % der Märkte
negativ, größter Rückgang 944 R, schlechtester Markt C98USDT −0,274 R. Erwartung war vorab
„eher fallen“. Damit ist am Skill nichts mehr offen. Register-Hinweis für den Kollegen:
`total_comparisons` 83 → 86 nicht eingetragen (Register gehört ihm).

## Grenzen (UNBEKANNT / MODELLIERT)

- US-Intraday nur 60 Tage; das Langzeiturteil für ORB stützt sich auf Krypto (5 Jahre).
- US-Universum heute liquider Titel → Survivorship; durch Querschnitt-Vergleich gemildert.
- Kosten modelliert: Krypto 10 bp Round Trip (unser bestätigtes Modell), US 4 bzw. 10 bp.

## Reproduktion

Skripte: `research/day_trader_skill_eval/` im Projekt (Code `cb0c355`). Erwartet das Repo
unter `../ext/day-trader-skill` relativ zum Skriptordner; Ergebnisse in `results/`.
`validate.py` zuerst (muss 33 / 13 / 15 / 5 zeigen), dann `crypto_orb.py ny|utc`,
`tm_on_ours.py`, `fetch_us.py`, `us_eval.py a|b`, `crypto_daily.py`, `analyse.py`.
