---
typ: produkt-teil
projekt: TradingBrain
bereich: system
status: verbindlich
aktualisiert: 2026-10-18
tags: [regeln, ki, governance]
---

# Regeln für Claude, ChatGPT & Codex

## Vor jeder Arbeit

1. [[🏠 TradingBrain — Zentrale]] lesen.
2. [[📌 Aktueller Stand]] lesen.
3. Passende Fachnotiz und Primärartefakte lesen.
4. `git status`, aktuellen Commit und laufende Prozesse prüfen, bevor ein Stand behauptet wird.

## Schreibregeln

- Bestehendes korrigieren statt widersprüchliche Wahrheiten anzuhäufen.
- Exakte Zahlen nur mit Population, Zeitraum, Modell, Kostenannahme und Code-/Datenversion festhalten.
- `BELEGT`: direkt durch Primärdaten oder reproduzierbare Messung gestützt.
- `MODELLIERT`: Resultat eines expliziten Modells; Annahmen nennen.
- `HYPOTHESE`: prüfbare Vermutung ohne ausreichenden Beleg.
- `UNBEKANNT`: Daten fehlen oder Identität ist nicht rekonstruierbar.
- Legacy-Werte nie stillschweigend zu Live-Werten umdeuten.
- Archivdateien nie verändern; Korrekturen in aktuellen Notizen dokumentieren.

## Abschluss jeder Arbeit

1. Betroffene Notizen aktualisieren.
2. [[📜 Verlauf & Entscheidungen]] mit Datum, KI/Person und Projekt-Commit ergänzen.
3. In der Zentrale genau einen nächsten Schritt führen.
4. `node vault_audit.mjs` ausführen.

## Geheimnisse

Keine Secrets oder personenbezogenen Finanzdaten im Vault. Zulässig ist nur die Information, in welchem Secret-Store oder welcher lokalen Konfigurationsart sie verwaltet werden.

