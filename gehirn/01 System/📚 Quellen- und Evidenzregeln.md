---
typ: produkt-teil
projekt: TradingBrain
bereich: system
status: verbindlich
aktualisiert: 2026-10-18
tags: [quellen, evidenz, research]
---

# Quellen- und Evidenzregeln

Für jede wichtige Behauptung werden Quelle, Abrufdatum, Gültigkeitsbereich und Belegstufe festgehalten. Bei Börsen- und API-Semantik haben offizielle Venue-Dokumentation und eigene API-Antworten Vorrang vor Blogs oder Erinnerungswissen.

Eine Strategiemessung ist erst vergleichbar, wenn mindestens diese Felder feststehen:

- `decision_id`, Codeversion und Datenmanifest
- Venue, Markt, Zeitraum und Zeitebene
- Signal-/Entry-/Exit-Regel
- Gebühren, Funding, Slippage und Fill-Proxy
- Risiko- und Portfolio-Kontext
- in-sample, out-of-sample oder live/paper
- Unsicherheitsintervall und Mehrfachtest-Korrektur

Ergebnisse werden in die getrennten Größen `gross_market_r`, `modeled_execution_cost_r`, `funding_r`, `conditional_simulated_net_r` und — nur bei echten Fills — `realized_live_net_r` aufgeteilt. Wenn Legacy-Daten diese Trennung nicht erlauben, wird das ausdrücklich als `UNBEKANNT` markiert und nicht geschätzt.

