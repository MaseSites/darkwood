---
typ: produkt-teil
projekt: TradingBrain
bereich: architektur
status: aktiv
aktualisiert: 2026-10-18
tags: [portfolio, simulation, accounting]
---

# Portfolio- und Simulationsmotor

Der gemeinsame Portfolio-Motor muss Kapital, gleichzeitig gebundenes Risiko, Korrelation, Margin, Liquidität und Reihenfolge der Entscheidungen gemeinsam simulieren. Zwölf getrennte Symbolkonten sind kein Ersatz für ein gemeinsames 1.000-CHF-Konto.

## Ergebnisfelder

- `gross_market_r`
- `modeled_execution_cost_r`
- `funding_r`
- `conditional_simulated_net_r`
- `realized_live_net_r`
- `fill_rate` und `fill_uncertainty`

Der Legacy-Bestand kann Slippage nicht sauber von Preisbewegung trennen, weil sie bereits in den Fillpreisen steckt. Neue Daten müssen deshalb unverschlechterte Referenzpreise zusätzlich speichern. Simulationsergebnisse tragen immer die Annahme “unter bedingtem Fill-Modell”; Live-Ergebnisse entstehen nur aus reconcilierten Exchange-Fills.

