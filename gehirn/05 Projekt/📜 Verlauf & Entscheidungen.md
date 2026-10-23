---
typ: produkt-teil
projekt: TradingBrain
bereich: projekt
status: aktiv
aktualisiert: 2026-10-23
tags: [verlauf, entscheidungen]
---

# Verlauf & Entscheidungen

## 2026-10-18 — Eigenes TradingBrain-Gehirn angelegt

- von: ChatGPT/Codex
- Projektstand: `c88553f`; Claudes uncommittete Phase-2-Arbeit blieb unberührt
- Entscheidung: TradingBrain erhält ein eigenes kanonisches Obsidian-Vault unter `C:\Users\sever\OneDrive\Desktop\traidingBrainGehirn`.
- Migration: fünf TradingBrain-Business-Notizen und zwei zugehörige Claude-Session-Notizen wurden unverändert kopiert und per SHA-256 verifiziert.
- Folge: Das frühere MASESites-Vault ist für TradingBrain nur noch Herkunftsarchiv und Wegweiser.

Ältere Chronologie und Entscheidungen sind verlustfrei im [[🧾 Migrationsinventar]] und den dort aufgelisteten Originalnotizen erhalten.

## 2026-10-18 — unabhängige Prüfung von Briefing 03

- von: ChatGPT/Codex
- Projektstand: `024207f`; Claudes laufende uncommittete Replay-/Fill-Provenienz-Arbeit blieb unberührt
- Befund: Die Strategiefamilie ist für das 20×-Ziel entscheidungspraktisch erschöpft; weitere Varianten derselben Familie sind nicht gerechtfertigt.
- Korrektur: Briefing 03 vermischte 51 Gelegenheiten bis 30.10. mit dem Sechsmonatsfenster. Korrekt sind rund 662 Trades und mindestens +0,4536 R bei 1 % Risiko; für A D1+H4 401 Trades und +0,7499 R.
- Grenze: Das Urteil beendet diese Familie, nicht die Suche nach nachweislich anderen Ertragsmechanismen.


## 2026-10-19 — Zweites Papierkonto (Plan 30 % × 7×) und zwei Anzeigefehler

- von: Claude
- Projektstand: `0d12eba`, `103907f` auf `freqtrade-core`
- Auftrag des Nutzers: eigenes Papierkonto mit 1.000 CHF, 30 % Margin bei 7× Hebel,
  aufstockend; Ansichten beider Konten getrennt, **ohne zu löschen**.
- `BELEGT` — das Plankonto läuft getrennt: eigener Speicher `data/plan_paper.sqlite`,
  eigene Laufsignatur (`…|plan30x7`), eigener Risikodeckel im Sizer
  (`forward_sizer(max_risk_share=0.35)`, lehnt ab statt zu kürzen). Der produktive
  3-%-Deckel auf dem Budgetpfad ist unberührt — die Vorwärtsregel liest kein Budget.
- `BELEGT` — vor dem Start gemessen (`scripts/run_plan_account.py`, dieselbe Regel über
  die 7.335 Replay-Trades): Höchststand 9.695 CHF nach 410 Trades, Kontoboden nach 787;
  über 300 Umordnungen endeten **0 %** über dem Start. Das Konto läuft trotzdem, weil es
  Papierhandel und ausdrücklich beauftragt ist — und **getrennt**, damit seine Zahl nur
  für sich selbst spricht.
- `BELEGT` — geteiltes Journal, getrennte Ansichten: `build_ledger` und `build_curve`
  lasen ungefiltert und zeigten dem Plankonto die 33 Trades des bestehenden. Damit ist
  dieselbe Verwechslung an **fünf** Ansichtsstellen gefunden worden. Die Risikologik hat
  nie gemischt (`closed_trades(signature=…)`). Gelöscht wurde nichts.
- `BELEGT` — `/api/state` las `services.account`, ein Feld, das im Betrieb niemand setzt.
  Das Kopffeld beider Dashboards meldete darum dauerhaft „A risk limit is blocking new
  trades", während der Händler handelte. Eine Warnung ohne Gegenzustand ist keine Warnung.
- `BELEGT` — dahinter ein zweiter Fehler, erst nach Behebung des ersten sichtbar: das
  Dashboard rechnete seine drei Verlustsicherungen gegen
  `config.engine.simulation.initial_equity` (1.000, der Startwert **eines** Marktes)
  statt gegen die 11.775 des Kontos. Tagesdeckel 54 statt rund 589, elffach zu eng.
  Quelle ist jetzt `account_equity`. **Der Händler war nie betroffen** — er liest
  `broker.equity` (`live/paper.py:833`); das Tor gilt nur für Handbestätigungen.
- `BELEGT` — beide Behebungen gegengeprüft durch Rückmutation auf den alten Code: alle
  fünf neuen Tests fallen dann mit genau dem Symptom. `system_state` und `kontostand`
  stehen jetzt auf Modulebene — vorher nur über einen laufenden Server erreichbar, was
  der Grund war, dass keiner von beiden geprüft war.
