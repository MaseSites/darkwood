# Nachprüfung des Risiko-Audits — vier Defekte, zwei brauchbare Vorschläge

**Stand 11.10.2026.** Untersucht mit vier parallelen Agenten, je einem Defekt
aus `audit/EVIDENZ_UND_RISIKO_AUDIT.md`, Abschnitte 3.1–3.4. Jeder Vorschlag
anschliessend von **drei Skeptikern** angegriffen, jeder mit einer eigenen
Brille: Korrektheit, Regression, Forschungsintegrität. Auftrag an die
Skeptiker: *widerlegen*, und bei Unsicherheit auf „widerlegt" entscheiden —
ein falscher Eingriff an einer Risikobremse ist schlimmer als keiner.

16 Agenten, 686 Werkzeugaufrufe, 0 Fehler, 44 Minuten.

**Ergebnis: alle vier Defekte bestätigt, aber nur zwei der vier Vorschläge
haben die Prüfung überlebt.**

| Defekt | bestätigt | Vorschlag | Gegenstimmen |
|---|---|---|---|
| 3.1 Drei Sicherungen können nicht auslösen | ja | **verworfen** | 3/3 — *unvollständig, falsch, gefährlich* |
| 3.2 `max_open_positions` nirgends durchgesetzt | ja | brauchbar | 1/3 |
| 3.3 Kostenbasis 4,76 % auseinander | ja | **verworfen** | 3/3 — *falsch, unvollständig, falsch* |
| 3.4 Neustart verschluckt Funding | ja | brauchbar | 1/3 |

**Was in diesem Bericht steht, habe ich selbst nachgerechnet.** Die Agenten
haben die Befunde gefunden; jede Zahl unten ist danach gegen
`data/journal.sqlite`, `data/paper.sqlite` und `data/signals.sqlite` erneut
gemessen.

**Drei Agentenzahlen mussten dabei korrigiert werden**, und das Muster ist
einheitlich: die *Befunde* halten, die *Arithmetik* nicht.

| Agent sagte | gemessen |
|---|---|
| „3 von 12 Konten einen Verlust vor dem Halt" | **2** — der Agent zählte die Waise mit, die er selbst als Fremdkörper nachgewiesen hatte |
| „sechs gleichzeitig offen am 08.10." | **fünf** (ADA, AVAX, BNB, BTC, DOT), in beiden Zählweisen |
| Haltedauer „13,29 h" | 13,29 h — stimmt, und widerlegt die 9,20 h des Audits |

Ein Prüfer, dessen Befund richtig und dessen Zahl falsch ist, ist genau so
nützlich wie einer mit beidem richtig — solange jemand nachrechnet. Das ist
der Grund, warum dieser Abschnitt existiert.

---

## 1. Ein neuer Defekt: das Journal ist nicht das Kontobuch

**Gefunden beim Widerlegen von 3.1, nicht gesucht.** Ein Skeptiker versuchte
zu zeigen, dass der Vorschlag die Verlustserien falsch zählt, und stiess
dabei auf eine Abweichung zwischen Journal und Kontobuch.

Abstimmung `1000 + Σ net_pnl` aus dem Journal gegen `accounts.equity`:

| Symbol | Journal | Konto | Lücke |
|---|---|---|---|
| elf Symbole | — | — | **0,0000** (auf den Rappen) |
| **BTCUSDT** | 936,1945 | 991,2427 | **+55,0482** |

Die Lücke ist auf vier Dezimalstellen das Nettoergebnis **einer** Zeile:

```
live-BTCUSDT-1790928000000   02.10 08:00 -> 02.10 12:30
  R -1,1045   netto -55,0482
  qty 0,06    Hebel 10   Risiko 49,8420   Einstieg 86.092,30
  run_signature None   decision_version None
```

Der zweite BTC-Trade, sechs Tage später, hat `qty 0,006` — **ein Zehntel** —
und 8,604 USDT Risiko. Und das Tally des Kontos zählt `opened: 1, closed: 1`.

