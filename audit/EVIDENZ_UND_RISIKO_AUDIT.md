# Audit vom 10.10.2026 — der Vorwärtsvorteil war mein eigener Schnitt

Zehn Dimensionen, read-only gemessen, jeder behauptete Defekt anschliessend
**gegnerisch nachgeprüft**: 58 Agenten, 0 Fehler, 1 317 Werkzeugaufrufe,
29 Minuten. **8 Defekte bestätigt, 40 widerlegt.** Die Quote ist der Punkt:
vier Fünftel der ersten Befunde hielten der Nachprüfung nicht stand, und ohne
sie wären sie hier als Ergebnisse gelandet.

Reproduktion: der Lauf liegt als Skript und Journal unter
`.claude/.../workflows/`, Lauf-Kennung `wf_04d05a17-6e6`. Jede Zahl unten habe
ich **selbst nachgerechnet**, nicht übernommen — an zwei Stellen mit anderem
Ergebnis als der Agent, und beide Male war der Unterschied selbst der Befund.

---

## 1. Der Hauptbefund: konsequent geschnitten ist der Vorteil weg

`audit/DIE_VORWAERTSSTICHPROBE.md` schnitt die Stichprobe bei **04.10.
21:52 UTC** — der letzten Änderung am *Code*, die verändert, welche Balken
entschieden werden. Was dort fehlte: eine spätere Änderung an der
*Konfiguration*, die verändert, welche Signale **angenommen** werden.

**Am 05.10. um 19:15 UTC fiel der Kostendeckel von 0,15 auf 0,08**
(`config/risk.yaml`, `max_cost_fraction_of_risk`). Drei Trades der Stichprobe
reissen diesen Deckel — und **alle drei sind Gewinner**:

| eröffnet (UTC) | Markt | R | geplante Kostenquote |
|---|---|---|---|
| 05.10. 13:00 | LINKUSDT | **+1,4691** | **0,0997** |
| 05.10. 19:00 | ATOMUSDT | **+1,4511** | **0,1275** |
| 07.10. 11:30 | LTCUSDT | **+1,9789** | **0,0808** |

Keiner von ihnen verletzte den Deckel, der zu seiner Zeit galt. Unter dem
*heutigen* Regelwerk entstünde keiner.

### Was das mit der Zahl macht

| Schnitt | n | Mittel | Trefferquote | z gegen −0,0867 R |
|---|---|---|---|---|
| nur Code-Schnitt *(der berichtete Stand)* | 13 | +0,5075 R | 53,8 % | 1,524 |
| **+ heutige Kostenregel, Replay-Gebühr** | **10** | **+0,1699 R** | **40,0 %** | **0,577** |
| + heutige Kostenregel, Live-Gebühr | 11 | +0,3343 R | 45,5 % | 0,993 |

**Der Vorwärtsvorteil von +0,7867 R, der diesen Lauf drei Tage lang getragen
hat, war ein inkonsistenter Schnitt.** Konsequent angewandt steht er bei
**+0,17 R** — gegen +0,8701 R, die das Ziel verlangt, und mit einem Abstand von
0,577 Standardfehlern zur Null-Erwartung, also nicht einmal in der Nähe der
*unkorrigierten* Schwelle von 1,96.

### Warum zwei Zeilen, und warum das selbst ein Befund ist

Der Agent fand **zwei** Trades über dem Deckel, ich finde **drei**. Der
Unterschied ist LTCUSDT bei 0,0808 gegen 0,0770 — und er entsteht, weil der
Agent mit der *Live*-Gebühr rechnet und ich mit der *Replay*-Gebühr. Genau
diese Differenz ist Defekt 8 unten, hier konkret geworden: **ein Trade liegt im
strittigen Band, und welche Hälfte der Codebasis ihn beurteilt, entscheidet, ob
er zur Stichprobe gehört.**

### Die unbequeme Einschränkung, die bleibt

Das ist die **Teilmenge der 13, die die heutige Kostenregel zulässt** — nicht,
was die heutigen Regeln *erzeugt hätten*. Eine abgelehnte Order gibt ihren
Platz frei, und ein Neulauf nähme andere Trades. Die ehrliche Form ist
deshalb: *die vorhandene Evidenz stützt +0,17 R, und ob ein Neulauf mehr oder
weniger ergäbe, ist ungemessen.*