- Grenze: Dies sind Mess- und Anzeigekorrekturen. **Keine** Aussage über Profitabilität
  des Plankontos; es hat zum Zeitpunkt dieser Notiz null abgeschlossene Trades.

## 2026-10-21 — Code und Gehirn im Repo MaseSites/darkwood

- von: Claude
- Projektstand: `8207355` auf `master` und `layout`
- Entscheidung: Das ganze Projekt samt Darkwood Terminal liegt zusätzlich in
  `https://github.com/MaseSites/darkwood` (`master` ist Standard-Branch). Das Gehirn
  liegt dort als Ordner `gehirn/`, damit der Kollege es mit demselben `git pull` bekommt
  wie den Code und in Obsidian als Vault öffnen kann.
- Ablauf: Geschrieben wird weiter **nur hier im Vault**. `python scripts/sync_gehirn.py`
  spiegelt den Vault nach `gehirn/`, committet nur diesen Ordner und pusht den aktuellen
  Branch nach `darkwood`. Die Spiegelung läuft in eine Richtung: Änderungen in `gehirn/`
  überschreibt der nächste Lauf.
- Risiko: Das Repo `darkwood` war beim Push **öffentlich** — Code, Forschung und dieses
  Gehirn sind damit für alle lesbar, bis es auf privat gestellt ist.

## 2026-10-21 — Externer Day-Trader-Skill geprüft und verworfen

- von: Claude
- Projektstand: `cb0c355` (Branch `layout`); keine Config, kein Entscheidungspfad berührt
- Befund: ORB des Skills auf Krypto über 5 Jahre verlässlich negativ (−0,042 R brutto, NY;
  −0,026 R, UTC) und schlechter als Zufallseinstieg; auf US-Aktien −0,014 R brutto, netto
  negativ; seine Time Machine sortiert unsere 7 310 Replay-Trades leicht falsch herum.
- Entscheidung: nicht einbauen. Details in [[🧾 Day-Trader-Skill (TikTok) — Prüfung 21.10.2026]].

## 2026-10-22 — E-TM: Time-Machine-Filter auf 56 ungesehenen Märkten gefallen

- von: Claude
- Projektstand: `cb0c355` (Branch `layout`); Daten `data/replay_fills_0311`, vorregistriert
- Befund: Arm „Stop-Tendenz weg“ −0,0363 R gegen Basis −0,0345 R, Differenz −0,0018 R
  [−0,0291, +0,0255]; beide Tore gefallen, Vorzeichen auf neuen Märkten umgekehrt.
- Entscheidung: Auch dieser letzte Teil des Skills kommt nicht ins System. Kein
  Handelsparameter geändert. Register `total_comparisons` 83 → 86 bleibt für den Kollegen.

## 2026-10-22 — Name: Darkwood Terminal statt TradingBrain

- von: Claude, auf Anweisung des Eigentümers
- Entscheidung: Das Projekt heisst **Darkwood Terminal** — gemeint ist immer das ganze
  System (Oberfläche, Bot, Konten, Analyse, Daten, Betrieb), nicht mehr „TradingBrain“.
- Grenze: Technische Namen (Ordner `traidingBrain`, Paket `traidingbrain`, Aufgaben
  `traidingBrain-*`, Vault `traidingBrainGehirn`) bleiben vorerst; Umbenennen wäre ein
  eigener Schritt, weil Pfade, Aufgabenplanung und Signaturen daran hängen.

## 2026-10-23 — Einrichtungspaket für den Kollegen

- von: Claude
- Stand: Code-Commit `d1d104e` (darkwood `master`), Daten vom 23.10. etwa 08:45
- Entscheidung: Der Kollege bekommt **einen** Download,
  `OneDrive\Darkwood Paket\darkwood-paket-2026-10-23.zip` (3,9 GB). Darin liegt ein
  Git-Klon von darkwood mit `.git` und dazu alles, was Git nicht trägt: `data/`
  (Marktdaten, alle Datenbanken als SQLite-Backup-Schnappschuss), `config_offen/plan.yaml`,
  `freqtrade/user_data/` und `.env`. Danach kommt jede Änderung nur noch mit `git pull`.
- Einrichtung: `CLAUDE-EINRICHTEN.md` (im Zip und daneben) ist ein Prompt für Claude Code
  beim Kollegen. Er legt venv und Pakete an, richtet den Autostart **nur** für
  `traidingBrain-plankonto` und `traidingBrain-dash-plan` ein und prüft Terminal,
  Bot und Claude-CLI.
- Nicht im Paket: `data/quarantine/` (11 GB Messdaten), `data/dienst/` (enthält Pfade
  dieses Rechners), `.venv`, Lock-Dateien.
- Grenze: Gleich ist nur der Moment des Pakets. Der Bot des Kollegen führt danach ein
  eigenes Papierkonto. Die Keys liegen im Zip, deshalb nur mit „Bestimmte Personen“
  freigeben, nie über GitHub.

