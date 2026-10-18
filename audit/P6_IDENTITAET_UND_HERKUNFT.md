# Phase 6 — Identität und Herkunft

**Stand 18.10.2026.** Entscheidungsstempel des Arbeitsbaums `fdba080e487f`
(unverändert über die ganze Phase). Laufender Papierhändler: PID 71960, Stempel
`d8c7f12104e4`, **nicht angefasst**.

---

## 0. Was diese Phase beantwortet

Der Auftrag lautete, Venue, Umgebung, Policy und Gebührenplan in die Signaturen
aufzunehmen und jedem Fill seine Herkunft mitzugeben. Der Grund steht seit Phase
2 im Code, in `execution/venuebinding.py:274`:

> In der Legacy-Signatur stand die Venue NICHT. Darum ist aus den Daten nicht
> entscheidbar, ob die 7.335 Trades unter Bybit- oder Binance-Regeln entstanden
> — die Antwort steht nur in einem Kommentar.

Die Phase hat das geschlossen und dabei **vier Befunde** ergeben, die vorher
nicht bekannt waren. Drei davon sind Messungen.

---

## 1. Befund: der Gebührenplan kam von der falschen Börse — und es kostet +0.0014 R

`config/settings.yaml` steht auf `exchange.name: binance`. Gemessen gegen die
echte Börse am 18.10.2026: Binance nennt `taker = 0.0005`, `maker = 0.0002`.
`DEFAULT_SPEC` in `domain/market.py:83` trägt `taker_fee = 0.00055` — **Bybits**
Satz. Alle 7.335 Replay-Fills sind unter der fremden Gebühr entstanden.

Exakt nachgerechnet ohne Neulauf (`scripts/study_venue_fee.py`), weil jeder Fill
Nominal, Gebühr und R trägt:

| Gebührenplan | Erwartungswert | Gebühr gesamt | Δ gegen Legacy |
|---|---|---|---|
| Legacy wie gespeichert (Bybits Taker) | **−0.0129 R** | 2.043,87 USDT | — |
| Venue-korrekt, gleiche Rollen | **−0.0114 R** | 1.939,51 USDT | **+0.0014 [+0.001, +0.002]** |
| Venue-korrekt, nur Taker (Policy A) | **−0.0304 R** | 3.283,24 USDT | −0.0170 [−0.018, −0.017] |
| Null Gebühren (**Obergrenze**) | **+0.0164 R** [−0.016, +0.048] | 0,00 USDT | +0.0290 [+0.028, +0.029] |

Die Korrektur ist reliabel und in **allen zwölf Märkten gleichgerichtet**
(+0.001 bis +0.002, jedes Intervall ohne die Null).

### Zwei Wächter, die beide gegriffen haben

Die Zahl wäre ohne sie falsch gewesen, und zwar glatt und plausibel:

1. Das Modell *maker ein / taker aus* reproduzierte nur **4.651 von 7.335**
   Fills. Alle 2.684 Abweichungen waren `closed_target` — ein Zielausstieg ist
   eine Limit-Order, also *maker/maker*. Die Rollenzuordnung wird jetzt **je
   Fill aus der Gebührenspalte** bestimmt, und die Gegenprobe fällt exakt auf
   den Ausstiegsgrund: 4.648 `stop` → maker/taker, 2.684 `target` →
   maker/maker, 3 `manual` → maker/taker. Das ist eine Bestätigung und keine
   Kurvenanpassung.
2. `net_pnl = gross − fees − funding` brach bei **4.603** Fills, jedes Mal um
   exakt `2 × funding`. **Funding ist vorzeichenbehaftet: positiv heisst
   erhalten.** Die anderen 2.732 Fills haben Funding 0 und hätten beide
   Vorzeichen bestätigt — ein Test auf der Teilmenge, die die Frage nicht
   stellt, wäre grün gewesen.

### Was daraus folgt

**Die Kostenachse ist quantitativ geschlossen.** Eine Börse, die *nichts*
kostet, bringt +0.0164 R mit einem Intervall, das die Null enthält, gegen eine
Anforderung von +0.3216 R (20× über 312 Trades bei 3 % Risiko). Faktor 20.

