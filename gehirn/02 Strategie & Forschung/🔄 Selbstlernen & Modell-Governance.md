---
typ: produkt-teil
projekt: TradingBrain
bereich: forschung
status: entwurf
aktualisiert: 2026-10-18
tags: [selbstlernen, ml, governance]
---

# Selbstlernen & Modell-Governance

“Selbstlernen” darf niemals bedeuten, dass ein laufendes Modell nach Verlusten unkontrolliert seine Regeln ändert. Lernen und Handeln werden getrennt.

## Mindestregeln

- Produktionsmodell ist versioniert und während einer Auswertungsepoche eingefroren.
- Training erfolgt offline auf zeitlich korrekten Daten ohne Zukunftsleck.
- Kandidaten laufen zuerst Shadow/Paper und erhalten eine eigene Entscheidungs-ID.
- Promotion braucht vorab definierte Schwellen, Vergleich gegen Baseline und Rollback-Pfad.
- Kein Online-Lernen mit direkter Kapitalfreigabe.
- Feature-, Label-, Daten- und Modell-Drift werden separat überwacht.
- Ein Verlust liefert keine kausale Erklärung; Ursachen werden erst nach reproduzierbarer Analyse übernommen.

