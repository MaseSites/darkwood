# Briefing an ChatGPT — Stand 18.10.2026

Du prüfst wieder unabhängig. Hier ist alles, was seit deiner letzten Prüfung
gemessen wurde, mit Dateien und Zeilennummern. Keine Zahl ohne Quelle; wo ich
geschätzt habe, steht es dabei.

**Commits seit deinem letzten Stand (`490f300`):**

| | |
|---|---|
| `1141bb4` | P0a — Legacy-Baseline eingefroren, sechs von sechs Armen gefallen |
| `6cbeaeb` | P1a — `ExecutionPolicy` (nur neues Modul, kein Verhalten geändert) |
| `0852426` | P1b — `VenueBinding` (nur neuer Wert, kein Verhalten geändert) |
| `fde8e9c` | P1c — Bestätigungspfad charakterisiert (nur Tests) |

**Prüfstand jetzt, alle drei getrennt:**

| | |
|---|---|
| `pytest -q -p no:randomly` | **1.772 gesammelt, 26 skipped, 0 F, 0 E, Exit 0**, 12:01 |
| `ruff check src tests scripts` | **sauber** |
| `mypy --strict src` | **20 Fehler in 5 Dateien** (unverändert, siehe 8.) |

Die Testzahl ist von 1.731 auf 1.772 gestiegen: +19 `test_execution_policy`,
+12 `test_venue_binding`, +8 `test_confirm_path_is_a_gate`, +2 aus
parametrisierten Fällen. „Grün" sage ich erst, wenn alle drei grün sind — das
ist mypy nicht.

---

## 1. Die Arme sind alle durch. Sechs von sechs gefallen.

84 von 84 (Regel, Markt)-Paaren, zwölf Märkte, `data/arms_alle.jsonl`,
Niveau 99.932 % (73 angemeldete Vergleiche, Bonferroni).

| Arm | n | R/Trade | Differenz | korrigiertes Intervall | Replikation |
|---|---|---|---|---|---|
| Basis | 7335 | −0.0129 | — | [−0.067, +0.040] | — |
| ohne Setup F | 7331 | −0.0068 | +0.0061 | [−0.070, +0.082] | +0.86× |
| Einstand 1 R | 8414 | −0.0147 | −0.0018 | [−0.069, +0.066] | −2.56× |
| Einstand 0.5 R | 9736 | **−0.0308** | −0.0178 | [−0.080, +0.045] | +4.27× |
| Ziel 1 R | 9528 | −0.0052 | +0.0077 | [−0.057, +0.071] | **+0.06×** |
| Ziel 1.5 R | 8175 | −0.0168 | −0.0038 | [−0.075, +0.067] | −1.77× |
| Ziel 2 R | 7566 | −0.0075 | +0.0054 | [−0.069, +0.078] | −0.29× |

**Kein Intervall verlässt die Null, in keiner Richtung.** Alle sechs
Halbbreiten liegen zwischen 0.060 und 0.064 R, alle sechs Punktwerte zwischen
−0.018 und +0.008 R. Jeder gemessene Effekt ist **4- bis 35-mal unter der
Auflösungsgrenze** von 0.0774 R bei zwölf Märkten.

### Der schärfste Einzelbefund: der Einstand-Stop funktioniert und schadet

Vorab verlangte Rand-Kennzahlen:

| | Basis | bei 1 R | bei 0.5 R |
|---|---|---|---|
| Anteil Trades unter −1 R | 60.3 % | 47.5 % | **31.5 %** |
| Regel feuerte | — | 43.9 % von 4.166 scharfen | 72.4 % von 6.561 |
| schlimmster Einzelverlust | −1.89 R | −1.89 R | −1.89 R |
| 5 %-Quantil | −1.08 R | −1.07 R | −1.07 R |
| **R je Trade** | **−0.0129** | **−0.0147** | **−0.0308** |

Die Regel halbiert die Vollverluste fast — und das Ergebnis wird **monoton
schlechter**, bei 0.5 R auf das 2.4-fache des Basisverlusts. Die geretteten
Vollverluste werden von abgeschnittenen Gewinnern mehr als aufgewogen.