Und mindestens drei weitere Commits im Fenster berühren den Entscheidungspfad
und sind **von mir ungemessen**: `dd7c0c1` (05.10. 12:38), `3425892`
(„die Haltezone verweigert den Handel", 07.10. 10:24), `8f26cdb` (09.10.
13:28). Jeder ist ein Kandidat für dieselbe Behandlung. Die Stichprobe kann
also noch kleiner werden, nicht grösser.

---

## 2. Und das Experiment konnte die Frage nie beantworten

Unabhängig davon, und für den Termin wichtiger: meine Mächtigkeitsrechnung in
`audit/WANN_WEISS_MAN_ES.md` war die **falsche Rechnung**. Sie löst
`n = (z·σ/μ)²` — das ist eine *Präzisions*-Rechnung und keine
*Mächtigkeits*-Rechnung. Sie sagt, wie schmal ein Intervall wird, nicht mit
welcher Wahrscheinlichkeit ein echter Effekt entdeckt wird.

Exakt gerechnet (exakte Binomialverteilung, kein Normalschluss):

| | |
|---|---|
| exaktes P(≥ 7 Treffer aus 11 \| p = 0,354) | **0,0532** |
| korrigiertes Niveau (Bonferroni auf 55) | 0,000909 |
| **Verhältnis** | **58-fach darüber** |
| Bonferroni-Clopper-Pearson-Intervall für 7/11 | **[0,158; 0,964]** |

Das Intervall ist 0,81 breit und enthält **jede** denkbare Null, eine Münze
eingeschlossen. Und die Zahl, die alles entscheidet:

> **Die prospektive Mächtigkeit bei n = 11 und korrigiertem Niveau ist 0,0505.**
> Der Verwerfungsbereich beginnt bei **10 von 11** Treffern. Selbst ein
> *echter, dauerhafter* Vorteil von 63,6 % hätte nur 5 % Chance gehabt, von
> diesem Versuch gezeigt zu werden — und **7 Treffer konnten nie bestehen.**

Das heisst: der Vorwärtslauf war in dieser Grösse kein Test, sondern eine
Beobachtung. Wie viele Trades es wirklich bräuchte:

| Frage | 80 % Mächtigkeit | 90 % |
|---|---|---|
| 63,6 % gegen 35,4 % trennen | 50 | 62 |
| +0,7867 R gegen −0,0867 R trennen (σ = 1,4061) | 45 | 55 |
| **dazu das Replikationstor (zwei getrennte Fenster)** | **~100** | **~128** |

Bei 1,9 Trades/Tag sind 100 bis 128 Trades **53 bis 67 Tage**. Ab dem 10.10.
mit 13 vorhandenen: **Ende November bis Mitte Dezember 2026.**

### Die Folge, und sie ist unangenehm

**„Das Ziel prüft sich selbst bis zum 30.10." war falsch.** Der Satz stand
dreimal in diesem Projekt — in `WANN_WEISS_MAN_ES.md`, im Zustandsbericht und
in der Vault-Notiz — und er stand auf der Präzisionsrechnung. Mit Mächtigkeit
und mit beiden Toren des Projekts gerechnet liegt die Antwort **nach** dem
Stichtag, nicht davor.

### Und die Reihenfolge der elf war nicht zufällig

Die Folge ist `WWWWWWWLLLL`, in Eröffnungs- **und** in Schlussreihenfolge.
Läufe = 2, das Minimum; erwartet unter Austauschbarkeit 6,09. Exakt
P(Läufe = 2) = 2/330 = **0,00606**. Autokorrelation auf Verzögerung 1:
**+0,6949**, exakter Permutationstest p = **0,0018**.

**Die elf Trades sind zwei Regimeblöcke, keine elf Ziehungen.** Damit ist das
Binomialmodell, auf dem jede Zahl in diesem Abschnitt ruht, falsch
spezifiziert — und alle Wahrscheinlichkeiten oben sind **optimistische
Obergrenzen**.

---

## 3. Die acht bestätigten Defekte

Nach Dringlichkeit, nicht nach Entdeckung.

### 3.1 Drei von sechs Sicherungen können in keinem Prozess auslösen

