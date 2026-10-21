---
typ: produkt-teil
projekt: TradingBrain
bereich: architektur
status: aktiv
aktualisiert: 2026-10-18
tags: [risiko, hebel, kapital]
---

# Risiko, Hebel & Kapital

Der Eigentümer akzeptiert ein hohes Verlustrisiko und will relevante Kontogrößen pro Trade einsetzen. Diese Vorgabe wird als zu prüfende Kapitalpolitik modelliert, nicht als Begründung, Schutzmechanismen oder Mathematik auszublenden.

## Getrennte Größen

- Kontorisiko bis zum Stop in CHF und Prozent
- Margin-Einsatz
- gehebeltes Notional
- effektive Liquidationsdistanz
- Portfolio-Risiko aller gleichzeitig offenen Positionen
- Gebühren, Funding, Slippage und Liquiditätswirkung

Ein Beispiel “250 CHF Margin mit 10× Hebel” ist nicht automatisch “250 CHF Risiko”: Risiko hängt von Stop, Gap, Liquidation, Ausführbarkeit und Korrelation ab. Jede aggressive Policy braucht Risk-of-Ruin-Verteilung, Drawdown-Verhalten, Verlustserien, Stresspfade, tägliche/gesamte Verlustschranke und technisch getesteten Kill-Switch.