**Das ist ein Trade aus einer zerstörten Kontogeneration.** Er steht im
Journal, das Konto kennt ihn nicht, und er wurde unter einer anderen
Risikoeinstellung genommen: **49,84 USDT auf 1.000 USDT sind 4,98 %, gegen
einen harten Deckel von 3 %.**

### Was er beschädigt

1. **Die Vorwärtsstichprobe.** Jede Rechnung über „die 24 Live-Trades"
   enthält ihn. Bereinigt sind es 23 Trades und **+0,0829 R** statt
   +0,0335 R. `audit/ZIEL_30_10_GERECHNET.md` ist entsprechend korrigiert.
2. **Jede Verlustserie auf BTCUSDT.** Ungefenstert gezählt, wie
   `risk/limits.py:102-112` es tut, hat BTCUSDT eine Serie von 2. Ohne die
   Waise ist es 1.
3. **Die Zahl 49,842 taucht an einer dritten Stelle auf** — siehe
   Abschnitt 4.1. Das Audit hat sie dort als Risikobudget eines *anderen*
   Trades benutzt und damit einen Defekt um Faktor 5 zu klein gerechnet.

### Was dagegen zu tun ist

Nicht löschen. Der Eintrag ist eine wahre Aufzeichnung eines Trades, der
stattgefunden hat. Was fehlt, ist die Zugehörigkeit: `run_signature`,
`decision_version` und `code_version` sind bei ihm **leer**, wie bei allen
Zeilen bis zum 09.10. — 18 von 25 ohne Signatur, 20 von 25 ohne
Entscheidungsstempel.

`journal/record.py` begründet diese Felder selbst damit, dass eine
Eigenschaft, die man nur durch Git-Archäologie findet, keine aufgezeichnete
Eigenschaft ist. Hier ist der Fall eingetreten, für den sie gedacht waren,
und sie waren leer.

**Nachgemessen am 12.10.:** `_record` stempelt heute alle drei, in zwei
Wellen eingeführt, und die Lücke ist damit historisch und schliesst sich
selbst. Was folgt, ist kein Rückfüllen, sondern ein Filter — siehe
Abschnitt 2.4.

---

## 2. Defekt 3.1 — der Vorschlag ist einstimmig verworfen

Die drei Sicherungen `max_daily_loss_pct`, `max_weekly_loss_pct` und
`cooldown_after_consecutive_losses` lesen alle `AccountState.recent_trades`,
und **alle drei Stellen, die einen `AccountState` bauen, übergeben `[]`**.
Das ist bestätigt — und der Befund ist sogar schärfer als das Audit sagt:

> `ClosedTrade(` wird in der Produktion **nirgends** konstruiert. Der einzige
> Konstruktionsaufruf im ganzen Baum steht in `tests/test_proposals.py:90`.
> Das Protokoll, das einen erzeugen soll —
> `domain/protocols.py:147 Executor.close_position(symbol) -> ClosedTrade | None`
> — ist in `execution/order.py:315` als `-> str | None` implementiert, einer
> Order-ID. Die Sicherungen verbrauchen einen Typ ohne Produzenten, und der
> deklarierte Rückgabetyp stimmt mit seiner einzigen Implementierung nicht
> überein.

Der Vorschlag war, in `live/paper.py:_maybe_open` zwischen Zeile 586 und 600
eine Prüfung einzusetzen, die ihre Historie aus dem Journal liest. Alle drei
Skeptiker haben ihn verworfen.

### 2.1 Er bewaffnet die Bremsen dort, wo kein Geld liegt

Das Tor vor jeder Order, die eine Börse erreichen kann, ist
`proposals/builder.py:260`. Seine `AccountState` kommt aus
`scripts/run_live.py:117-126` und `scripts/run_dashboard.py:222-229` — genau
den zwei Stellen, die der Vorschlag ausdrücklich nicht anfasst. Nach dem
Eingriff wären die Bremsen auf dem Papierpfad scharf (null Geld) und am Tor
vor der Börse weiterhin tot. **Der Vorschlag benennt drei kaputte Stellen und
reparierte eine.**