`max_daily_loss_pct` (0,05), `max_weekly_loss_pct` (0,10) und
`cooldown_after_consecutive_losses` (3) lesen alle `AccountState.recent_trades`
(`risk/limits.py:94-112`, verbraucht bei :151, :159, :167). **Alle drei
Stellen, die einen `AccountState` bauen, übergeben `recent_trades=[]`:**
`scripts/run_live.py:120-127`, `scripts/run_dashboard.py:222-229` (dort
zusätzlich `open_positions=[]` und `now_ms=0`), und `api/app.py:176` gibt
weiter, was gesetzt wurde — also das des Dashboards.

Also ist `realised_today()` = 0, `realised_this_week()` = 0 und
`consecutive_losses()` = 0 in **jedem** laufenden Prozess. Die Sicherung gegen
die Verlustserie, die der eigene Docstring des Moduls als ihren Zweck nennt,
kann nicht feuern.

**Und die Tests sind grün**, weil sie den `AccountState` von Hand bauen, den
die Produktion nie baut (`tests/test_proposals.py:320, :333, :345`). Das ist
dasselbe Muster wie am 09.10., als sechs grüne Tests einen Absturz im echten
Objekt verdeckten — [[a-fixture-that-is-not-shaped-like-the-real-thing]].

### 3.2 `max_open_positions = 2` wird nirgends durchgesetzt

Gemessen zum Zeitpunkt des Audits: **vier** offene Positionen (ADA, AVAX, BNB,
LINK — alle short). Unter den 18 geschlossenen Trades war der Höchststand drei,
an vier verschiedenen Gelegenheiten.

`max_open_positions` wird nur bei `risk/limits.py:135` gelesen. Der
Papierhändler ruft `sim/plan.py:115 assess()`, dessen Signatur `equity` nimmt
und **keine offenen Positionen** — `RiskLimits.check` wird also nie aufgerufen.
Der einzige Aufrufer, der offene Positionen übergibt, ist
`scripts/run_live.py:124`.

**Die Folge ist begrenzt und gehört genannt:** Notional 1 108,45 USDT, Margin
170,22, Risiko-wenn-alles-stoppt 40,23 USDT = **0,333 %** der 12 085,55 USDT
über alle zwölf Konten, weil jedes Konto 1 % seines *eigenen* Kapitals
riskiert. Der Mangel ist „die Konfiguration beschreibt das Verhalten nicht",
nicht „das Risiko ist zu hoch".

`scripts/ratchet.py:198` notiert `max_open_positions` schon als „toten
Konfigurationstext" — aber mit der Begründung „SimBroker hat einen Platz", und
das untertreibt: bei zwölf parallelen Brokern ist die faktische Grenze zwölf.

### 3.3 Der Live-Pfad bepreist eine Runde 4,76 % billiger als der Replay

Aus dem Signalspeicher zurückgerechnet als
`cost_fraction · risk_amount / (qty · entry)`:

| | Wert | Zeilen |
|---|---|---|
| live | **0,00100000** | alle 22 bepreisbaren, 10 Symbole, *ein* Wert |
| replay | **0,00105000** | alle 43 080 bepreisbaren, 12 Symbole, *ein* Wert |

0,00105 ist `DEFAULT_SPEC` exakt (maker 0,0002 + taker 0,00055 + 3 bp
Slippage). 0,00100 bedeutet maker+taker = 0,00070 live statt 0,00075.

Ursache: `scripts/paper.py:86-93` liefert `DEFAULT_SPEC` für jedes Symbol,
`scripts/papertrade.py:132-145` dagegen `source.fetch_symbol_spec`. **Der
Live-Pfad ist hier der genauere** — er holt die echte Gebührentabelle —, und
der Replay rechnet mit einem Vorgabewert, der 7 % höher liegt.

Die Wirkung, gemessen: bei Deckel 0,08 liegt das strittige Band bei
replay-bepreisten Quoten in (0,080; 0,084] — **493 von 22 942
Kosten-Ablehnungen**, also 2,15 % der Kosten-Ablehnungen und 1,03 % aller
Zeilen; die angenommenen Signale steigen von 7 333 auf 7 826, **+6,72 %**.
Minimaler wirtschaftlicher Stop: 1,3125 % des Einstiegs im Replay gegen
1,2500 % live. Und die Kostenregel ist **44,8 %** der Live-Ablehnungen und
47,9 % der Replay-Ablehnungen — also das meistbenutzte Tor im System.

