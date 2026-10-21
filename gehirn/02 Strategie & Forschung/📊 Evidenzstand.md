---
typ: produkt-teil
projekt: TradingBrain
bereich: forschung
status: aktiv
aktualisiert: 2026-10-21
tags: [evidenz, p0a, ergebnisse]
---

# Evidenzstand

## Belegt

- Die vorhandene Legacy-Gesamtpopulation weist im gespeicherten Modell keine ausreichende positive Kante aus.
- Gebührenänderungen verbessern dieselben Fills messbar, aber viel zu wenig, um die Ziel-Lücke zu schließen.
- Maker-Annahmen und konkrete Fill-Wahrscheinlichkeiten sind historisch nicht bewiesen.
- Ein signaltheoretischer Marktausgang und die Ausführbarkeit der eigenen Order sind zwei verschiedene Ebenen.

- Die Bewertungsschicht (Rating, Band, Einigkeit, Widerspruch, Richtung gegen Gesamtbild, Regime) trennt über 7'335 Replay-Trades auf zwölf Märkten keine Teilmenge, die die Auflösung von 0,077 R überschreitet (21.10.2026). Sie beschreibt die Indikatorlage, sie prognostiziert nicht.
- Muster aus den 54 Live-Trades (Shorts im Aufwärtstrend, Widerspruch, Nachtstunden) sind im Replay nicht vorhanden. Eine Regel aus dem Handelsbuch braucht das Replay als Gegenprobe, sonst ist sie eine Beschreibung einer Nacht.
- Der einzige Befund mit Intervall ohne Null bleibt der Kostenanteil (billig besser, brutto +0,0561 R). Das Plankonto handelt mit offenem Kostentor dagegen; seine −0,319 R je Trade entsprechen der gemessenen Erwartung der teuren Population (−0,2111 R).

## Modelliert

- Wachstums- und Ruinpfade hängen gekoppelt von Kante, Einsatzanteil, Hebel, Korrelation, Kosten, Verlustserien und Fillrate ab. Einzelne Zielrechnungen ohne diese Kopplung sind unvollständig.
- Taker/Taker plus Slippage kann als konservative Kostenschranke dienen, beweist aber keine Fillrate.

## Unbekannt

- Realisierte Live-Netto-Kante unter eigener Mainnet-Ausführung.
- Eigene Queue-Position und historische PostOnly-Fillrate.
- Stabilität einer positiven Kante über Regime, Venues und zukünftige Daten.
- Ob die laufende Vorwärtsstichprobe nach ihrem vorab definierten Abschlusskriterium positiv bleibt.

## Ablehnungsregel

Ein Arm oder Feature wird nicht aufgrund einer guten Einzelzahl übernommen. Er braucht vorab definierte Auswertung, getrennte Validierung, realistische Execution-Kosten und eine dokumentierte Entscheidung. Forschungsmisserfolge bleiben im [[🧪 Experimentregister]], damit sie nicht später erneut als neue Idee verkauft werden.

## Unabhängige Prüfung von Briefing 03 — 2026-10-18

`BELEGT` — Briefing 03 vermischt zwei Horizonte. **51 Gelegenheiten** gehören zum kurzen Fenster bis 30.10.2026, nicht zu sechs Monaten. Bei 182 Tagen und 3,64 Trades/Tag ergeben sich rund **662 Trades**. Bei 1 % konstantem Kontorisiko verlangt Faktor 20 dann unter der optimistischen Annahme eines konstanten R je Trade **+0,4536 R**. Bei nur 51 Trades wären **+6,0499 R** nötig; +0,42 R über 51 Trades ergeben lediglich Faktor **1,2383**.

`BELEGT` — Für den Kandidaten A D1+H4 gilt seine eigene niedrigere Kadenz: 401 Trades verlangen **+0,7499 R**. Gegen +0,0856 R in-sample ist das Faktor **8,76**, gegen +0,0728 R unter realistischerer Ausführung Faktor **10,30**.

`ENTSCHEIDUNGSVORSCHLAG` — Die untersuchte Familie aus direktionalen Preisstruktur-Setups auf Perpetuals ist für das Ziel 1.000 → 20.000 in sechs Monaten als **erschöpft** zu schließen. Das ist kein universeller Beweis „Trading funktioniert nicht“, sondern eine Entscheidung, keine weiteren Wochen in Parameter-, Exit-, Kosten-, Daten- oder Selektionsvarianten derselben Familie zu investieren.

`OFFEN, ABER NICHT ZIELRETTEND` — Die registrierte E2-Frage einer zustandsbehafteten Halte-/Nicht-Handelszone ist sequenziell noch nicht sauber beantwortet. Sie kann hauptsächlich Umschlag und Maut reduzieren; die Nullgebühren-Obergrenze zeigt, dass sie die erforderliche Größenordnung nicht plausibel liefert. Potenziell materielle Event-, Relative-Value-, Options-, Market-Making- oder Arbitrageansätze wären neue Strategiefamilien und dürfen nicht als weitere Optimierung dieser Familie ausgegeben werden.

