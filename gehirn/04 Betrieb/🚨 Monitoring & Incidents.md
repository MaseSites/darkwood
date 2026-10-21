---
typ: produkt-teil
projekt: TradingBrain
bereich: betrieb
status: entwurf
aktualisiert: 2026-10-18
tags: [monitoring, incidents, alerts]
---

# Monitoring & Incidents

## Zu überwachen

- Prozesszustand und Heartbeats
- Markt- und Kontodatenfrische
- Uhrabweichung
- API-Fehler, Rate Limits und Authentifizierungsfehler
- Orderzustände, Rejects, Cancels und Reconciliation-Differenzen
- Exposure, Margin, Liquidationsabstand und Korrelationskonzentration
- täglicher/rollierender PnL, Drawdown und Policy-Verstöße
- Daten-, Feature- und Modell-Drift
- Version von Code, Konfiguration, Modell und Entscheidungspfad

Ein Alarm braucht Schweregrad, Empfänger, Runbook, automatische Schutzreaktion und Kriterium für Wiederfreigabe. Ein Incident wird nach [[🚨 Vorlage — Incident]] erfasst; Ursachen dürfen nicht aus dem bloßen Ausgang eines Trades abgeleitet werden.