**Die Vorwärts-Elf sind davon nicht verunreinigt**: kein Live-Trade wurde
genommen, den die Replay-Gebühr abgelehnt hätte. Das ist die Antwort auf die
Hypothese, die gestern als „die einzige, die den Vorteil als Artefakt entlarven
könnte" benannt war: **das Band ist echt, die genommene Population nicht
betroffen.** Aber es entscheidet, ob LTCUSDT zur Stichprobe gehört (siehe
Abschnitt 1).

### 3.4 Ein Neustart verschluckt stilles Funding

`live/paperstate.py:182-195`: `restore_into` ruft
`broker.skip_to(last_minute_ts)` auf, **während die Position noch abgekoppelt
ist**. `_charge_funding` verbraucht dabei jede Rate bis zu dieser Minute mit
`position=None` und verbucht nichts.

Belegt an einem der 11: `live-LINKUSDT-1791303300000` (short, 06.10. 16:15 →
07.10. 02:00) überspannt die Abrechnung am 07.10. 00:00, für die
`data/funding/LINKUSDT.parquet` die Rate +0,0001 hält. Notional 709,38 USDT,
also **+0,0709 USDT nicht eingenommen** = +0,0014 R. Vier der fünf
überspannenden Trades wurden belastet, der fünfte nicht.

Weil ein Short bei positiver Rate Funding *erhält*, liess der Ausfall den Trade
**schlechter** aussehen, nicht besser. Bei den heutigen Haltezeiten (live
Mittel 9,20 h) ist das ~0,001 R und bewegt keine Schlussfolgerung — **aber es
skaliert mit der Haltedauer**, und längere Halten sind der ganze Zweck des
Vorwärtsprogramms.

### 3.5 Im Simulator wird Liquidation vor dem Stop geprüft

`sim/broker.py:396-398` prüft die Liquidation **vor** dem Stop, `:506` setzt
`net = -position.margin`. Folge: der schlechteste Trade der gesamten
Replay-Population ist ein Artefakt.

`SOLUSDT-1672552800000`, short, Stop 10,07, Hebel 9×, abgeleitete Liquidation
10,82882778. Verbucht: Ausstieg 10,83207642611111, Grund `liquidation`, netto
−195,71, **R = −3,8849** gegen ein Risikobudget von 50,3779. Der Preis hat
innerhalb derselben Minute **zuerst den Stop** gekreuzt.

Das berührt `audit/E10_STOP_AUSLOESER.md`, wo steht „Liquidation löst in beiden
Armen auf Berührung aus" — richtig, aber die *Reihenfolge* innerhalb der Minute
war nicht geprüft. Für die Randmasse (schlechtester Trade, 5-%-Quantil) ist das
der relevante Fall.

### 3.6 Die Grundlinie war inkonsistent gebündelt

Meine gestrige Grundlinie von **−0,0867 R bei 35,4 %** gewichtete die
Vorwärtsmischung als 5 Trades bei R:R 1,5 und 6 bei 2,0. Die wirklichen
geplanten Verhältnisse sind **{1,5: 4, 2,0: 6, 1,568: 1}** — der Trade bei
1,568 liegt 0,068 von 1,5 entfernt, und die Replay-Seite bündelt mit
|Abstand| ≤ 0,05. Unter der eigenen Bündelung der Replay-Seite ist die Mischung
also **4:6 mit einem unzugeordneten Trade**, nicht 5:6.

Die Grundlinie bewegt sich dadurch nur in der dritten Stelle, aber die
Rechnung war nicht die, die ich beschrieben hatte.

### 3.7 und 3.8

Die beiden verbleibenden bestätigten Defekte sind die Regimeblock-Struktur
(Abschnitt 2, letzter Teil) und die Mächtigkeitsfrage (Abschnitt 2) — beide
dort behandelt, weil sie das Hauptergebnis tragen und keine Codefehler sind.

---

## 4. Was ausdrücklich NICHT gefunden wurde

Vierzig von achtundvierzig behaupteten Defekten hielten der gegnerischen
Nachprüfung nicht stand. Die wichtigsten Freisprüche, weil ein Freispruch
genauso ein Ergebnis ist:

