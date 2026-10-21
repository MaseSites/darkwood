# TradingBrain-Gehirn — verbindliche Arbeitsregeln

Dieses Verzeichnis ist das eigenständige, kanonische Obsidian-Gehirn für das Projekt **TradingBrain**.

Vor jeder Arbeit:

1. `00 Start/🏠 TradingBrain — Zentrale.md` vollständig lesen.
2. `00 Start/📌 Aktueller Stand.md` vollständig lesen.
3. Die zum Thema passende Notiz lesen; bestehende Entscheidungen nicht neu erfinden.
4. Für exakte Implementierungsdetails und Messwerte den Code beziehungsweise die dort verlinkten Audit-Artefakte prüfen. Bei Widerspruch gewinnt der Code oder das Primärartefakt; anschließend die Notiz korrigieren.

Während und nach der Arbeit:

- Wissen in die passende Fachnotiz einarbeiten; Widersprüchliches ersetzen statt unkommentiert anzuhängen.
- Jede Tatsachenbehauptung als `BELEGT`, `MODELLIERT`, `HYPOTHESE` oder `UNBEKANNT` behandeln.
- Frontmatter `aktualisiert: JJJJ-MM-TT` aktualisieren.
- Nur die Zentrale trägt `projektordner`; Unter-Notizen tragen `typ: produkt-teil`.
- In `05 Projekt/📜 Verlauf & Entscheidungen.md` Datum, Urheber und Projekt-Commit festhalten.
- Genau einen `naechster_schritt` in der Zentrale führen.
- Keine Passwörter, API-Schlüssel, Tokens, `.env`-Inhalte, Kontonummern oder privaten Zugangsdaten speichern. Nur dokumentieren, wo ein Secret verwaltet wird.
- Das Verzeichnis `90 Archiv — Migration 2026-10-18` ist unveränderliches Migrationserbe. Nicht redigieren.
- Abschließend im Vault-Stamm `node vault_audit.mjs` ausführen.