**Folgerung, die ich für belegt halte:** der Rückgabe-Befund
(Durchschnittstrade erreicht +1.1840 R, endet bei −0.0129 R, 62.9 % berühren
ihr Ziel nie) ist **keine Nachlässigkeit im Ausstieg**. Er beschreibt, wie
diese Trades verlaufen. `declared_before_reading` stand auf TRUE und die
Vorhersage war das Gegenteil.

E15s bester Arm (Ziel bei 1 R, +0.0077 R) scheitert nicht am Vorzeichen,
sondern an der **Replikation 0.06×**: früh +0.0146 R, spät +0.0009 R.

### Nebenbefund: der Platz-Effekt ist in jedem Arm sichtbar

Trade-Zahlen: 7.335 → 8.414 (+14.7 %) → 9.736 (+32.7 %) → 9.528 (+29.9 %) →
8.175 (+11.5 %) → 7.566 (+3.1 %). Ein früherer Ausstieg gibt den Platz frei.
Bis zu 33 % **in Einzelmarkt-Läufen mit einem Platz je Symbol** — im
gemeinsamen Portfolio grösser und marktübergreifend.

---

## 2. Die Zielarithmetik, auf dem Stand aller Korrekturen

Nach deiner Little-Korrektur (Mittelwert statt Median) und der Korrektur der
Marktzahl (68 nutzbar, nicht 83):

| Pool | n | R/Trade | Angebot/Tag | Deckel/Tag | Chancen 182 T | nötig @1 % | nötige Quote | Urteil |
|---|---|---|---|---|---|---|---|---|
| alles | 7335 | −0.0129 | 23.10 | 3.64 | 662 | +0.454 | 53.2 % | Kante negativ |
| ohne F | 7267 | −0.0060 | 22.88 | 3.63 | 661 | +0.454 | 53.3 % | Kante negativ |
| ohne M15 | 3718 | +0.0121 | 11.71 | 2.32 | 422 | +0.713 | 63.4 % | 59× zu wenig |
| A+B D1+H4 | 1112 | +0.0701 | 3.50 | 1.26 | 230 | +1.313 | 90.0 % | 19× zu wenig |
| **nur A D1+H4** | 876 | **+0.0856** | 2.76 | 2.20 | 401 | **+0.750** | 71.1 % | **9× zu wenig** |
| nur A D1 | 172 | +0.1565 | 0.54 | 0.84 | 99 | +3.086 | **>100 %** | **UNMÖGLICH** |

Letzte Zeile: das nötige R liegt über dem grössten möglichen Gewinner.
Vola-Drag gemessen auf der echten Stichprobe: bei f=1 % liefert +0.0856 R über
401 Trades **1.365× = 1.365 CHF** (arithmetisch 1.409×); bei f=3 % frisst der
Drag **32.5 %**.

Kopplung über den Heat-Deckel (`slots = ⌊H/f⌋`):

| Risiko f | Plätze | Chancen | nötig R | Faktor zu wenig |
|---|---|---|---|---|
| 0.5 % | 10 | 613 | +0.980 | 11.5× |
| **1.0 %** | **5** | **401** | **+0.750** | **8.8×** |
| 1.5 % | 3 | 241 | +0.835 | 9.8× |
| 2.0 % | 2 | 160 | +0.942 | 11.0× |
| 3.0 % | 1 | 80 | +1.268 | 14.8× |

Bei **aufgehobenem** Heat-Deckel und ≥10 Plätzen: +0.490 R nötig, **5.7× zu
wenig** — darüber bindet das Angebot (3.37/Tag bei 83 Märkten) und nichts
verbessert sich mehr.

---

## 3. Die Gebühren-Sensitivität, wie von dir verlangt

Gebührenmodell des Simulators exakt rekonstruiert und gegen **alle 7.335
Fills** geprüft, grösster Fehler **0.0e+00**:

```
fees = Einstiegs-Notional × maker + Ausstiegs-Notional × (maker wenn target, sonst taker)
```

| Szenario | maker | taker | c | Kostenboden | max. Notional @10 CHF Risiko |
|---|---|---|---|---|---|
| A Legacy Bybit | 0.00020 | 0.00055 | 0.00105 | 1.3125 % | 762 CHF |
| B Binance Standard | 0.00020 | 0.00050 | 0.00100 | 1.2500 % | 800 CHF |
| C Binance +BNB *(hyp)* | 0.00018 | 0.00045 | 0.00093 | 1.1625 % | 860 CHF |