* **Die Risikoschicht ist bei beiden Pfaden dieselbe.** `live/paper.py:600`
  und `sim/engine.py` erreichen beide `sim/plan.py:assess()`, und
  `plan_entry()` ist wörtlich `assess(...).entry`. Geprüft, nicht geglaubt.
* **Die genommene Population ist nicht durch die Gebührendifferenz
  verunreinigt** (3.3).
* **Funding wird live angewandt** — nur der Neustartpfad verliert es (3.4).
* **Die Positionsgrösse stimmt**: `risk_amount = qty · |entry − stop|` hält.
* **Der 1-%-Deckel hat jeden Live-Trade gehalten.**

## 5. Grenzen dieses Audits

**Es ist read-only und hat nichts verändert** — `git status --porcelain` war
nach dem Lauf leer, `data/journal.sqlite` unberührt.

**Zehn Dimensionen sind nicht alle Dimensionen.** Was nicht gemessen wurde,
ist nicht freigesprochen: die drei genannten Commits im Fenster, die
Intrabar-Auflösung live gegen Replay über die ganze Population, und ob ein
Neulauf unter heutigen Regeln mehr oder weniger Trades erzeugt.

**Die Mächtigkeitszahlen setzen Unabhängigkeit voraus**, und Abschnitt 2 zeigt,
dass sie verletzt ist. Die 100 bis 128 Trades sind damit eine **Untergrenze**.

---

## 6. Nachtrag: was das Scharfschalten der toten Sicherungen kostet

Reproduktion:

```bash
python scripts/study_dead_limits.py
```

Abschnitt 3.1 und 3.2 nennen vier Sicherungen, die nicht auslösen können.
Sie zu reparieren ist richtig und **verändert, welche Trades entstehen** —
also schneidet es die Vorwärtsstichprobe. Statt darüber zu mutmassen, ist der
Preis jetzt gezählt.

**Und dabei fällt eine Mehrdeutigkeit auf, die selbst ein Befund ist:** die
Konfiguration sagt nicht, ob die Grenzen **je Konto** oder **über das
Portfolio** gelten. Der Papierhandel führt zwölf getrennte Händler mit je
1 000 USDT und je *einem* Positionsplatz.

| Lesart | `max_open_positions` | Tagesverlust | Wochenverlust | Cooldown | **zusammen** |
|---|---|---|---|---|---|
| **je Konto** | 0 | 0 | 0 | 0 | **0 von 21** |
| über das Portfolio | 3 | 0 | 4 | — | **7 von 21** |

*(Portfolio: 3 durch `max_open_positions`, 4 durch den Cooldown, zusammen 7
ohne Doppelzählung.)*

**Je Konto kostet die Reparatur nichts.** Null von 21 Trades ändern sich, das
Mittel bleibt bei +0,1893 R. Der Grund ist Arithmetik und keine Nachsicht: ein
Konto riskiert rund 10 USDT je Trade, der Tagesdeckel liegt bei 5 % von 1 000
= 50 USDT, und ein einzelner Markt erreicht in 24 Stunden keine drei
aufeinanderfolgenden Verluste. `max_open_positions: 2` kann je Konto ohnehin
nicht binden, weil der Broker *einen* Platz hat.

Über das Portfolio gerechnet blockt dieselbe Konfiguration **ein Drittel der
Stichprobe** und hebt das Mittel auf +0,3728 R über 14 Trades.

**Damit ist der Einwand gegen die Reparatur weg** — für die Lesart, die zur
gebauten Architektur passt. Die Lesart selbst gehört aber entschieden und
nicht aus Bequemlichkeit gewählt: dass die billigere Variante auch die
wirkungslose ist, ist kein Argument für sie.

*Untergrenze, nicht die Veränderung.* Gezählt ist, was die Regeln an den
**genommenen** Trades tun. Eine blockierte Order gibt ihren Platz frei, und
ein echter Neulauf nähme danach andere Trades — dieselbe Einschränkung wie bei
jeder nachträglichen Filterrechnung hier.

---

## 7. Korrektur zum Termin, 11.10.2026 — die Rate ist höher als angenommen

Reproduktion: die Rechnung unten braucht nur die Trade-Zahl aus dem Journal
und die Trade-Zahlen aus Abschnitt 2.

