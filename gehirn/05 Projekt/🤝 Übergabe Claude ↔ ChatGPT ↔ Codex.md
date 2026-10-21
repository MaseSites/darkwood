---
typ: produkt-teil
projekt: TradingBrain
bereich: projekt
status: aktiv
aktualisiert: 2026-10-21
tags: [uebergabe, claude, chatgpt, codex]
---

# Übergabe Claude ↔ ChatGPT ↔ Codex

## Rollen

- Claude: primäre Implementierung im Repository, Tests und technische Zustandsberichte.
- ChatGPT/Codex: Analyse, Recherche, Gegenprüfung, Spezifikation und Pflege dieses Gehirns; Implementierung nur bei ausdrücklichem Auftrag.
- Severin: Ziel, Prioritäten, Freigaben und externe Entscheidungen.

## Übergabeformat

Jede größere Meldung enthält:

1. Commit und Arbeitsbaumstatus
2. was konkret geändert oder nur analysiert wurde
3. Tests mit exakten Ergebnissen
4. neue belegte Fakten, Modellannahmen und offene Unbekannte getrennt
5. Auswirkungen auf laufende Stichproben
6. nächste Entscheidung oder nächstes Abnahmekriterium

Keine KI behandelt die Zusammenfassung einer anderen KI als Primärbeleg. Bei wichtigen Punkten werden Code, Test oder Ursprungsartefakt gelesen. Neue dauerhafte Erkenntnisse kommen in dieses Vault, nicht nur in den Chat.

## Arbeitsteilung ab 21.10.2026: Layout hier, Analysen beim Kollegen

Entscheidung des Eigentümers: diese Claude-Session arbeitet **nur noch am
Layout** (Terminal und Dashboard). Analysen, Experimente, Strategie- und
Risikoänderungen macht ein Kollege. Damit es keine Konflikte gibt:

**Branches.** Basis ist `freqtrade-core` (gepusht am 21.10., Stand `0569ed4`).
Layout-Arbeit läuft auf dem Branch **`layout`** (angelegt und gepusht am
21.10.). Analysen laufen auf einem eigenen Branch des Kollegen (Vorschlag:
`analyse`), ebenfalls von `freqtrade-core`. Zusammengeführt wird nur per
Pull Request nach `freqtrade-core`, nie direkt. Vor jeder Layout-Sitzung:
`git fetch` und `freqtrade-core` in `layout` mergen, damit die Oberfläche
gegen den aktuellen Backend-Stand läuft.

**Pfade, die das Layout besitzt** (nur hier wird geändert):
- `src/traidingbrain/dashboard/static/*` (app.css, app.js, chart.js,
  position-chart.js, terminal.css, terminal.js, terminal-chart.js,
  terminal-faktor.js, terminal-indikatoren.js, terminal-zeichnen.js)
- `src/traidingbrain/dashboard/templates/index.html`, `terminal.html`

**Pfade, die der Kollege besitzt** (Layout fasst sie nicht an):
- `src/traidingbrain/{analysis,sim,strategy,strategies,risk,journal,learn,score,live,data}/`
- `scripts/`, `audit/`, `config/`, `config_offen/`, `tests/` (ausser reine
  UI-Tests), `data/`

**Geteilte Pfade, mit Absprache:** `src/traidingbrain/api/*` (vor allem
`terminal.py`, `portfolio.py`, `market.py`, `chart.py`). Das Layout darf dort
nur **lesende Endpunkte für die Anzeige** ergänzen oder Antwortfelder
erweitern, nie Entscheidungs- oder Kontologik. Jede Änderung an `api/` wird
in der PR-Beschreibung genannt; wer zuerst mergt, der andere rebased.

**Regeln, die auch für das Layout gelten:** keine erfundene Zahl im Chart;
jede Anzeige nennt ihre Quelle; Warnungen, die immer leuchten, sind keine
(`a-warning-that-always-lights-up`); Entscheidungsstempel und Laufsignatur
bleiben unberührt, weil Layout-Dateien nicht im Entscheidungspfad liegen.

**Betrieb, der aus der Analysephase noch offen ist** (Übergabe an den
Kollegen, bitte in dieser Reihenfolge):
1. Kill-Switch `data/KILL_SWITCH` ist seit 21.10. 11:10 UTC gesetzt. Ein
   Wächter startet den Händler beim flachen Konto mit der neuen Konfiguration
   neu (`|tf=D1,H4,H1|bild`, Kostentor 0,08). **Danach die Datei löschen**,
   sonst handelt er nicht. Prüfen: neue Signaturzeile im
   `data/dienst/traidingBrain-plankonto.log`.
2. E24 (Takt-Balken) rechnet in drei Strängen; danach
   `python scripts/study_e24_takt.py --auswerten`, Ergebnis ins Register.
3. E25 (Lighter-Beständigkeit) ab 27.10. ~09 h auswertbar; E26-Sammler läuft;
   E27 ist der Vorwärtstest der neuen Epoche, keine Anpassung vor 100 Trades.