Stop-Distanz-Bänder der 7.335 Fills: unter 1.1625 % **0**; 1.1625–1.2500 %
**0**; 1.2500–1.3125 % **2**; über 1.3125 % **7.333**. Kleinste Stop-Distanz
**1.3123 %** — der Kostenboden selbst. Median 2.0866 %, 5 %-Quantil 1.3619 %.
Die beiden Ausnahmen sind ATOMUSDT (1.3122759 %) und DOTUSDT (1.3123028 %),
also ~2e−5 pp darunter — Tick/Qty-Rundung, kein Regelbruch.

| | Delta je Trade | korrigiert 99.932 % | Summe | Mittel |
|---|---|---|---|---|
| B Binance Standard | **+0.001473** | [+0.001413, +0.001532] | +10.81 R | −0.0129 → −0.0114 |
| C +BNB (hyp) | +0.004202 | [+0.004077, +0.004322] | +30.82 R | −0.0129 → −0.0087 |

Nach Ausgang: stop +0.002324 (n=4.648), **target +0.000000 (n=2.684)** — dein
Punkt trifft auf die Stelle genau, Maker ist in B unverändert. max Delta
+0.003860 R gegen deine Schätzung „etwa +0.0038" — Übereinstimmung auf 2 %.

Delta nach Zeitebene (Szenario B): A/D1 +0.000530, A/H4 +0.001153,
A/H1 +0.001456, A/M15 +0.001682. Monoton — engere Stops heissen mehr Notional
je Risikoeinheit. **Die Korrektur hilft am meisten dort, wo die Kante am
schlechtesten ist.**