Und die zwei übrigen sind kein Einzeiler: `starting_equity_today=args.equity`
in `run_live.py:120-121` ist genau der Fehler, den `risk/limits.py:147-149`
in einem Kommentar beschreibt — „otherwise the allowance shrinks as losses
accumulate and the limit is never quite reached". Selbst mit gefüllter
Historie könnten die Verlustdeckel dort strukturell nicht auslösen.

### 2.2 Er bricht eine bestehende Messung

`decision_closure()` zählt heute **56** Dateien, und `traidingbrain.risk.limits`
ist nicht darunter — selbst nachgezählt. Der Eingriff macht 57.

`scripts/verify_claims.py:139-142` hält
`Fact("Dateien im Live-Entscheidungspfad", …, 56, fixed=True)`. Der Eingriff
lässt also `verify_claims.py` mit Exitcode 1 enden, und drei weitere Stellen
tragen die Zahl 56 im Text.

### 2.3 Und er ist nicht kostenlos — zwei Konten sind scharf

Die Begründung des Vorschlags war „0 von 21 blockiert, auf vier Weisen
gemessen". Das ist eine **rückwärts** gerichtete Aussage über die
aufgezeichnete Stichprobe, benutzt, um eine **vorwärts** wirkende Änderung zu
rechtfertigen.

Verlustserien jetzt, ungefenstert gezählt wie `limits.py:102-112`:

| | Serie |
|---|---|
| AVAXUSDT | **2** |
| DOTUSDT | **2** |
| BTCUSDT | 2 → **1** nach Abzug der Waise |
| die übrigen neun | 0 oder 1 |

`cooldown_after_consecutive_losses` steht auf 3. **Zwei von zwölf Konten sind
einen Verlust von einem 24-Stunden-Halt entfernt**, und weil der dritte
Verlust gleichzeitig `last_loss_ts()` setzt, greift der Halt sofort.

> Der Skeptiker schrieb „3 von 12". Das ist die Zahl **mit** der Waise, die er
> selbst im gleichen Atemzug als Fremdkörper nachgewiesen hat. Bereinigt sind
> es zwei. Das Argument hält, die Zahl nicht — und es ist dieselbe Sorte
> Fehler, gegen die der ganze Bericht geschrieben ist.

### 2.4 Nachtrag vom 12.10.: der erste Schritt war falsch benannt

Die erste Fassung dieses Abschnitts verlangte, „erst die Herkunftsfelder zu
füllen". **Das geht nicht, und es muss auch nicht.** Nachgemessen:

`live/paper.py:_record` stempelt `run_signature`, `decision_version` und
`code_version` **bereits** — eingeführt in zwei Wellen, und die Wellen sind
in den Daten sichtbar:

| | run_signature | decision_version |
|---|---|---|
| ab 10.10. 13:01 | ja | **ja** |
| 09.10. 23:48 – 10.10. 04:52 | ja | nein |
| bis 09.10. 11:32 | nein | nein |
| **von 25 Zeilen** | **7** | **5** |

Die Lücke ist also **historisch und schliesst sich selbst**. Rückwirkend
füllen wäre Erfindung: welche Konfiguration einen Trade vom 02.10. erzeugt
hat, lässt sich nur aus der Git-Historie erschliessen, und genau das nennt
`journal/record.py` keine aufgezeichnete Eigenschaft.

**Der richtige erste Schritt ist deshalb ein Filter, keine Rückfüllung.** Eine
Bremse darf nur Zeilen lesen, die sie zuordnen kann — also die der laufenden
Signatur. Und das ändert die Lage:

| gelesene Historie | n | Konten mit Verlustserie ≥ 2 |
|---|---|---|
| alle Zeilen | 25 | AVAXUSDT, BTCUSDT |
| **nur laufende Signatur** | **7** | **keine** |

**Die Gegenstimme „gefährlich" hing an einer Historie, die die Bremse nicht
lesen darf.** Gefiltert ist kein Konto scharf — der Eingriff wäre auf dem
Datenstand tatsächlich kostenlos, und zwar aus dem richtigen Grund statt aus
der rückwärts gerichteten „0 von 21"-Zählung.

