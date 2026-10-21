---
typ: produkt-teil
projekt: TradingBrain
bereich: architektur
status: aktiv
aktualisiert: 2026-10-18
tags: [architektur, system]
---

# Systemarchitektur

TradingBrain wird als Mess- und Ausführungssystem in getrennten Ebenen geführt:

1. Datenerfassung und Provenienz
2. Markt-/Signalberechnung
3. Entscheidung mit unveränderlicher `decision_id`
4. Portfolio- und Risikofreigabe
5. Venue-/Environment-Bindung
6. Order- und Execution-Lifecycle
7. Journal, Attribution und Reconciliation
8. Monitoring, Alarme und Kill-Switch

Ein Fill ohne referenzierbare Entscheidung ist unzulässig. Referenzintegrität muss über die Kette erhalten bleiben; bloß gleiche Counts genügen nicht. Paper, Testnet und Mainnet sind getrennte Umgebungen und dürfen weder Speicher noch Identitäten stillschweigend vermischen.

