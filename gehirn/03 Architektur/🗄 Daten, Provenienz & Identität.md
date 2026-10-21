---
typ: produkt-teil
projekt: TradingBrain
bereich: architektur
status: aktiv
aktualisiert: 2026-10-18
tags: [daten, provenance, decision-id]
---

# Daten, Provenienz & Identität

Jeder entscheidungsrelevante Datensatz braucht mindestens Quelle/Venue, Markt, Zeitstempel, Schema-Version, Erfassungszeit und ein prüfbares Manifest. Inferenzierte Herkunft wird als Inferenz markiert und mit Beleg gespeichert.

## Unverhandelbare Invarianten

- Ein Fill ohne `decision_id` ist nie erlaubt.
- Code-, Konfigurations-, Daten- und Entscheidungsidentität sind getrennte Felder.
- Gleiche Counts ersetzen keine referenzielle Integrität.
- Upserts dürfen keine historische Identität still überschreiben.
- Zeitstempel brauchen Semantik und Zeitzone.
- Legacy-Daten bleiben lesbar, werden aber nicht still als V2- oder Live-Wahrheit ausgegeben.
- Rohdaten und eingefrorene Auswertungsartefakte werden nicht nachträglich umgeschrieben.