Das entkräftet den Einwand nicht, es **präzisiert** ihn: ungefiltert zu lesen
war das Problem, nicht das Bremsen.

### 2.5 Nachtrag vom 12.10.: die fehlende Aufzaehlung, nachgeholt

Die Regression-Gegenstimme verwarf den Vorschlag unter anderem damit, dass
`refused_by=None` auf einer `action=REFUSED`-Zeile von einer bestehenden
Studie als **genommen** gelesen wird. Das ist richtig und nachgeprueft:
`scripts/study_meta_label.py:465` entscheidet mit
`taken = [c for c in confirm if c.refused_by is None]` — nicht am Feld
`action`.

Ein Limit-Block muss also **beides** setzen. Und bevor dem `Rule`-Enum ein
sechster Wert hinzugefuegt wird, gehoert aufgezaehlt, wer ihn liest. Das war
die Luecke, fuer die der Vorschlag „unvollstaendig" bekam; hier ist sie
geschlossen.

| Leser | was er tut | Wirkung eines neuen Werts |
|---|---|---|
| `study_costcap.py:239` | `refused_by == Rule.COSTS` | **unbedenklich** — ein neuer Wert ist einfach nicht COSTS |
| `study_exits.py:288` | `refused_by in SAFETY_RULES` | **muss ergaenzt werden** |
| `study_meta_label.py:194` | `refused_by in SAFETY_RULES` | **muss ergaenzt werden** |
| `study_meta_label.py:465` | `refused_by is None` heisst genommen | **unbedenklich, aber nur** wenn der Block einen Grund setzt |
| `study_refused.py:242,278,308` | gruppiert nach `refused_by.value` | **unbedenklich** — es erscheint eine neue Gruppe, und das ist richtig |
| `study_the_clock.py:377` | liest die Spalte, verzweigt nicht | **unbedenklich** |
| `api/paper.py:88,175` | `refused_by_risk`, ein **Zaehler** | **unbeteiligt** — gleiches Wort, andere Sache |
| `live/loop.py:75,83,234` | derselbe Zaehler | **unbeteiligt** |

Zwei echte Stellen also, eine Invariante, und zwei Namenskollisionen, die
beim Greppen wie Treffer aussehen und keine sind.

### 2.6 Und dabei ein eigener Defekt: `SAFETY_RULES` gibt es zweimal

| | Inhalt |
|---|---|
| `scripts/study_exits.py:100` | `{"liquidation", "chance_risiko", "kosten"}` |
| `scripts/study_meta_label.py:109` | `frozenset({"liquidation"})` |

Gleicher Name, derselbe erklaerte Zweck — „Ablehnungsgruende, die eine
Auswahlregel NICHT ueberstimmen darf" — und **verschiedene Mengen**.

`study_exits` haelt eine Kosten- und eine Chance-Risiko-Ablehnung fuer
unantastbar, `study_meta_label` nicht. Die beiden Studien beantworten damit
die Frage „darf ein Modell diese Ablehnung ueberstimmen?" unterschiedlich,
und nichts gleicht sie ab. Welche der beiden richtig ist, ist eine
Entscheidung und keine Formsache: die weitere Menge macht das Meta-Modell
schwaecher, die engere laesst es Trades ueberstimmen, die eine Risikoregel
abgelehnt hat.

Gefunden, weil vor dem Hinzufuegen eines Enum-Werts die Leser aufgezaehlt
wurden. Ohne diese Aufzaehlung waere ein sechster Wert in genau eine der
beiden Mengen gewandert, und welche, haette vom Zufall abgehangen.

Der Satz gehoert an eine Stelle, nicht an zwei. Als eigener Schritt, weil
ihn zusammenzulegen bedeutet, sich fuer eine der beiden Mengen zu
entscheiden — und das ist eine Messfrage, keine Aufraeumarbeit.

### Was daraus folgt

**Der Eingriff findet weiter nicht ad hoc statt**, aber der Weg ist jetzt
konkret, in dieser Reihenfolge:

