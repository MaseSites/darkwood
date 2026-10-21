---
typ: produkt-teil
projekt: TradingBrain
bereich: architektur
status: aktiv
aktualisiert: 2026-10-18
tags: [venue, execution, bybit, orders]
---

# Venue & Execution

## Aktuelle Leitplanken

- Venue ist Pflichtidentität, nicht optionaler Konfigurationshinweis.
- Datenpfad und Datensatz tragen beide die Venue.
- Ein Limitpreis beweist keine Maker-Rolle.
- PostOnly kann marketable Orders ablehnen; dieser Zustand muss explizit verarbeitet werden.
- Target-/Stop-Semantik wird aus offizieller API-Dokumentation und eigenen Exchange-Antworten abgeleitet, nicht aus Simulatorannahmen.
- Tatsächliche Liquidity Role wird nur aus realen Execution-Daten übernommen.
- L1, Tape und Queue-Position sind verschiedene Evidenzebenen.
- Partial Fill, Cancel, Reject, Expiry und Reconciliation sind normale Zustände, keine Randfälle.

Policy A bleibt die ausführbare kostenkonservative Baseline, ohne dadurch historisch belegte Fill-Wahrscheinlichkeit zu erhalten. Policy B bleibt hinsichtlich Maker-Target und Queue-Verhalten zusätzlich offen.