Abschnitt 2 rechnet mit **1,9 Trades/Tag**. Diese Zahl stammt aus einer frühen
Messung über vier Märkte. Nachgezählt über alle 21 geschlossenen Live-Trades:

| Fenster | Trades | je Tag |
|---|---|---|
| gesamt (8,2 Tage) | 21 | **2,56** |
| letzte 4 Tage | 11 | 2,75 |
| letzte 2 Tage | 4 | 2,00 |

Mit der gemessenen Rate statt der angenommenen:

| nötig für | Trades | Tage | fertig am |
|---|---|---|---|
| 80 % Mächtigkeit, R-Metrik | 45 | 9 | **20.10.2026** |
| 80 %, Trefferquote | 50 | 11 | 22.10.2026 |
| 90 %, R-Metrik | 55 | 13 | 24.10.2026 |
| 90 %, Trefferquote | 62 | 16 | 27.10.2026 |
| **mit Replikationstor, 80 %** | 100 | 31 | **10.11.2026** |
| mit Replikationstor, 90 % | 128 | 42 | 21.11.2026 |

**Damit ist eine Aussage von gestern zu korrigieren.** Ich hatte geschrieben,
die Antwort falle „Ende November bis Mitte Dezember" und damit **nach** dem
Stichtag. Das galt für 1,9 Trades/Tag. Bei der gemessenen Rate gilt:

> Der Nachweis in **einem** Fenster ist bis zum 30.10. zu haben — bis dahin
> stehen rund 70 Trades gegen 45 bis 62 nötige. **Nur das Replikationstor**
> reicht darüber hinaus, auf den 10. bis 21.11.

Das ändert nichts am Befund, dass die bisherige Evidenz keinen Vorteil zeigt
(+0,17 R konsequent geschnitten). Es ändert, wann die Frage entschieden ist.

### Zwei Einschränkungen, die dazugehören

**Die Rate ist nicht stabil.** 2,00 über die letzten zwei Tage gegen 2,75 über
die letzten vier. Bei 2,00 landet der Einzelfenster-Nachweis am 23.10. und das
Replikationstor am 20.11. — die Schlussfolgerung hält über diese Spanne, die
genauen Daten nicht.

**Die Haltedauern sind nach unten verzerrt.** Unter den 21 *geschlossenen*
Trades steht der Median bei 4,1 h und das Maximum bei 54 h. Gleichzeitig sind
vier Positionen **offen**, zwei davon seit 94,6 h (LINK) und 66,6 h (BNB).
Die langen Trades sind noch nicht geschlossen und fehlen deshalb in jeder
Statistik über geschlossene Trades — ein Überlebenseffekt in der eigenen
Stichprobe. Dass H4-Setups unter den geschlossenen die *kürzeste* mittlere
Haltedauer zeigen (4,5 h gegen 9,8 h bei M15), ist genau dieser Effekt und
nicht eine Eigenschaft der Zeitebene: `strategies/guide.py` sagt ausdrücklich,
ein H4-Setup setze seinen Stop an H4-Struktur und **„the trade runs for days"**.

*Kein Fehler also, sondern Bauart* — aber eine, die die Belegung aller vier
Plätze über Tage erklärt und damit auch die 21 Stunden ohne einen einzigen
Abschluss am 10./11.10.

---

## 8. Warum die Gewinne kamen und wieder gingen — und eine Korrektur an mir selbst

Severin, 11.10.: *„Schau, was du wirklich bei den gewonnenen Trades richtig
gemacht hast und setze das auch jetzt wieder um."* Die Frage ist richtig
gestellt und hat eine gemessene Antwort.

### Die Reihenfolge ist kein Nachlassen, sondern drei Blöcke

Nach Abschluss sortiert: `L W L L L L  W W W W W W W W  L L L L L L L`

| Block | BTC über die Haltefenster | short | R je Trade |
|---|---|---|---|
| 1 (Trades 1–6) | +0,19 % | 3/6 | −0,637 |
| **2 (acht Gewinne)** | **−1,67 %** | 7/8 | **+1,881** |
| **3 (sieben Verluste)** | **+0,98 %** | 6/7 | **−1,037** |