1. **Die Bremse filtert auf die laufende `run_signature`.** Sieben Zeilen sind
   dünn, aber zuordenbar; 25 sind drei Konfigurationsepochen plus ein Trade
   aus einer zerstörten Kontogeneration. Eine dünne richtige Historie schlägt
   eine dicke falsche.
2. **`starting_equity_today` korrigieren**, an beiden übrigen Stellen. Sonst
   können die Verlustdeckel am Börsentor nicht auslösen, egal was die
   Historie sagt — `risk/limits.py:147-149` beschreibt den Fehler in einem
   Kommentar.
3. **Dann alle drei Baustellen gemeinsam**, nicht eine. Eine Bremse auf dem
   Papierpfad scharf zu machen und am Börsentor tot zu lassen, ist die
   schlechtere von zwei Welten: sie kostet Trades, wo kein Geld liegt.
4. Und die Umstellung gehört in den Entscheidungsstempel, mit angepasstem
   `verify_claims.py` — `decision_closure()` wächst von 56 auf 57, und die
   Zahl steht an vier Stellen im Text. Eine Zuverlässigkeitskorrektur ist
   eine Strategieänderung.

---

## 3. Defekt 3.3 — das Audit hat an dieser Stelle recht gehabt und ist es nicht mehr

Live bepreist eine Runde mit 0,00100, der Replay mit 0,00105 — bestätigt, und
der Grund ist, dass der Live-Pfad die echte Gebührentabelle holt
(`ccxt binance`: maker 0,0002 / taker 0,0005) und der Replay `DEFAULT_SPEC`
nimmt (maker 0,0002 / taker 0,00055 + 3 bp).

Das Audit schreibt dazu:

> „**Die Vorwärts-Elf sind davon nicht verunreinigt**: kein Live-Trade wurde
> genommen, den die Replay-Gebühr abgelehnt hätte."

**Das gilt seit heute 16:00 UTC nicht mehr.** Selbst nachgerechnet über die
14 genommenen Live-Signale mit Kostenquote, jede mit 1,05 skaliert:

| Signal | Quote live | ×1,05 | Urteil |
|---|---|---|---|
| **XRPUSDT-1791734400000-A** | 0,077440 | **0,081312** | **abgelehnt** (Deckel 0,08) |
| SOLUSDT-1791691200000-B | 0,074733 | 0,078470 | genommen |
| die übrigen zwölf | ≤ 0,065738 | ≤ 0,069025 | genommen |

Genau eines kippt, und es ist zum Trade geworden:
`live-XRPUSDT-1791734400000`, geöffnet 11.10. 16:00 UTC, **−1,0756 R,
−10,7549 USDT**.

**Das ist kein Fehler des Audits, sondern eine Behauptung mit Verfallsdatum.**
Sie war wahr, als sie geschrieben wurde, und niemand hat sie neu geprüft, als
sich die Grundlage änderte. Genau dafür existiert `scripts/verify_claims.py`
mit seiner Tier-2-Prüfung gegen Daten — und diese Behauptung stand nicht
darin.

### Warum der Vorschlag trotzdem verworfen ist

Weil er **die Zusammensetzung der Vorwärtsstichprobe ändert**, nicht nur ihre
Bepreisung. Die Kostenquote ist exakt linear in der Rundenrate
(`risk/sizing.py:162`), und eine Umstellung auf die teurere Basis
schliesst diesen Trade rückwirkend aus. Dazu:

* Der einzige Test, der die geänderten Zeilen berührt
  (`tests/test_data_layer.py:428-437`), **kann die Änderung nicht sehen**:
  `DEFAULT_SPEC["taker_fee"]` ist dieselbe 0,00055 wie der Fixture-Wert. 324
  Tests bleiben grün. Der Defekt ist nicht ungetestet, er ist
  **uninstrumentiert**.
* Und die billigere Basis ist die *genauere*. Sie zum Replay zu ziehen heisst,
  den Replay teurer zu machen, nicht den Live-Pfad korrekter.

