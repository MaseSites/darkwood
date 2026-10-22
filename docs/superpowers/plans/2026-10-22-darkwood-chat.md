# Darkwood-Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Chat-Seitenfeld im Darkwood Terminal, in dem der Nutzer mit dem Bot spricht; feste Regeln nehmen Trade-Vorschläge an oder lehnen sie ab, und ein angenommener Vorschlag wird nach Klick und Neuprüfung als manuelle Papier-Order ausgeführt.

**Architecture:** Neues Paket `src/traidingbrain/api/chat/` mit sieben Modulen (Typen, Konto, Prüfung, Lagebild, Sprecher, Speicher, Router), eingehängt als Router in `api/app.py`. Die Prüfung ist eine reine Funktion über ein `Lage`-Objekt; Claude (CLI) liefert nur Text und einen Vorschlag, nie das Urteil. Die Oberfläche ist ein eigenes JS/CSS-Paar, eingebunden in `terminal.html`.

**Tech Stack:** Python 3.14, FastAPI, pydantic v2, sqlite3, pytest; Claude-CLI über `brain/subscription.py`; Vanilla-JS wie `terminal.js`.

**Spec:** `docs/superpowers/specs/2026-10-22-darkwood-chat-design.md`

## Global Constraints

- Branch `layout`. Keine Datei in `config/`, `config_offen/`, `risk/`, `live/`, `strategy*/`, `journal/` wird geändert.
- Schreibzugriff nur auf `data/chat.sqlite` und (über `order_oeffnen`) `data/manual_paper.sqlite`. Nie auf `data/plan_paper.sqlite`, `data/journal.sqlite`, `config*/`.
- Das Urteil kommt ausschliesslich aus `pruefe(...)`. Claude-Ausgabe kann es nicht setzen.
- `unbekannt` zählt wie `verletzt`. Angenommen ⇔ keine Regel `verletzt` oder `unbekannt`.
- Regelwerte aus der laufenden Konfiguration (`services.config`, `config_offen/plan.yaml`), nie im Chat-Code dupliziert.
- Manuelles Konto: Start `1000.0` USD plus `pnl` der geschlossenen Zeilen in `manual_paper.sqlite`; die Zahl steht als `MANUELL_START = 1000.0` einmal in `api/chat/konto.py`.
- Karten-Ablauf `config.risk.execution.proposal_ttl_seconds` (900), Kursdrift `config.risk.execution.max_price_drift_bps` (15).
- Kosten: `KOSTEN_ROUNDTRIP` aus `api/terminal.py` (0.001), Kosten = Notional × KOSTEN_ROUNDTRIP.
- UI im Darkwood-Stil (`terminal.css`-Tokens), Seitenfeld 380 px, < 768 px Vollbild. Skills `ui-ux-pro-max` → `emil-design-eng` → `anti-slop-ajonai` (Prüfskript `scripts/check.mjs` am Ende).
- Texte im UI auf Deutsch, Zahlen mit `money()`/`px()` aus `terminal.js`.
- Tests: `.venv/Scripts/python.exe -m pytest`. Kein Test ruft die echte CLI oder Binance auf.

## Review Focus