Das System war in Block 2 **und** Block 3 zu rund 90 % short. In Block 2 fiel
der Markt, in Block 3 stieg er. **Die Entscheidungen haben sich nicht
verändert — der Markt hat sich verändert.**

### Gerechnet statt beschrieben

Marktbewegung je Trade, mit dem Vorzeichen der Seite versehen und durch die
Stop-Weite geteilt, gegen das Ergebnis:

| | |
|---|---|
| Korrelation | **+0,810** |
| erklärte Varianz | **66 %** |
| Hebel auf die Marktrichtung (`b`) | **+1,491** ± 0,247 |
| Rest daneben (`a`) | **−0,2007 R** |

Zwei Drittel des Ergebnisses sind Marktrichtung. Was daneben übrig bleibt, ist
**negativ**. Das bestätigt E8 (dort `b` = 1,788 auf 14 Trades) auf allen 21.

**Die Antwort auf die Frage lautet damit: an den Gewinnern wurde nichts
gemacht, das sich wiederholen liesse.** Sie waren Shorts in einer fallenden
Woche. Dieselben Shorts in einer steigenden Woche sind die Verluste.

### Und das Gefühl, die Verluste seien doppelt so gross, täuscht

| | |
|---|---|
| Gewinner | **+1,828 R** (+17,46 USDT) |
| Verlierer | **−1,040 R** (−13,16 USDT) |
| Verhältnis | ein Gewinner ist **1,76×** ein Verlierer |
| Summe | +157,14 gegen −157,89 → **netto −0,76 USDT** |

Nicht die Grösse schmerzt, sondern die **Reihenfolge**: sieben Verluste
hintereinander.

### KORREKTUR: die Bremse, die ich vorgeschlagen habe, hätte Geld gekostet

Abschnitt 6 nennt für die Portfolio-Lesart *„4 von 21 geblockt (3× max_open_
positions, 4× Cooldown)"* und ich habe daraus geschlossen, die Portfolio-Lesart
hätte die Verlustserie gebremst. **Das war falsch, und der Fehler ist mein
eigener aufgeschriebener:** ich habe die geblockten Trades *gezählt*, ohne
nachzusehen, **welche**.

Portfolio-Cooldown, 3 Verluste in Folge, 24 h Pause, gegen die echten Trades:

| geblockt | | |
|---|---|---|
| 04.10. 20:02 | DOGEUSDT | **+22,54 USDT** |
| 05.10. 13:00 | LINKUSDT | **+14,61 USDT** |
| 09.10. 13:00 | AVAXUSDT | −10,26 USDT |
| 10.10. 09:00 | DOTUSDT | −10,66 USDT |

| | |
|---|---|
| ohne Bremse | **−0,76 USDT** über 21 Trades |
| **mit Bremse** | **−16,97 USDT** über 17 Trades |

Die Bremse blockt definitionsgemäss, was *nach* einer Verlustserie kommt — und
hier war die Erholung nach der ersten Serie der grösste Gewinn des ganzen
Laufs. *„Eine Prozentzahl ohne ihre Auszahlung ist kein Ergebnis"* steht als
Lektion in diesem Projekt, und ich bin ihr trotzdem aufgesessen.

**Die Empfehlung aus Abschnitt 6 ist damit zurückgezogen.** Die Portfolio-
Lesart ist nicht belegt besser; sie ist an dieser Stichprobe belegt
schlechter. Mit n = 4 geblockten Trades belegt das natürlich auch nichts in
die andere Richtung — ausser, dass meine Begründung keine war.

### Was daraus folgt, und was ausdrücklich nicht

**Nicht folgt:** dass man das Muster der Gewinner nachbauen soll. Die Gewinner
auszuwählen und ihre Eigenschaften zur Regel zu machen, ist die Methode, mit
der dieses Projekt sich schon mehrfach selbst einen Vorteil vorgerechnet hat.

**Folgt:** das System ist ein 1,5-fach gehebelter Richtungswette ohne
gemessene Fähigkeit, die Richtung zu wählen — 35 Merkmale ordnen die nächsten
fünf bis zehn Stunden mit Korrelation 0,004. Eine Wette ohne Grundlage wird
durch keine Filterung besser. Was sie entscheidet, ist allein, ob die nächsten
Wochen fallen oder steigen.