**Was stattdessen zu tun ist:** die Behauptung in `verify_claims.py`
aufnehmen, damit ihr Verfall auffällt, und den Replay auf die **gefetchte**
Basis umstellen — in einem eigenen, angemeldeten Schritt, mit neuem
Entscheidungsstempel, nicht als Nebenwirkung einer Aufräumaktion.

---

## 4. Defekt 3.4 — der Vorschlag ist brauchbar, vier Zahlen des Audits nicht

Der Mechanismus ist bestätigt: `paperstate.py` ruft `broker.skip_to(...)`,
während die Position noch abgekoppelt ist, und `_charge_funding` verbraucht
jede Rate mit `position=None`.

Der brauchbare Vorschlag ist **Variante (c)**: den Funding-Cursor
persistieren, dann die Position *vor* dem Verbuchen anhängen. Begründung, die
die Varianten (a) und (b) ausschliesst: `_funding_settled_ts` ist der einzige
Teil des Zustands, der sagt, *welche* Raten verbraucht sind — `funding_paid`
ist eine Summe, und eine Summe kann das nicht sagen. Ohne ihn ist keine
Reihenfolge korrekt, weil der Broker „schon verbucht" nicht von „noch
geschuldet" unterscheiden kann.

### 4.1 Vier Zahlen des Audits sind falsch

| Audit | gemessen | Richtung |
|---|---|---|
| „+0,0014 R" | **+0,00703 R** | Faktor **5,0 zu klein** |
| „vier der fünf überspannenden Trades belastet" | 15 von 24 überspannen, **7** mit Lücke | anders gezählt |
| „live Mittel 9,20 h" | **13,29 h** (Median 4,29 h) | nicht reproduzierbar |
| „~0,001 R, bewegt keine Schlussfolgerung" | als Mittel richtig (+0,000411 R/Trade), schlimmster Einzelfall **+0,01022 R** | Rand fehlt |

Die erste ist die interessante. +0,070938 USDT geteilt durch das
*eigene* Risikobudget des Trades (10,0881 USDT) sind +0,00703 R. Die
Audit-Zahl +0,0014 R unterstellt ein Risiko von 50,67 USDT — und das ist das
Budget der **ersten Generation**, dasselbe 49,842, das in Abschnitt 1 als
Waise auffiel. **Der Fehler läuft in die Richtung, die den Defekt kleiner
aussehen lässt**, und er entstand dadurch, dass zwei Kontogenerationen
vermischt wurden.

Richtig und exakt im Audit: Notional 709,3768, die Abrechnung am 07.10. 00:00
mit Rate +0,0001, +0,070938 USDT nicht eingenommen, `funding` als 0,0
verbucht, und das Vorzeichenargument — ein Short bei positiver Rate *erhält*,
der Ausfall liess den Trade also schlechter aussehen.

### 4.2 Die Einschränkung, die der Vorschlag selbst falsch darstellt

Der Vorschlag warnt, der Eingriff bewege `net_pnl` und `r_multiple` „auf
jedem über einen Neustart gehaltenen Trade — bis zu +0,0102 R". **Das ist für
die gemessenen Fälle falsch.** Live-Journalzeilen werden nur bei Schluss
geschrieben (`live/paper.py:645-710`); die 24 geschlossenen Zeilen sind
eingefroren. Die gemessenen +0,0926 USDT sind **nicht** rückholbar.

Der Eingriff wirkt also **nur nach vorn**, und die Schlagzeilenzahl misst die
Geschichte des Fehlers, nicht die Wirkung der Korrektur. Das ist der Einwand,
der durchkam, und er ist richtig.

### 4.3 Die Gefahr liegt in der Migration

`ALTER TABLE … ADD COLUMN funding_settled_ts INTEGER` lässt bestehende Zeilen
`NULL`. Würde `load` das zu 0 machen und `restore_into` den Cursor bei 0
setzen, während die Position schon hängt, **berechnet `_charge_funding` jede
Rate ein zweites Mal** — auf der offenen LINKUSDT-Position sind das 13
Abrechnungen, +0,0640 → +0,1279 USDT, also +0,0062 R erfundenes Einkommen,
und das bei **jedem** Neustart.