Neu zugelassene Signale (exakt, weil `cost_fraction = c/d` linear in `c`
skaliert): B **493** (2.15 % der 22.942 kosten-Abgelehnten, +6.72 % der
genommenen), C **1.311** (5.71 %, +17.88 %). Ihre `cost_fraction` liegt in
(0.0800, 0.0840] — **oberhalb** des teuersten vorhandenen Fünftels (max
0.0800 = der Deckel). Die Fünftel der genommenen Population: 1. (billigste)
−0.0126, 2. **+0.0484**, 3. −0.0384, 4. −0.0414, 5. (teuerste) −0.0173 —
nicht monoton. Billige gegen teure Hälfte: +0.0468 R, korrigiert
**[−0.0601, +0.1595]**, spannt die Null. (Die frühere Notiz „billige Trades
sind besser, +0.0561 R, Intervall ohne Null" bezog sich auf **brutto**-R.)

**Einordnung: die Gebührenkorrektur schliesst 0.3 % der gesuchten Lücke.**

---

## 4. Die Ausführungs-Abweichung, gemessen

Dein Befund bestätigt, wörtlich aus `execution/order.py:265`:

```python
self.exchange.create_order(
    self.venue.symbol(intent.symbol), "limit", side, intent.qty, intent.entry,
    {"clientOrderId": ..., "stopLoss": ..., "takeProfit": ...,
     "slTriggerBy": "MarkPrice", "tpTriggerBy": "MarkPrice",
     "timeInForce": "GTC", "reduceOnly": False},
)
```

Kein `PostOnly`, kein `tpslMode`/`tpOrderType`/`tpLimitPrice`, kein
`slOrderType`. Simulator: `broker.py:493` LIMIT ⇒ maker ohne Kreuzungsprüfung,
`broker.py:746` `maker_exit = reason is ExitReason.TARGET` unbedingt.

**Und `broker.py:741-745` sagt es selbst, im Quelltext:** *„It is also a
constraint on the live side, not only a model change. It is only true if the
executor places a resting limit at the target. A take-profit-market order …
crosses the spread and pays taker — and then this line would be quietly
optimistic about every winner."* Der Vertrag war notiert und nie durchgesetzt.

| Variante | Delta je Trade | korrigiert 99.932 % | Summe | Mittel |
|---|---|---|---|---|
| nur TP wird Market | −0.005835 | [−0.006158, −0.005515] | −42.80 R | → −0.0188 |
| nur Einstieg crosst | −0.016143 | [−0.016465, −0.015817] | −118.41 R | → −0.0291 |
| **beides Taker (Schranke)** | **−0.021979** | [−0.022488, −0.021477] | **−161.21 R** | → **−0.0349** |

**Die obere Schranke ist 1.7-mal grösser als die gesamte gemessene Erwartung.**

Kostenboden 1.75 % statt 1.3125 % würde **2.529 von 7.335 Fills (34.5 %)**
nicht zulassen; nach Zeitebene M15 1.575, H1 751, H4 192, **D1 nur 11**. Deren
R-Mittel −0.0287 gegen −0.0046 beim Rest. Je Pool:

| Pool | n | R heute | fällt weg | R mit Taker | R auf der verbleibenden Menge |
|---|---|---|---|---|---|
| alles | 7335 | −0.0129 | 34.5 % | −0.0349 | −0.0214 |
| ohne M15 | 3718 | +0.0121 | 25.7 % | −0.0076 | +0.0039 |
| A+B D1+H4 | 1112 | +0.0701 | 14.7 % | +0.0537 | +0.0567 |
| **nur A D1+H4** | 876 | +0.0856 | 17.9 % | +0.0669 | **+0.0728** |

### Eine Korrektur meiner eigenen Zahl

Ich hatte Slippage zweimal gerechnet (0.0017). `broker.py:713` sagt wörtlich:
*„`sim/plan.py:307` sets `OrderType.LIMIT` without exception, so no market
entry exists in any measurement, and **the limit path never slips at all**."*
Slippage trifft nur den Ausgang. **Deine 0.00140 war richtig.** Darum leitet
meine `ExecutionPolicy` die Slippage jetzt aus dem Ordertyp ab statt sie frei
zu setzen — eine Policy, die PostOnly sendet und trotzdem rutscht, soll nicht
konstruierbar sein.

---

## 5. Die Venue-Karte: 125 Funde

Fünf unabhängige Suchrichtungen (Namen, Spec/Gebühren, Bestätigungspfad,
Signatur, Simulator-Kostenmodell). Die schwersten:

### 5.1 Gespeicherte Forschungsdaten könnten unwiederbringlich verderben

`data/derivatives.py:347` — `LivePositioning.refresh` schreibt frisch geholte
Zeilen über `store.write` in **dieselbe Datei** wie die Backfill-Historie.
`DerivativesStore.write` (283-296) mischt per `pd.concat` und `_tidy` (262:
`drop_duplicates(subset="ts", keep="last")`).

- Live-Zeilen: `run_live.py:171` → `DerivativesSource(…, config.engine.exchange.name)` = **BINANCE**
- Historie: `backfill_derivatives.py:74-81` → hartkodiertes `ccxt.bybit` = **BYBIT**
- `_OI_SCHEMA` (51-57) und `_RATIO_SCHEMA` (59-65) haben **keine Venue-Spalte**
- `keep="last"` ⇒ bei Überlappung gewinnt Binance und überschreibt Bybit
- `panel.py:138-141` hat den Grössenunterschied selbst gemessen: **16419.749
  (Bybit) gegen 47921.245 (Binance-Archiv)** für BTCUSDT am 2021-10-01 00:00,
  Faktor ~2.9
- `positioning.py:48` setzt `MIN_OI_CHANGE = 0.004` (0.4 %) — die Naht wäre
  eine gigantische Open-Interest-Bewegung, die rein aus dem Börsenwechsel
  entsteht

**Gemessen: es ist NICHT passiert.** Alle vier Dateien
(`data/derivatives/{BTC,ETH,SOL,XRP}USDT/`) enden 2026-09-29, zuletzt
geschrieben 10-05 19:37, **null Sprünge über 50 %**. Und die Herkunft
bestätigt sich aus den Daten: BTCUSDT 2021-10-01 00:00 steht bei **16419.749**
— der Bybit-Wert auf die letzte Dezimalstelle. Die Gefahr ist **latent**.

### 5.2 Die Preisdrift-Prüfung könnte gegen Demo-Preise laufen

`run_dashboard.py:173` übergibt `testnet=secrets.bybit.testnet` an die
**Binance**-Preisquelle. Mit `testnet=true` ruft `venue.build` (121-123)
`practice_mode="enable_demo_trading"` und leitet auf `demo-dapi.binance.com`
(147-148). `run_live.py:96` setzt für dieselbe Quelle ausdrücklich
`testnet=False` mit der Begründung *„Prices come from mainnet"*. **Die beiden
Runner widersprechen sich bei derselben Entscheidung.** `exchange.py:14-16`
sagt selbst, eine Testnet-Historie sei dünn und teils synthetisch.

### 5.3 Der Bestätigungspfad ist kein Tor

| Stelle | prüft Kontogrenzen? |
|---|---|
| `builder.build()` | **ja** — `builder.py:260` |
| `builder.adjust()` | **nein** (prüft nur „Risiko darf nur sinken") |
| `POST /token` | **nein** — nur Preisdrift, `app.py:389` |
| `POST /confirm` | **nein** — Kill-Switch, Token, CAS, `app.py:405` |
| `app.py:315` | nur **Anzeige** (`limits_allow_trading`) |

Tagesverlust, Wochenverlust, Abkühlung und Platzdeckel sind auf dem Weg vom
Vorschlag zur Order kein Tor. Das Abnahmekriterium von Stufe 7 des Bauplans
lautet: *„Änderung 5×→4× … läuft erneut durch den Guard."* Nicht erfüllt.

### 5.4 Der Kontozustand kann die Positionsprüfungen nicht auslösen

`run_dashboard.py:238` baut `AccountState.from_history(...)` **einmal beim
Start**, ohne `open_positions`. Die Liste ist leer, also rechnen
`limits.py:210` und `:217` `0 >= 5` und `0 >= 1`. Derselbe Defekt, den
`live/book.py` für den Papierhändler beschreibt und behoben hat.

### 5.5 Weitere Funde, verdichtet

- `execution/order.py:91` — `venue_name: str = "bybit"` als Vorgabewert;
  `run_dashboard.py:144` und `run_live.py:230` übergeben nichts. Die einzige
  Stelle, die es übergibt, ist `check_exchange.py:156` (CLI-Argument).
- `execution/order.py:339-341` — `symbol_spec()` baut
  `MarketData(venue_name=self.venue.name, …)`, also kommen Tick, qty_step,
  min_qty, min_notional, max_leverage **und beide Gebühren** von der Venue des
  **Executors**.
- `data/exchange.py:236-237` — `taker_fee=float(market.get("taker") or 0.00055)`
  und `maker_fee=… or 0.0002`: ein **hartkodierter Bybit-Ausweichwert in einer
  venue-agnostischen Abfrage**.
- `config/settings.py:461-470, 504` — es gibt **nur `BybitCredentials`**,
  eingebunden als `Secrets.bybit`. `ExchangeConfig` erlaubt `binance`; der
  Geheimnis-Namensraum kennt nur bybit. Ein Binance-Executor hätte keinen
  Zugangsdatenpfad.
- `ExchangeConfig.name` hat **ebenfalls** `"bybit"` als Vorgabewert
  (`settings.py:33`), während `settings.yaml` `binance` sagt.
- `run_live.py:115` — unarmiert hartkodierte `OFFLINE_SPEC`-Bybit-Zahlen.
- `backfill_derivatives.py:74` — `ccxt.bybit(...)` direkt, unter Umgehung des
  Venue-Moduls.
- `journal/version.py:119` — `run_signature` besteht aus `initial_equity |
  setups.enabled | max_cost_fraction_of_risk | signal_timeframe | refused-v1 |
  …`. **Venue und Gebührenplan stehen NICHT drin.**
- `sim/broker.py:158-199` — `Fill` speichert keine Venue. Auch nicht in
  `data/replay_fills/`.
- `sim/broker.py:753` — Liquidationszweig nutzt `taker_fee` als Platzhalter
  für eine Liquidationsgebühr.
- `proposals/builder.py:294-331` — `adjust()` ruft `limits.check()` nicht.

---

## 6. Was ich in P1 schon gebaut habe

### `src/traidingbrain/execution/policy.py` (`6cbeaeb`, 19 Tests)

Trennung **Absicht gegen Beweis**: eine Policy erklärt, was gesendet wird;
`maker_role_proven` (Vorgabe FALSE) entscheidet, ob die günstigere Gebühr
gilt. `EntryLiquidity` hat drei Werte: `POST_ONLY_MAKER`,
`LIMIT_TAKER_ALLOWED` (der heutige Executor), `MARKET_TAKER`. Slippage wird
aus dem Ordertyp **abgeleitet**, nicht gesetzt.

| Policy | Umlaufkosten | Kostenboden |
|---|---|---|
| A `safety-first` | taker+taker+1×Slippage = **0.00140** | 1.75 % |
| B `maker-target`, unbewiesen | identisch zu A | 1.75 % |
| **B mit Beweis** | maker+taker+1×Slippage = **0.00105** | **1.3125 %** |

**Die letzte Zeile IST das Legacy-Kostenmodell.** Legacy hat Policy B also
stillschweigend als *bewiesen* behandelt.

Abgelehnte Zustände, je mit Test: Limit-Stop, `maker >= taker`, Gebühren ohne
Herkunftsangabe, negative Slippage. `policy_for()` hat **keinen Vorgabewert**.

### `src/traidingbrain/execution/venuebinding.py` (`0852426`, 12 Tests)

`VenueBinding` ist ein gefrorener Wert über fünf Felder — `analysis_venue`,
`price_check_venue`, `instrument_spec_venue`, `execution_venue`, `policy` —
der inkohärent **nicht konstruierbar** ist. Absichtlich ein Wert und keine
Prüffunktion: eine Funktion muss aufgerufen werden, und genau das ist
ausgeblieben. `venue` ist abgeleitet, nicht gespeichert. `testnet` geht in den
Fingerprint ein.

### `tests/test_confirm_path_is_a_gate.py` (`fde8e9c`, 8 Tests)

Charakterisiert den Istzustand. **Zwei meiner Hypothesen sind dabei
gefallen** — siehe Abschnitt 7.

---

## 7. Zwei eigene Hypothesen, die beim Testen gefallen sind

**(a) Die gefrorene Uhr blockt MEHR, nicht weniger.** Ich hatte behauptet, der
einmal gesetzte `now_ms` lasse die Abkühlung ablaufen. Gemessen: liegen
Verluste in der *Zukunft* des Zustands, ist `now_ms − last_loss` negativ und
die Restzeit grösser als der Deckel. Dasselbe bei den Verlustfenstern —
`limits.py:165` rechnet `cutoff = now_ms − DAY_MS`, mit gefrorener Uhr ist das
Fenster `[T0−24h, ∞)`, wächst unbegrenzt und sammelt jeden späteren Verlust
ein. Ein Test zeigt: ein Verlust **zehn Tage nach** dem gefrorenen Zeitpunkt
zählt als „heute". Der Defekt ist real und irrt auf die **sichere** Seite.

**(b) Der Tagesdeckel liest Trades, nicht Eigenkapital.** `limits.py:225`
rechnet `−state.realised_today()`, eine Summe über `recent_trades`. Ein Konto,
dessen Eigenkapital 6 % gefallen ist, ohne dass ein Trade abgeschlossen wurde,
löst den Deckel **nicht** aus.

Übrig bleibt als eindeutiger Defekt desselben Aufrufs: die leere
`open_positions`-Liste (5.4).

**Dazu zwei Betriebsfehler von mir, zur Vollständigkeit:** mein
Lebendigkeitsprüfer las `int(stdout or 0)`, machte aus einer fehlgeschlagenen
PowerShell-Abfrage eine glaubwürdige Null und damit aus „Abfrage
fehlgeschlagen" ein „kein Arm läuft". Auf diese Lesart habe ich einen zweiten
Prozess auf dieselbe Cache-Datei gestartet, während der erste mit 49.178 s CPU
rechnete; gestoppt nach 20 s CPU, Cache geprüft und unberührt. Und der
Prozessfilter zählte sich selbst — zum zweiten Mal, sechs Tage nach der
Notiz darüber.

---

## 8. P0a-Befunde, die du noch nicht hattest

- **`data/funding/` ist eine lebende Datei.** `papertrade.py:248
  top_up_funding()` frischt sie bei jedem Lauf auf. Keiner der zwölf
  SHA-256 aus der ersten Belegsammlung (16.10.) stimmte am 17.10. um 09:59
  noch. Zeilenzahl wächst um 3/Tag. Geprüft und für die Legacy-Population
  unbedenklich: alle 39 seither angehängten Zeilen liegen **nach** dem
  spätesten Replay-Zeitpunkt (2026-10-04 11:45Z).
- **Der Funding-Speicher ist ein UPSERT**, kein Append: `funding.py:78-82`
  `drop_duplicates(subset="ts", keep="last")`, Eingehendes hinter Bestehendes.
  Faktisch append-only nur durch Aufruferdisziplin in **einer Zeile**
  (`papertrade.py:273`, `since = (last + 1) if last else …`).
- **Die Arme liefen unter `|portfolio|cap5`, die replay_fills unter
  `|refused-v1`** — und reproduzieren die Basis exakt (7.335 Trades,
  −94.78 R). Mechanisch: R ist grössen-invariant, und im Einzelmarkt-Lauf
  bindet `max_positions_per_symbol=1` zuerst, also kann der Platzdeckel nie
  greifen. Bestätigt durch `grenzen = 0` in allen 47.918 Replay-Signalen. **Im
  gemeinsamen Portfolio würden beide Unterschiede greifen.**
- **Exakter Join über `proposal_id` (= `SYMBOL-decided_ts`, `plan.py:303`):**
  7.335 Fills, 7.335 eindeutige IDs, 7.333 angenommene Signale, exact_match
  **7.255 (98.91 %)**, fill_without_signal 80, signal_without_fill 78,
  duplicate_candidate 0/0. **78 der 80 haben eine Signalzeile unter einer
  ANDEREN `run_signature` (0.15)**, Verteilung BTCUSDT 60 / ETHUSDT 20; BTCs
  Signale unter 0.08 enden am 2025-10-27, das Replay-Fenster bis 2026-10-01.
- **Pending-Belegung ist klein:** 7.255 gefüllte Aufträge, **6.817 (94.0 %)
  füllen sofort**, Median 0.000 h, Mittel 0.044 h, max 7.93 h bei 8.0 h Frist.
  Pending gesamt 318.8 von 242.085.3 Platzstunden = **+0.13 %**. Abgelaufen:
  78 Aufträge über zwölf Märkte, nur als Zählung, **`expires_ts` nirgends
  gespeichert**.
- **Gleichzeitige Signale:** 5.988 verschiedene `decided_ts`, davon **990
  (16.5 %) mit >1**, Verteilung 1:4998 2:731 3:191 4:49 5:12 6:5 7:2 — **nur 7
  Zeitpunkte über fünf**. Die Knappheit entsteht durch Belegung aus früheren
  Trades (mittlere Haltedauer 33.0 h), nicht durch gleichzeitige Ankunft.
- **Die Besetzungs-Schattenmenge:** nur für EINEN Markt und bei Kostendeckel
  **0.15** gemessen — BTCUSDT Schatten 6.962 Signale / 1.485 angenommen gegen
  Basis 2.861 / 555, Verhältnis **2.68×**. Übertragen auf die 7.333: ~19.600
  Kandidaten. Das ist eine Grössenordnung, keine Messung der 0.08-Population.
- **Märkte:** 83 Verzeichnisse = 12 aktiv (Median 70.2 MB) + 56 ungesehen
  (50.0 MB) + 15 Rest. Von den 15 tragen **14 nur W1**; das fünfzehnte,
  **KNCUSDT**, hat D1 (1.838 Kerzen), H4 (11.031) und W1 (262), aber kein H1,
  M15 oder M1. Nutzbar bleibt **68**. (Deine Korrektur, eingearbeitet.)
- **`mypy --strict src`: 20 Fehler in 5 Dateien** — 12 `untyped-decorator` +
  2 `import-not-found` in `adapter/server.py`, 2 `arg-type` in
  `live/paperstate.py`, 2 `type-arg` in `journal/replayset.py`, 1
  `no-any-return` in `learn/goalsim.py`, 1 `attr-defined` in
  `journal/version.py`. Das Abnahmekriterium von Stufe 0 ist verletzt.

`audit/P0A_LEGACY_FREEZE.md` (51 KB) enthält **34 Befunde in zehn Gruppen**,
je mit Behauptung, Quelle, gemessener Grösse, Auswirkung, Schluss,
verbleibender Unbekannter, Behebungsschritt und Etikett — 28 BELEGT, 2 BELEGT
(in-sample), 2 MODELLIERT, 2 HYPOTHESE. Plus `audit/p0a_manifest.json` mit
2.589 Kerzen-Hashes und allen Arm-Kommandozeilen.

---

## 9. Fragen an dich

**A. Die strategische, und sie ist die wichtigste.** Nach E14/E15/E16 ist die
Ausstiegs-Achse geschlossen, die Entry-Achse war vorher schon ohne Kante, und
die Gebühren-Achse schliesst 0.3 % der Lücke. Der beste verbleibende Kandidat
(nur A auf D1+H4, +0.0856 R in-sample, +0.0728 R unter realistischer
Ausführung) ist **9× zu wenig** für 20× in sechs Monaten und erreicht 15.000
erst um den 25.02.2027. **Rechtfertigt dieses Bild noch den Bau einer sauberen
Messmaschine (P2–P4, geschätzt 20–40 Stunden), oder ist die ehrliche Antwort,
dass die Messmaschine gebaut wird, um eine andere Frage zu beantworten als
„erreichen wir 20×"?** Falls Letzteres: welche Frage ist es dann, und ist sie
die Zeit wert?

**B. Venue-API-Semantik, bevor ich verdrahte.** Für Bybit v5 und Binance
USDⓈ-M, mit Primärquellen:
1. Gibt es bei Bybit für `takeProfit`/`stopLoss` an der Entry-Order eine
   Kombination, die einen **vor dem Trigger ruhenden** reduce-only-Limit-TP
   erzeugt — oder muss der TP nach dem Entry-Fill als separate Order gesendet
   werden (und entsteht damit das Fenster, das `_place()` ausdrücklich
   vermeiden will)?
2. Meldet Bybit v5 im `execution`-WS-Stream pro Fill eine verlässliche
   **Maker/Taker-Rolle** und die realisierte Gebühr, und unter welchem Feld?
3. Wie sieht das bei Binance USDⓈ-M aus — `postOnly`/`GTX`, TP-Typen, und
   das `isMaker`-Feld im User-Data-Stream?
4. Storniert Binance einen marketable `GTX` so wie Bybit einen marketable
   `PostOnly`?

**C. Die Derivate-Gefahr — welcher Entwurf?** Drei Möglichkeiten: (i) eine
Venue-Spalte ins Schema und gemischte Schreibvorgänge hart ablehnen; (ii) je
Venue eine eigene Datei; (iii) Live-Positionierung bis P2 ganz abschalten. Die
bestehenden Dateien sind rein Bybit und sollen es bleiben. Was ist die
richtige Reihenfolge, und was passiert mit der Live-Positionierung in der
Zwischenzeit?

**D. Die Zugangsdaten-Lücke.** Es gibt nur `BybitCredentials`. Soll `P1` einen
venue-parametrisierten Geheimnis-Namensraum bekommen (`TB_BINANCE__API_KEY`
etc.) — oder soll Binance-Ausführung bis auf Weiteres **hart abgelehnt**
werden, mit Bybit als einziger ausführbarer Venue, und dafür die *Daten* auf
Bybit umgestellt? Das zweite wäre die kleinere Änderung, bedeutet aber einen
neuen Backfill aller 68 Märkte.

**E. Die Reihenfolge innerhalb P1.** Meine Liste: (1) `venue_name` zur
Pflicht, beide Aufrufstellen aus der Konfiguration; (2) Zugangsdaten gegen
Venue prüfen; (3) `testnet` der Preisquelle entkoppeln; (4) `/token` als Tor
mit frischem Kontozustand inklusive offener Positionen; (5) `adjust()` durch
den Guard; (6) Venue + Policy in `run_signature`; (7) Venue-Spalte für die
Derivate. Stimmt die Reihenfolge, und fehlt etwas?

**F. Was ich nicht gefragt habe.** Nenne den Punkt in diesem Briefing, bei dem
du einer meiner Schlussfolgerungen **nicht** folgst.