Und die Obergrenze ist **optimistisch** gerechnet, nicht vorsichtig: bei null
Gebühren kann die Kostenregel (`max_cost_fraction_of_risk`) überhaupt nicht mehr
auslösen, die Zahl behält also den Nutzen einer Auswahl, deren Kosten sie
gleichzeitig auf null setzt — und die von dieser Regel abgelehnte Population ist
gemessen brutto-negativ. Ein echter Nullgebühren-Lauf wäre schlechter.

Die unbewiesene Makerannahme ist **12× mehr wert** als die Venue-Korrektur. Das
ist die ehrliche Rangfolge auf dieser Achse.

---

## 2. Befund: die Börse nannte Handelsregeln nicht, und der Code hat sie erfunden

`data/exchange.py:236` hatte für jedes Feld einen `or`-Ausweichwert, und die
Zahlen darin waren Bybits. Der Docstring derselben Funktion verurteilte das
schon („Hardcoding these is how orders get rejected in production"). Zwei
verschiedene Defekte:

* **Erfinden.** Sechs Felder halten jetzt den Lauf an (`UnpublishedSpecError`).
  Der Grund ist der Pfad: `fetch_symbol_spec` speist `run_backtest.py` und
  `papertrade.py`, und in einer Simulation lehnt niemand eine Order wegen
  falscher Rundung ab. Ein geratener `price_tick` rundet still jeden Preis
  falsch, über den ganzen Lauf.
* **`or` statt `is None`.** `0.0` ist in Python falsch, also bekam eine Börse
  mit einer Gebühr von **null** Bybits 0,055 % untergeschoben — derselbe Fehler
  in die Gegenrichtung.

### Gemessen gegen die Börse, nicht gegen die Fixture

`tests/fakes.py:91` nennt alle sieben Felder. Die echte Marktbeschreibung nennt
`limits.leverage.max` für **keines** der zwölf Perpetuals; Binance
veröffentlicht die Hebelstufen nur hinter einem signierten Endpunkt, den diese
Direktive nicht anfassen darf. Fail-closed hätte den ganzen Forschungspfad
stillgelegt, ohne etwas richtiger zu machen. Ohne die Probe gegen die Börse wäre
das eine grüne Suite und ein toter Papierhändler gewesen.

Darum bleibt `max_leverage` beim Ersatzwert 25.0, mit argumentierter
Fehlerrichtung (unter jedem echten Deckel) **und einer Wache daran**: ein Test
fällt, sobald `risk.leverage.max` über diesen Wert steigt und die geratene Zahl
anfängt zu binden. Heute ist sie von `leverage.max: 10.0` dominiert und
entscheidet nichts.

### Und die echten Instrumentregeln weichen je Symbol ab

| | BTC | ETH | SOL | XRP | ADA | DOGE | DEFAULT_SPEC |
|---|---|---|---|---|---|---|---|
| `price_tick` | 0.1 | 0.01 | 0.01 | 0.0001 | 0.0001 | 1e-05 | **0.1 für alle** |
| `qty_step` | 0.001 | 0.001 | 0.01 | 0.1 | 1 | 1 | **0.001 für alle** |
| `min_notional` | 50 | 20 | 5 | 5 | 5 | 5 | **5 für alle** |

**Der Tick trifft den Replay nicht**, weil `round_price` nur in
`proposals/builder.py` sitzt — im Dashboard- und Live-Pfad, nicht im
Backtest-Pfad. Das ist eine wichtige Trennung: die Tick-Abweichung ist ein
Live-Problem, nicht eine Verunreinigung der 7.335 Fills.

### Und die Schrittweiten binden nicht — gemessen, nicht vermutet

`qty_step`, `min_qty` und `min_notional` wirken über `risk/sizing.py:138` und
`sim/plan.py:195` auch im Replay. `scripts/study_spec_effect.py` rechnet gegen
den Schnappschuss `data/venue_specs/binance.json` — eingefrorene Kopie
`audit/venue_specs_binance_2026-10-18.json`, weil `data/` nicht im Repo liegt
und ein Messartefakt sonst nicht reproduzierbar wäre —, welche Fills die
**echte** Spec gar nicht zugelassen hätte:

> **2 von 7.335 (0,03 %)**, beide in AVAX, beide weil die Rohgrösse auf null
> rundet. Kein einziger Fill scheitert an `min_qty` oder `min_notional` — auch
> nicht BTCs echte 50 USDT gegen die angenommenen 5. Erwartungswert der
> verbleibenden 7.333: **−0.013 R**, also −0.0002 gegen alle.

Das schliesst den Punkt: **die Venue-Verwechslung kostet exakt die
Gebührendifferenz und sonst nichts.** Ein Faktor 1000 in der Schrittweite (ADA,
AVAX, DOGE: echt 1 gegen angenommene 0.001) schlägt nicht durch, weil die
Positionen bei 1.000 USDT Konto und 1 % Risiko gross genug sind, dass eine
Rundung auf ganze Einheiten unter einem Promille liegt.

Die Grenze der Messung steht im Skript: ein abgelehnter Trade gibt seinen Platz
frei, und welcher dann einrückt, entscheidet nur ein Neulauf mit gemeinsamem
Konto. Bei zwei abgelehnten Trades ist das keine ernste Einschränkung.

---

## 3. Befund: das Kohärenztor aus Phase 2 hat seinen Fall gefunden

Beim Versuch, dem Replay seine Identität mitzugeben, hat
`VenueBinding.research()` den Lauf abgewiesen:

```
IncoherentVenueError: Ein Lauf, 4 Boersen-Entscheidungen, aber 2 verschiedene
Boersen: ['binance', 'bybit']. data_venue='binance', price_venue='binance',
instrument_spec_venue='bybit', policy='binance'.
```

Das Tor hatte recht, und es wurde in Phase 2 gebaut, **ohne diesen Fall zu
kennen**. Der Replay liest Binance-Kerzen und baut seine Instrumentregeln aus
`DEFAULT_SPEC`.

Die eingefrorene Population ist aber genau so entstanden und muss reproduzierbar
bleiben. Die Lösung ist **keine Aufweichung des Tores**, sondern eine benannte
Ausnahme mit drei Eigenschaften:

1. Sie heisst `VenueBinding.legacy_incoherent` und nicht `research` — niemand
   trifft sie versehentlich.
2. Sie verlangt einen **Grund als Text**. Ein `allow=True` wird kopiert; ein
   Feld, das man füllen muss, wird gelesen. Der Grund geht in den Fingerprint,
   also sind ein kohärenter und ein inkohärenter Lauf nie dieselbe Zeile.
3. Sie **kann nicht ausführen**. `execution_venue` ist kein Parameter, und eine
   zusätzliche Prüfung im `__post_init__` fängt den Weg über
   `dataclasses.replace`. Ein Lauf, der nicht weiss, welche Instrumentregeln an
   der Zielbörse gelten, darf messen und niemals senden.

Streng bleibt sie auch dort, wo Strenge nichts kostet: eine *kohärente* Bindung
durch diesen Weg zu bauen ist ein Fehler, denn dann wäre der Grund
gegenstandslos und würde als Rauschen in jeden Fingerprint wandern.

---

## 4. Befund: Simulator und Policy widersprechen sich über die Makerrolle

`sim/broker.py:493` berechnet die Makergebühr für **jeden** Limit-Einstieg, ohne
`maker_role_proven` zu prüfen. `broker.py:747` tut dasselbe für Zielausstiege
und sagt im eigenen Docstring, das sei *„quietly optimistic about every
winner"*. Das Policy-Objekt führt `maker_role_proven = False`.

Der Simulator rechnet also, als wäre die Makerrolle bewiesen. Gemessen kostet
diese Annahme **+0.017 R je Trade** [+0.017, +0.018] — zwölfmal die
Venue-Korrektur.

Die Identität des Replays nennt darum `bybit:maker-target` (die Sätze, die
wirklich berechnet wurden) und lässt `maker_role_proven` auf `False` — das Feld
würde sonst einen Beweis behaupten, den es nicht gibt. Die Abweichung steht
ausgeschrieben im Grund und damit im Fingerprint.

---

## 5. Was gebaut wurde

### `journal/identity.py` — `ExperimentIdentity`, 18 Felder

`run_signature` wird **nicht erweitert, sondern mitgetragen**. Sie ist ein
Schlüssel: 12.843 Zeilen liegen unter ihren exakten Zeichenketten, und jeder
Zusatz hängt nur an, wenn er vom historischen Anker abweicht. Für die Venue wäre
dieser Anker selbst der Widerspruch — „nichts anhängen, wenn es dem Anker
entspricht" hätte den Fehler zum Vorgabewert gemacht.

Die tragende Eigenschaft ist **bewiesen und nicht behauptet**: ein
parametrisierter Test liest die Feldliste aus `dataclasses.fields`, verändert
jedes Feld einzeln und verlangt einen anderen Stempel. Er wächst mit, und ein
später hinzugefügtes Feld, das nicht in `canonical()` landet, lässt ihn fallen.
Genau dieser Test hätte den Befund aus §0 vor einem Jahr gefunden.

Fail-closed: leeres Feld, `None` (ausser den beiden Ausführungsfeldern, wo „kein
Ausführungspfad" ein echter Zustand ist), unbekannter oder fehlender Schlüssel
beim Einlesen, und ein Wert, der das Trennzeichen enthält — alles Abbruch.

### `journal/provenance.py` — `decision_id` und `FillProvenance`

`decision_id` ist ein Hash über den **Inhalt** der Entscheidung. Der Anlass: am
11.10.2026 wurden Fills ihren Entscheidungen über *ungefähren* Preis und
Zeitpunkt zugeordnet, und das hat 78 widersprüchliche Signaturen verdeckt.

Preise gehen als `float.hex()` ein. Ein Test zeigt zwei Preise, die `.8f` auf
dieselbe Zeichenkette abbildet und die verschiedene Schlüssel bekommen.

`FillProvenance` trägt die dreizehn Angaben der Direktive in 14 Feldern, und **jede
modellierte Grösse steht neben ihrer tatsächlichen**. Das ist der Punkt: in der
Simulation gibt es keine tatsächliche, live gibt es beide, und der Unterschied
*ist* die Messung, auf die der Ausführungsteil wartet. `slippage` ist `None`
statt `0.0`, wenn kein echter Fillpreis vorliegt — eine Null würde behaupten, es
sei gemessen worden und habe nichts ergeben.

Die Integritätsprüfung sitzt beim **Schreiben**. Ein nachträglicher Bericht
findet die Waise, wenn sie schon in drei Auswertungen steht — genau so ist der
Trade vom 17.10.2026 gelaufen, der zu keinem Konto gehörte.

Und ein Fall, der ausdrücklich **kein** Fehler ist: eine Entscheidung ohne Fill.
In ADAUSDT wurden 3.703 von 4.446 Absichten abgelehnt. Die Ablehnungen sind
selbst eine Messung.

### `data/dataversion.py` — zwei Datenstempel, Methode im Wert

`content:` hasht Zeitstempel und Schlusskurse und fängt eine Revision.
`coverage:` hasht Fenster und Zeilenzahl, ist billig und **blind** dagegen, dass
eine Quelle ihre eigene Vergangenheit umschreibt. Beide Eigenschaften sind
getestet, die Blindheit der billigen Form ausdrücklich — sie ist kein Defekt,
sondern der Grund, warum die Methode vorne im Wert steht.

---

## 6. Dass die Änderung additiv ist, ist belegt

Drei unabhängige Belege:

1. **Struktur.** `identity_for` wird in `replay_all_markets.py:190` gerufen,
   `engine.run()` in Zeile 159. Die Identität entsteht 31 Zeilen *nachdem* die
   Fills existieren.
2. **Stempel.** `decision_version()` ist unverändert `fdba080e487f`, und keines
   der drei neuen Module liegt im 59-Modul-Abschluss des Entscheidungspfads.
3. **Empirie.** Ein kurzer Replay (BTCUSDT, 600 Balken, in einen Scratch-Ordner,
   die eingefrorenen Daten unberührt) reproduziert **2 von 2** abgeschlossenen
   Trades feldgenau gegen `data/replay_fills/BTCUSDT.json`. Die einzigen
   Abweichungen: `stop_moved`, ein Feld, das es zur Einfrierung nicht gab (E10),
   und der dritte Trade, den der `--max-bars`-Schnitt manuell schliesst.

Der Replay hat jetzt `--out`, damit ein Probelauf die 7.335 Legacy-Fills nicht
überschreiben kann.

---

## 7. Was die eingefrorene Population nicht mehr hergibt

`scripts/audit_provenance_gap.py`, gemessen statt aufgelistet:

**Rekonstruierbar.** Entscheidungszeit (`sim/plan.py:303` baut `proposal_id` aus
`created_ts`; die 438 Fälle à 6,0 %, in denen sie von `opened_ts` abweicht,
bestätigen es). Stop (aus `risk_amount / qty`: 7.335 von 7.335 plausibel, und
bei den Stopausstiegen gegen den tatsächlichen Ausstiegspreis bestätigt — 4.647
von 4.648, also 99,98 % mit **einer** Ausnahme, die nicht auf 100 % gerundet
wird). Rolle und Gebühr je Fill exakt.

**Verloren.** `reference_price` (nie gespeichert — Schlupf ist für diese
Population nicht messbar), `identity_stamp`, `venue`, `policy`, und jede
tatsächliche Grösse. Dazu das **geplante** Ziel für alle 4.651 Fills, die nicht
im Ziel endeten.

**Und ein eigener Befund:** `snapshot_hash` ist in **allen 7.335** Fills leer.
Ein Herkunftsfeld, das im Datensatz steht und nie geschrieben wurde, ist die
unangenehmste Form von Lücke — es sieht in jeder Spaltenliste nach Herkunft aus.
Es wäre zugleich das wertvollste gewesen. Genau das leistet `decision_id` jetzt.

**Daraus folgt die Reihenfolge:** die Herkunft gehört in den *nächsten* Replay
hinein, nicht hinterher an den alten.

---

## 8. Was offen bleibt

| Punkt | Zustand |
|---|---|
| `FillProvenance` je Fill im Replay erzeugen | Die Aufzeichnung steht, der Erzeuger nicht. Braucht `plan.py`, `broker.py`, `engine.py` — und das sind Module im Entscheidungsabschluss, also ein eigener Lauf mit Gleichheitsbeweis. |
| `DEFAULT_SPEC` durch die echten Instrumentregeln ersetzen | Jetzt vollständig bemessen: +0.0014 R aus der Gebühr, −0.0002 R aus den Schrittweiten (2 von 7.335 Fills). Ein registrierter Arm, kein stiller Edit — aber der erwartete Effekt ist bekannt und klein. Der Schnappschuss liegt in `data/venue_specs/binance.json`. |
| `analysis/context.py` hartkodierte Venue | Weiter im Widerspruch zur Konfiguration. `venues_agree()` meldet es jetzt. |
| Phase 3 (Testnet-Semantik), Phase 4 (Policy B) | Weiter blockiert: alle Kerzen sind Binance, ausführbar ist nur Bybit. `maker_role_proven` bleibt `false`. |
| `qty_step`-Wirkung auf die genommene Population | **Geschlossen** am 18.10.2026: 2 von 7.335 Fills, −0.0002 R. Siehe §2. |
| Spec-Schnappschuss im Replay verwenden | Die Datei existiert und ist geprüft; der Replay liest weiter `DEFAULT_SPEC`. Das ist der eine Edit, der aus den beiden Messungen oben folgt. |