Die Unterscheidung `None` gegen `0` ist tragend. Drei Positionen sind gerade
offen (ADA, LINK, DOT), die Migration landet also mitten im Trade.

---

## 5. Defekt 3.2 — das Setting ist nicht tot, es gilt für einen anderen Pfad

`max_open_positions = 2` wird auf dem Papierpfad nicht durchgesetzt —
bestätigt. Aber die interessante Antwort ist, dass die Frage falsch gestellt
war. Drei Lesarten, und keine der beiden naheliegenden hält:

**Pro Konto** ist die strukturelle Grenze 1 (`broker.py:234`, `paper.py:550`),
und `settings.py:370` ist `Field(ge=1)` — es gibt **keinen** legalen Wert, der
das Verhalten ändern könnte. Löschen wäre aber eine echte
Sicherheitsregression, weil das Setting auf dem einen Pfad, der Geld berührt
(`run_live.py:124` → `execution/order.py:285`, ungefiltertes
`fetch_positions`), **scharf** ist.

**Über Konten** wäre die faktische Grenze 12, und „2" eine falsche Behauptung
— gemessener Höchststand **fünf** gleichzeitig offen am 08.10. 20:02 UTC
(ADA, AVAX, BNB, BTC, DOT), gegen konfigurierte zwei. Eine
Portfoliogrenze scheidet trotzdem aus, vierfach: sie poolt Konten, die
`live/paper.py:29-32` ausdrücklich getrennt hält, damit der Vorwärtslauf mit
den Backtests vergleichbar bleibt; der Platz würde nach Listenposition
vergeben, nicht nach Signalqualität, also gewännen BTC und ETH strukturell
jeden umkämpften Balken; `sim/engine.py:193` hat keine Portfoliosicht, Replay
und Vorwärtslauf würden auseinanderlaufen; und sie ändert, welche Trades
existieren.

**Richtig ist:** `max_open_positions` ist eine wahre, durchgesetzte Aussage
über **ein** Börsenkonto, das mehrere Symbole halten kann. Dieses Konto
existiert auf genau einem Pfad. Es ist *keine* Aussage über zwölf getrennte
Einzelslot-Simulationen.

Der Eingriff ist also ein **Kommentar und ein Test**, kein Codepfad. Verhalten
unverändert, die 24 Live-Trades unberührt.

Und die Messung, die das belegt, war schon da: `scripts/study_dead_limits.py`
(Commit `f3df11d`, 10.10.) zählt unter der Portfolio-Lesart 4 von 24
blockiert, mit allen vier Grenzen 9 von 24, Mittel +0,0335 → +0,2796 R über
15. **Diese +0,2796 R sind keine Verbesserung** — eine nachträgliche Zählung
über n=15, und das Skript nennt sich selbst eine Untergrenze, weil eine
blockierte Order ihren Platz freigibt und ein echter Neulauf andere Trades
nimmt.

---

## 6. Was jetzt passiert

**Angewendet wird:**

* 3.2 — Kommentar und Test, die festhalten, für welchen Pfad das Setting gilt.
* 3.4 — Variante (c) mit `None`-sicherer Migration und einer ausdrücklichen
  Prüfung, dass der Broker vor dem Anhängen leer ist. Mit neuem
  Entscheidungsstempel.

**Nicht angewendet wird:**

* 3.1 — erst Herkunftsfelder, dann `starting_equity_today`, dann alle drei
  Baustellen zusammen.
* 3.3 — erst die Behauptung in `verify_claims.py`, dann die Umstellung als
  eigener angemeldeter Schritt.

**Neu aufgenommen:**

* Der Waisen-Trade als Defekt 3.9, mit der Folge für jede Aussage über „die
  Vorwärtsstichprobe".
* Die abgelaufene Behauptung aus 3.3 als Prüfung in `verify_claims.py`.

Die beiden verworfenen Vorschläge sind der Ertrag dieses Durchgangs, nicht
sein Ausfall. Beide hätten eine Messung beschädigt, einer davon eine
Risikobremse — und beide sahen beim Schreiben richtig aus.