1. **Vorschlag ohne Margin oder Hebel** („BTC long") — erwartet: Margin = Plan-Regel (`margin_share × manuelles Kapital`), Hebel = Plan-Hebel; nie Absturz. Test in Task 3.
2. **Symbol, dem das Terminal nicht folgt** („PEPE long") — erwartet: Regel 3 `unbekannt`, abgelehnt mit Satz „Markt wird nicht beobachtet". Test in Task 4.
3. **Kartenausführung nach Dashboard-Neustart** — erwartet: Karte aus `chat.sqlite` gelesen, Ablauf gilt weiter. Test in Task 6.
4. **Claude liefert Vorschlag mit Kleinbuchstaben-Symbol oder `BTC` statt `BTCUSDT`** — erwartet: normalisiert auf `BTCUSDT`. Test in Task 5.
5. **Zwei schnelle Nachrichten, während Claude noch denkt** — erwartet: zweite Anfrage wird abgewiesen (409 „Claude antwortet noch"), UI zeigt es. Test in Task 7.

---

### Task 1: Typen des Chats

**Files:**
- Create: `src/traidingbrain/api/chat/__init__.py` (leer)
- Create: `src/traidingbrain/api/chat/modelle.py`
- Test: `tests/test_chat_modelle.py`

**Interfaces:**
- Produces (alle pydantic `BaseModel`):
  - `Vorschlag(symbol: str, side: Literal["long","short"], margin_usd: float | None = None, leverage: float | None = None, sl: float | None = None, tp: float | None = None)`; Validator normalisiert `symbol` auf Grossbuchstaben und hängt `USDT` an, wenn es fehlt.
  - `Setup(timeframe: str, side: str, entry: float, stop: float, target: float)`
  - `Regel(nr: int, name: str, status: Literal["erfuellt","verletzt","unbekannt"], wert: str, grenze: str, hinweis: str | None = None)`
  - `Urteil(angenommen: bool, regeln: list[Regel], order: OrderWunsch | None, stop_vom_bot: bool, preis: float | None)` — `OrderWunsch` aus `api/terminal.py`.
  - `Regelwerte(require_agreement: bool, timeframes: list[str], margin_share: float, leverage: float, risk_cap_share: float, max_cost_fraction: float, max_leverage: float, kosten_roundtrip: float)`
  - `Lage(symbol: str, timeframe: str, preis: float | None, bild: Literal["long","short","neutral"] | None, setups: list[Setup] | None, folgt: bool, konto: AccountState, quellen: dict[str, str], kontext: dict)` mit `model_config = ConfigDict(arbitrary_types_allowed=True)`; `None` heisst „unbekannt".

- [ ] **Step 1: Write the failing test** — `test_vorschlag_normalisiert_symbol`: `Vorschlag(symbol="btc", side="long").symbol == "BTCUSDT"`; `Vorschlag(symbol="ethusdt", side="short").symbol == "ETHUSDT"`; `side="buy"` wirft `ValidationError`.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_chat_modelle.py -v` → FAIL (ModuleNotFoundError).
- [ ] **Step 3: Implement** die Modelle in `modelle.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git add src/traidingbrain/api/chat tests/test_chat_modelle.py && git commit -m "Chat: Typen fuer Vorschlag, Regel, Urteil, Lage"`

### Task 2: Kontostand des manuellen Papierkontos

**Files:**
- Create: `src/traidingbrain/api/chat/konto.py`
- Test: `tests/test_chat_konto.py`

**Interfaces:**
- Consumes: Tabelle `positions` in `manual_paper.sqlite` (Schema in `api/terminal.py:_manuell_db`).
- Produces:
  - `MANUELL_START = 1000.0`
  - `manuelles_konto(db: Path, *, jetzt_ms: int, bot_positionen: list[tuple[str, str]]) -> AccountState` — `equity = MANUELL_START + Σ pnl (status='closed')`; `recent_trades` und `history` aus geschlossenen Zeilen als `ClosedTrade` (`state=TradeState.CLOSED_MANUAL`, `snapshot_hash="manuell"`, `funding=0.0`, `r_multiple` wie `_manuell_geschlossen`); `open_positions` = offene manuelle Zeilen **plus** `bot_positionen` (`(symbol, side)`), jeweils als `Position(..., liquidation_price=entry, opened_ts=…)`; Start heute/Woche über `AccountState.from_history`.
  - `bot_positionen(state_path: Path, symbole: list[str]) -> list[tuple[str, str]]` — liest `PaperStateStore(state_path).load(s)`, nimmt `state.position.side` wo `position` gesetzt.

- [ ] **Step 1: Write failing tests** (Datei-DB in `tmp_path`, Schema per `_manuell_db`-Statement):
  - `test_leeres_konto_steht_bei_1000`: keine Zeilen → `equity == 1000.0`, `open_positions == []`.
  - `test_geschlossene_pnl_zaehlt`: zwei geschlossene Zeilen `pnl=+30.0` und `-12.5` → `equity == 1017.5`, `len(recent_trades) == 2`.
  - `test_bot_positionen_zaehlen_mit`: eine offene manuelle BTC-long-Zeile + `bot_positionen=[("ETHUSDT","short")]` → `{(p.symbol, p.side.value) for p in open_positions} == {("BTCUSDT","long"),("ETHUSDT","short")}`.
- [ ] **Step 2: Run** `pytest tests/test_chat_konto.py -v` → FAIL.
- [ ] **Step 3: Implement** beide Funktionen.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Chat: Kontostand des manuellen Papierkontos (Start 1'000)"`

### Task 3: Regelprüfung

**Files:**
- Create: `src/traidingbrain/api/chat/pruefung.py`
- Test: `tests/test_chat_pruefung.py`

**Interfaces:**
- Consumes: `Vorschlag`, `Lage`, `Regelwerte`, `Urteil`, `Regel` (Task 1); `RiskLimits` aus `risk/limits.py`; `OrderWunsch` aus `api/terminal.py`.
- Produces:
  - `regelwerte_aus(config: AppConfig, plan: dict) -> Regelwerte` — `require_agreement=config.engine.setups.require_agreement`, `timeframes=config.engine.setups.timeframes`, `margin_share=plan["margin_share"]`, `leverage=plan["leverage"]`, `risk_cap_share=plan["risk_cap_share"]`, `max_cost_fraction=config.risk.limits.max_cost_fraction_of_risk`, `max_leverage=config.risk.leverage.max`, `kosten_roundtrip=KOSTEN_ROUNDTRIP`.
  - `pruefe(v: Vorschlag, lage: Lage, werte: Regelwerte, limits: RiskLimits) -> Urteil` — keine I/O.

Ablauf in `pruefe` (Reihenfolge = Regelnummern der Spec):
1. Fehlende Margin → `werte.margin_share × lage.konto.equity`; fehlender Hebel → `werte.leverage`.
2. Fehlender `sl` → Stop des ersten Setups in `lage.setups` mit `side == v.side` einsetzen, `stop_vom_bot=True`.
3. Regel 1 Stop/Ziel-Seite gegen `lage.preis`; Regel 2 `lage.bild == v.side` (nur wenn `require_agreement`); Regel 3 Setup gleicher Richtung auf einer der `timeframes`; Regel 4 Risiko = `|preis − sl| × qty`, qty = margin×leverage/preis; über `risk_cap_share × equity` → Margin proportional kürzen, Status `erfuellt`, `wert` nennt „gekürzt auf X USD"; Regel 5 Kosten = notional × kosten_roundtrip ≤ max_cost_fraction × Risiko; Regel 6 und 7 = `limits.check(lage.konto, symbol=v.symbol, side=v.side)` — Blocker mit „position" im Text → Regel 6, Verlust/Pause → Regel 7; Regel 8 Hebel ≤ max_leverage.
4. Fehlt die Grundlage einer Regel (`preis`/`bild`/`setups` ist `None` oder `lage.folgt` falsch) → `unbekannt` mit `hinweis`.
5. `order` = finaler `OrderWunsch` nur bei `angenommen`.

- [ ] **Step 1: Write failing tests.** Hilfsfunktion `_lage(**ueberschreiben)` baut eine `Lage` mit `preis=82_597.0`, `bild="short"`, `setups=[Setup(timeframe="H4", side="short", entry=82_597.0, stop=83_400.0, target=81_400.0)]`, `folgt=True`, Konto 1'000 USD ohne Positionen; `_werte()` mit `require_agreement=True, timeframes=["D1","H4","H1"], margin_share=0.3, leverage=7.0, risk_cap_share=0.015, max_cost_fraction=0.08, max_leverage=10.0, kosten_roundtrip=0.001`; `RiskLimits(load_config().risk.limits)`.
  - `test_regelkonformer_short_wird_angenommen`: `Vorschlag(symbol="BTCUSDT", side="short")` → `angenommen is True`, `stop_vom_bot is True`, `order.sl == 83_400.0`.
  - `test_long_gegen_das_bild_wird_abgelehnt`: `side="long", sl=81_900.0` → abgelehnt, Regel 2 `verletzt`, Regel 3 `verletzt`.
  - `test_stop_auf_falscher_seite`: short mit `sl=81_000.0` → Regel 1 `verletzt`.
  - `test_risiko_wird_gekuerzt_nicht_abgelehnt`: short, `margin_usd=900.0`, `leverage=10.0` → Regel 4 `erfuellt`, `order.margin_usd * order.leverage * abs(82_597-83_400)/82_597 <= 15.0 + 1e-6`.
  - `test_zu_enger_stop_scheitert_an_kosten`: short, `sl=82_610.0` → Regel 5 `verletzt`.
  - `test_hebel_ueber_10_verletzt`: `leverage=20.0` → Regel 8 `verletzt`.
  - `test_fehlende_daten_sind_unbekannt_und_lehnen_ab`: `_lage(preis=None)` → abgelehnt, Regel 1 `unbekannt`.
  - `test_ohne_margin_und_hebel_gilt_die_planregel` (Review Focus 1): `Vorschlag(symbol="BTCUSDT", side="short")` → vor Kürzung Margin 300.0, Hebel 7.0 (nachweisbar über `order.leverage == 7.0`).
  - `test_deckel_urteilt_wie_risklimits`: Konto mit 5 offenen Positionen → Regel 6 `verletzt`, und `RiskLimits.check(...).allowed is False` mit derselben `AccountState`.
  - `test_claude_kann_nicht_freigeben`: Urteil hängt nur an `(v, lage, werte)` — `pruefe` hat keinen Parameter für Claude-Text; Test ruft `pruefe` zweimal mit identischen Eingaben und erwartet identische `Urteil.model_dump()`.
- [ ] **Step 2: Run** `pytest tests/test_chat_pruefung.py -v` → FAIL.
- [ ] **Step 3: Implement** `regelwerte_aus` und `pruefe`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Chat: Regelpruefung -- acht Regeln, unbekannt lehnt ab"`

### Task 4: Lagebild

**Files:**
- Create: `src/traidingbrain/api/chat/lagebild.py`
- Test: `tests/test_chat_lagebild.py`

**Interfaces:**
- Consumes: `kopf`, `kalender` (api/terminal.py); `_score_read_dict`, `_market_for`, `_followed_symbols`, `_state_path`, `_journal_path`, `_konto_signatur` (api/app.py, spät importiert wie im `/score`-Endpunkt); `manuelles_konto`, `bot_positionen` (Task 2).
- Produces: `baue_lage(services: Services, symbol: str, timeframe: str, *, jetzt_ms: int, holer: Holer | None = None) -> Lage`. `Holer` ist ein kleines `dataclass` mit den Feldern `kopf`, `score`, `markt`, `kalender` (Callables), Standard = die echten Funktionen; Tests reichen Attrappen.

Regeln: `bild` aus `score["direction"]`; `setups` = Vereinigung von `_market_for(services, symbol, tf).setups` über `config.engine.setups.timeframes`, je mit `timeframe=tf`; jede Quelle, die eine `HTTPException` oder `KeyError` wirft, wird `None` und in `quellen` als `"unbekannt: <Grund>"` vermerkt; `folgt = symbol in _followed_symbols(services)`; `kontext` enthält Score-Kopf (rating, band, regime, headline), Kalenderzeilen der nächsten 24 h, Plan-Einstellungen und die letzten 5 Journal-Trades des Markts.

- [ ] **Step 1: Write failing tests** mit Attrappen-`Holer`:
  - `test_lage_liest_bild_und_setups`: Score `direction="short"`, Markt liefert für H4 ein Short-Setup → `lage.bild == "short"`, `[s.timeframe for s in lage.setups] == ["H4"]`.
  - `test_ausgefallene_quelle_wird_unbekannt`: `kopf` wirft `HTTPException(503)` → `lage.preis is None`, `lage.quellen["kurs"].startswith("unbekannt")`.
  - `test_fremder_markt_folgt_nicht` (Review Focus 2): `symbol="PEPEUSDT"` → `lage.folgt is False`; zusammen mit `pruefe` → Regel 3 `unbekannt`, `hinweis == "Markt wird nicht beobachtet"`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `Holer` und `baue_lage`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Chat: Lagebild aus den Terminal-Quellen, Ausfall wird unbekannt"`

### Task 5: Sprecher (Claude über die CLI)

**Files:**
- Create: `src/traidingbrain/api/chat/sprecher.py`
- Create: `src/traidingbrain/api/chat/system_prompt.md`
- Test: `tests/test_chat_sprecher.py`

**Interfaces:**
- Consumes: aus `brain/subscription.py` `_cli_environment`, `_extract_json`, `CALL_TIMEOUT_S`, und die Argumentliste/Entpackung von `SubscriptionBrain._run`/`_unwrap` (nicht duplizieren: beide als Modulfunktionen `run_cli(content: str, *, executable: str) -> tuple[str | None, str | None]` und `unwrap(stdout: str) -> tuple[str | None, str | None]` herausziehen; `SubscriptionBrain` ruft sie danach selbst auf — reine Verschiebung, bestehende Tests bleiben grün).
- Produces:
  - `Antwort(text: str, vorschlag: Vorschlag | None, bedenken: list[str], fehler: str | None)`
  - `class Sprecher(Protocol): def sprich(self, nachricht: str, lage: Lage, verlauf: list[tuple[str, str]]) -> Antwort`
  - `ClaudeSprecher(lauf=run_cli)` — baut Eingabe aus `system_prompt.md`, `lage` (JSON ohne `konto`-Objekt, dafür `equity`), letzte 10 Verlaufszeilen, Nachricht; erwartet JSON `{antwort, vorschlag, bedenken}`; ungültig → genau eine Nachfrage mit zitiertem Fehler; danach `Antwort(text=…, vorschlag=None, fehler="Antwort nicht lesbar")`. Felder wie `"angenommen"` werden ignoriert.
  - `status() -> Literal["bereit","nicht_angemeldet","nicht_installiert"]` über `shutil.which("claude")` und einen gecachten Probeaufruf (60 s).
- `system_prompt.md` sagt: du sprichst für den Bot, du urteilst nicht, du darfst Bedenken nennen, Zahlen nur aus dem Lagebild, Antwort nur als JSON nach Schema.

- [ ] **Step 1: Write failing tests** mit `lauf`-Attrappe:
  - `test_vorschlag_wird_gelesen`: Attrappe liefert `{"antwort":"ok","vorschlag":{"symbol":"btc","side":"short"},"bedenken":["x"]}` → `vorschlag.symbol == "BTCUSDT"` (Review Focus 4), `bedenken == ["x"]`.
  - `test_ungueltig_dann_eine_nachfrage`: erste Antwort `"kein json"`, zweite gültig → genau 2 Aufrufe, zweiter Inhalt enthält den Fehlertext.
  - `test_zweimal_ungueltig_ohne_vorschlag`: beide ungültig → `vorschlag is None`, `fehler == "Antwort nicht lesbar"`.
  - `test_feld_angenommen_wird_ignoriert`: Antwort enthält `"angenommen": true` → `Antwort` hat kein solches Feld, `vorschlag` unverändert.
  - `test_attrappe_hat_echte_cli_form`: `unwrap` auf ein echtes Beispiel der CLI-Ausgabe (`{"type":"result","result":"{...}"}`, Form aus bestehenden `tests/test_subscription_brain.py`) liefert den inneren Text.
- [ ] **Step 2: Run** `pytest tests/test_chat_sprecher.py tests/ -k "subscription_brain or sprecher" -v` → neue FAIL, bestehende PASS.
- [ ] **Step 3: Implement** Herausziehen von `run_cli`/`unwrap`, dann `ClaudeSprecher`, `status`, Prompt-Datei.
- [ ] **Step 4: Run** dieselbe Auswahl → alles PASS.
- [ ] **Step 5: Commit** `"Chat: Sprecher ueber die Claude-CLI, urteilt nie"`

### Task 6: Verlauf und Karten

**Files:**
- Create: `src/traidingbrain/api/chat/speicher.py`
- Test: `tests/test_chat_speicher.py`

**Interfaces:**
- Produces: `ChatSpeicher(path: Path)` mit
  - `nachricht(rolle: Literal["nutzer","bot"], text: str, *, ts: int) -> None`
  - `verlauf(limit: int = 50) -> list[dict]` (je `{ts, rolle, text, karte_id}`)
  - `karte_anlegen(vorschlag: Vorschlag, urteil: Urteil, *, ts: int, ttl_s: int) -> str` (12 Hex-Zeichen)
  - `karte(karte_id: str) -> dict | None` (`{vorschlag, urteil, preis, laeuft_ab_ts, ausgefuehrt_ts, order_id}`)
  - `als_ausgefuehrt(karte_id: str, order_id: str, *, ts: int) -> bool` — atomar per `UPDATE … WHERE ausgefuehrt_ts IS NULL`; `False` beim zweiten Aufruf.

- [ ] **Step 1: Write failing tests:**
  - `test_karte_ueberlebt_neuen_speicher` (Review Focus 3): anlegen, neuen `ChatSpeicher` auf derselben Datei öffnen → `karte(id)` gleich, `laeuft_ab_ts == ts + 900_000`.
  - `test_nur_einmal_ausfuehrbar`: `als_ausgefuehrt` → `True`, zweiter Aufruf → `False`.
  - `test_verlauf_in_reihenfolge`: drei Nachrichten → `verlauf()` in Zeitreihenfolge.
- [ ] **Step 2: Run** → FAIL. **Step 3:** implementieren. **Step 4:** PASS.
- [ ] **Step 5: Commit** `"Chat: Verlauf und Pruefkarten in data/chat.sqlite"`

### Task 7: Endpunkte und Einhängen

**Files:**
- Create: `src/traidingbrain/api/chat/router.py`
- Modify: `src/traidingbrain/api/app.py` (neben `terminal_router` einhängen)
- Test: `tests/test_chat_router.py`

**Interfaces:**
- Consumes: alles aus Task 1–6; `order_oeffnen` aus `api/terminal.py`.
- Produces: `router(services, *, sprecher: Sprecher | None = None, speicher: ChatSpeicher | None = None, holer: Holer | None = None, jetzt=time.time) -> APIRouter` mit Präfix `/api/terminal/chat` und den fünf Endpunkten der Spec (Abschnitt 7). Antwortform `nachricht`/`pruefen`: `{antwort, bedenken, karte: {id, vorschlag, urteil, laeuft_ab_ts} | null}`.
- Plan-Werte: `config_offen/plan.yaml` über dieselbe Lesefunktion wie `bot_settings_lesen`.
- Sperre: ein `threading.Lock` je Prozess für `nachricht`; besetzt → `409 "Claude antwortet noch"`.
- `ausfuehren`: 404 unbekannt, 410 abgelaufen, 409 schon ausgeführt; Lage neu, `pruefe` neu; abgelehnt → `{ausgefuehrt: false, grund: <erste verletzte Regel>}`; `|preis_neu − preis_karte| / preis_karte × 10_000 > max_price_drift_bps` → `{ausgefuehrt: false, grund: "Kurs hat sich um X bp bewegt"}`; sonst `order_oeffnen(urteil.order)` und `als_ausgefuehrt`.

- [ ] **Step 1: Write failing tests** mit `TestClient`, Attrappen für `sprecher`, `holer`, `MANUELL_DB` per `monkeypatch` auf `tmp_path`, `order_oeffnen` gegen Attrappen-`kopf`:
  - `test_nachricht_mit_regelkonformem_vorschlag_liefert_karte`: Status 200, `karte.urteil.angenommen is True`.
  - `test_claude_sagt_angenommen_regel_sagt_nein`: Sprecher schlägt BTC long gegen Bild vor und schreibt „angenommen" in den Text → `karte.urteil.angenommen is False`.
  - `test_pruefen_ohne_claude`: `/pruefen` mit `sprecher`, der beim Aufruf `AssertionError` wirft → 200 mit Karte.
  - `test_ausfuehren_einmal`: zweimal `POST /ausfuehren/{id}` → 200 `ausgefuehrt: true`, dann 409; genau eine Zeile in `manual_paper.sqlite`.
  - `test_ausfuehren_abgelaufen`: `jetzt` um 901 s vorgestellt → 410.
  - `test_ausfuehren_kursdrift`: Attrappen-Kurs nach Prüfung +0.2 % → `ausgefuehrt: false`, `grund` enthält "bp".
  - `test_bot_dateien_bleiben_unberuehrt`: Hash von `plan_paper.sqlite` und `journal.sqlite` (Kopien in `tmp_path`, über `services`) vor und nach Ausführen gleich.
  - `test_zweite_nachricht_waehrend_claude_denkt` (Review Focus 5): Sprecher blockiert auf einem `threading.Event`; zweite Anfrage → 409.
- [ ] **Step 2: Run** `pytest tests/test_chat_router.py -v` → FAIL.
- [ ] **Step 3: Implement** `router.py`, Einhängen in `app.py` direkt nach `app.include_router(terminal_router(...))`.
- [ ] **Step 4: Run** `pytest tests/test_chat_*.py tests/test_api.py -v` → PASS.
- [ ] **Step 5: Commit** `"Chat: Endpunkte /api/terminal/chat, Ausfuehren mit Neupruefung"`

### Task 8: Seitenfeld im Terminal

**Files:**
- Create: `src/traidingbrain/dashboard/static/terminal-chat.js`
- Create: `src/traidingbrain/dashboard/static/terminal-chat.css`
- Modify: `src/traidingbrain/dashboard/templates/terminal.html` (Knopf in der Kopfzeile, `<aside id="chat">`, zwei Einbindungen)
- Test: `tests/test_chat_ui.py` (Vorlage enthält Knopf, Feld und Skript)

**Interfaces:**
- Consumes: Endpunkte aus Task 7; aus `terminal.js` den aktuellen Markt/Zeitebene über `document.body.dataset` oder ein `CustomEvent("terminal:blick", {detail:{symbol, timeframe}})`, das `terminal.js` beim Wechsel feuert (einzeilige Ergänzung dort).
- Produces: sichtbares Seitenfeld gemäss Spec Abschnitt 8.

- [ ] **Step 1: Skill `ui-ux-pro-max`** laden, Entscheidungsblatt (`anti-slop-ajonai`) als Kopfkommentar in `terminal-chat.css` festhalten, wie in `terminal.css`.
- [ ] **Step 2: Write failing test** `test_vorlage_bindet_chat_ein`: `GET /terminal` enthält `id="chat"`, `terminal-chat.js`, `Bot fragen`.
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement** Feld, Nachrichten, Prüfkarte (acht Regeln ✓/✕/?, Urteil, Bedenken, Countdown, **Ausführen**), Formular-Schalter, Status-Punkt, Zustand „Claude denkt …", 409-Meldung, < 768 px Vollbild. Skill `emil-design-eng` für Öffnen/Schliessen und Kartenwechsel; `prefers-reduced-motion` beachten.
- [ ] **Step 5: Run** test → PASS.
- [ ] **Step 6: Audit** `node <anti-slop-skill>/scripts/check.mjs src/traidingbrain/dashboard/static/terminal-chat.css src/traidingbrain/dashboard/static/terminal-chat.js` → keine Fehler.
- [ ] **Step 7: Browser-Prüfung** Dashboard 8788 neu laden (inneren Python-Prozess beenden, ~61 s warten, Neustart-Budget beachten), `/terminal` öffnen: Feld öffnen, Formular-Prüfung BTC long → abgelehnt mit Regeln 2/3; eine Frage an Claude → Antwort erscheint; Handybreite 375 px → Vollbild. Screenshot.
- [ ] **Step 8: Commit** `"Chat: Seitenfeld im Darkwood Terminal"`

### Task 9: Abschluss

- [ ] **Step 1: Run** `.venv/Scripts/python.exe -m pytest -q` → alles grün.
- [ ] **Step 2:** `git diff --stat freqtrade-core...layout -- config config_offen src/traidingbrain/risk src/traidingbrain/live` → leer.
- [ ] **Step 3:** Vault-Notiz `03 Architektur/🖥 Darkwood Terminal — Oberfläche & Bewertungsschicht.md` um Abschnitt „Chat" ergänzen, `aktualisiert: 2026-10-22`; `python scripts/sync_gehirn.py --kein-push`.
- [ ] **Step 4: Commit** und im PR-Text die neuen `api/`-Endpunkte für den Kollegen nennen.
