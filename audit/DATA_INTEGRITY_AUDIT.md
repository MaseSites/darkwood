# Phase 1 — Datenintegrität und Betriebsfehler

**Lauf:** 08.10.2026, 22:34–22:50 UTC · **Commit vor der Arbeit:** `6074abe`
**Prüfung bezieht sich auf:** P15–P20 und P40–P45 des `PROBLEMBERICHT_20X.md`

Jede Zeile unten trennt **gemessen**, **Annahme** und **offen**.

---

## 1. OHLCV: erwartete gegen tatsächliche Kerzen

Geprüft: 72 Reihen (12 Märkte × 6 Zeitebenen), rund 45 Millionen Kerzen.
Erwartet wurde `(letzter − erster) / Schrittweite + 1` je Reihe.

### Gemessen

| | |
|---|---|
| **Duplikate** über alle 72 Reihen | **0** |
| **Nicht-monotone Zeitstempel** | **0** |
| Fehlende Kerzen insgesamt | **1 830** |
| **Alle 12 M1-Reihen** | **0 fehlend** |

Die Lücken sitzen fast ausschliesslich in M15, und sie sind klein:

| Reihe | fehlen | Anteil | Lücken |
|---|---|---|---|
| SOL / ETH / XRP M15 | je 251 | 0,14 % | je 8 |
| ADA / ATOM / AVAX / BNB / DOGE / DOT / LINK / LTC M15 | je ~132 | 0,06 % | je 6 |
| BTC M15 | 14 | 0,01 % | 1 |
| BTC / ETH / SOL / XRP H1 | je 2 | 0,00 % | je 1 |

Das BTC-M15-Loch ist der Rest des Nachladens vom 08.10.: von acht Lücken
blieb eine mit 14 Kerzen, und die liegt **vor** dem nachgeladenen Fenster
(30.09.).

**Befund:** Die Behauptung „historische Datenlücken" aus P15–P20 trifft zu,
aber die Grössenordnung ist 0,004 % des Bestands, und die Zeitebene, auf der
alle Ausgänge aufgelöst werden (M1), ist lückenlos.

## 2. Das M1-Archiv ist alt — und was das wirklich kostet

### Gemessen

| Markt | M1 endet | M15 endet | Rückstand |
|---|---|---|---|
| BTC, ETH, SOL, XRP | 01.10. 13:57 UTC | 08.10. 22:15 UTC | **176,3 h** |
| ADA, AVAX, LINK | 03.10. 16:20–17:28 | 08.10. 22:15 | 124,8–125,9 h |
| ATOM, BNB, DOGE, DOT, LTC | 04.10. 08:54–11:47 | 08.10. 22:15 | 106,5–109,3 h |

### Und das ist Absicht, nicht ein Fehler

Im Code dokumentiert (`live/paper.py`): der Papierhändler **holt** M1 jeden
Zyklus (240 Minuten) und löst damit **im Speicher** die offene Position auf —
er archiviert es bewusst nicht, weil die M1-Tabelle 2,6 Millionen Zeilen je
Symbol hat und jeder Schreibvorgang eine ganze Jahrespartition neu validiert.
*„The collector and the sync keep that table; this one borrows from it."*

Die Zusage im Modul-Docstring, der Vorwärtshandel löse „minute by minute,
exactly as in the backtests" auf, ist damit **zutreffend**. Ich hatte sie
zuerst für falsch gehalten; die Prüfung hat das widerlegt.

### Die Konsequenz, gemessen statt vermutet

Ich hatte vermutet, das alte M1-Archiv verhungere das Replikationsfenster
neuer Studien. Gemessen:

> **7 von 7 340 genommenen Signalen (0,1 %)** liegen hinter dem Ende des
> M1-Archivs und sind deshalb nicht nachsimulierbar.

Die Vermutung ist widerlegt. Dass E10 im späteren Fenster nur 496 von 7 255
Paaren hatte, liegt an der Verteilung des Signalspeichers selbst, nicht am
M1-Rückstand.

**Offen:** Niemand aktualisiert das M1-Archiv automatisch. Solange nur 0,1 %
betroffen sind, ist das kein Blocker; sobald eine Studie das jüngste Fenster
braucht, ist es einer.

## 3. Journal: sechs Konsistenzprüfungen

Siehe `audit/BASELINE_REPRODUCTION.md` §2.2. Zusammengefasst: **0 Duplikate,
0 verdrehte Zeitstempel, 0 Arithmetikfehler** in 2 749 Trades. Gebühren und
Funding sind getrennt gespeichert und vorzeichenrichtig verbucht.

**Bisher unerwähnt und hiermit erwähnt:** 1 Liquidation und 2 manuelle
Schliessungen im Journal. Keine Audit-Datei nennt sie.

## 4. P44 behoben: ein Prozess je Rolle, vom Betriebssystem erzwungen

### Was gebaut wurde

`src/traidingbrain/storage/singleton.py` — eine Sperrdatei mit exklusiver
Betriebssystem-Sperre: `msvcrt.locking` unter Windows, `fcntl.flock` sonst.
Verdrahtet in `scripts/papertrade.py` (Rolle `papertrade`),
`scripts/collect_venue_tape.py` (`venue_tape`) und
`scripts/collect_binance_tape.py` (`binance_tape`).

Der entscheidende Grund für eine Betriebssystem-Sperre statt einer PID-Datei:
**das Betriebssystem gibt beim Prozessende von sich aus frei** — auch bei
Absturz oder Kill. Es gibt keine verwaiste Sperre, die ein späterer Start
erst als veraltet erkennen müsste, und genau diese Erkennung ist die Stelle,
an der selbstgebaute Locks falsch werden.

### Gemessen, Ende zu Ende

```
Prozess A hält die Sperre.
Prozess B: python scripts/papertrade.py --cycles 1
  -> "Start abgelehnt: papertrade laeuft bereits
      (pid=38736 seit=2026-10-08 22:47:21 UTC)."
  -> Rückgabewert 2
```

Der Rückgabewert wurde **ohne** `| tail` geprüft; eine Pipe verschluckt ihn,
und das steht als Falle in den Projektnotizen.

### Zwei Dinge, die der Test gefunden hat

**`msvcrt.locking` ist eine *mandatory* Sperre.** Solange sie gehalten wird,
verweigert Windows jedem anderen Handle sogar das **Lesen** des gesperrten
Bereichs — auch demselben Prozess. Eine Sperre bei Versatz 0 hätte damit genau
die Diagnose unlesbar gemacht, die sie erklären soll: `holder()` hätte
„unbekannt" gemeldet, während alles in Ordnung war. Gelöst durch eine Sperre
bei Versatz 4096, hinter dem Dateiende, mit kurzem Text davor. `fcntl.flock`
ist dagegen beratend und lässt Lesen zu.

**Mein erster Test war grün aus dem falschen Grund.** Er tötete `child.pid` —
und das venv-`python.exe` ist unter Windows ein Starter, der den eigentlichen
Interpreter als weiteren Prozess startet. Gemessen: `child.pid` 16040, Halter
der Sperre 9772. Der Kill traf den Starter, dessen stdin-Pipe sich schloss,
worauf der echte Halter auf EOF in sein `release()` lief und sich **ordentlich**
beendete. Der Test hätte die Freigabe durch das Betriebssystem nie geprüft.
Jetzt meldet das Kind seine eigene PID und die wird getötet. *Dieselbe Falle
hat in diesem Projekt schon einmal „vier Prozesse = zwei Händler" ergeben.*

### Tests

`tests/test_singleton.py`, **7 Tests, alle grün**: Erwerb mit PID-Vermerk,
zweiter Erwerb im selben Prozess, verschiedene Rollen kollidieren nicht,
Freigabe und Wiedererwerb, **echter zweiter Prozess**, **hart getöteter
Halter**, und: eine abgelehnte Übernahme darf die Diagnose des Halters nicht
leeren.

### Offen — eine Lücke im Übergang

Der **laufende** Papierhändler wurde vor dem Lock gestartet und hält ihn
nicht. Die Garantie gilt ab seinem nächsten Start. Gemessen: ein Zweitstart
lief einen Zyklus mit, bevor der Lock verdrahtet war.

## 5. Funding-Fehlmeldungen beim Start — geprüft, ohne Folge

Zwölf Zeilen „Funding nicht abrufbar" im Papierprotokoll, alle beim Start um
~16:16 UTC, als beide Tape-Collectoren dieselbe IP sättigten.

**Gemessen:** der Funding-Bestand steht für alle Märkte auf **08.10. 16:00
UTC**, der letzten Abrechnung (Binance siedelt 00:00/08:00/16:00 ab). Die
nächste war zum Prüfzeitpunkt noch nicht fällig. Bei Fehlschlag liest der
Händler den gespeicherten Bestand weiter, und `top_up_funding` läuft **alle 20
Zyklen** im Hauptlauf. **Es fehlt kein Funding.**

## 5b. Nachtrag 09.10.: ein Fehler-Ausbruch, den niemand gemeldet hat

**Gemessen.** Zwischen rund 08:20 und 10:43 UTC lief der Papierhandel mit
einer Fehlerquote von etwa **47 %**. Alle zwölf Märkte scheiterten wiederholt
an `fetch_ohlcv(..., W1)` — dem **ersten** Abruf jedes Zyklus — mit einem
ccxt-Timeout (die Meldung endet nach der URL, ohne Grund; so sieht bei ccxt
ein Timeout aus). Die Zähler standen danach bei **5 043 Fehlschlägen auf
46 096 Zyklen**, gegen 1 977 auf 39 636 zwei Stunden davor.

**Der exakte Aufruf funktioniert von hier**, mit und ohne `startTime`, auf
`1w`, `1d` und `1h`. Es war kein deterministischer Fehler.

**Und er war vorbei, bevor ich ihn fand.** Über ein Fenster von 100 Sekunden
gemessen: 25 Zyklen, **0 Fehlschläge**. Die Quote jetzt ist null.

**Verloren ging nichts.** Ein Fehlschlag wird gefangen statt geworfen, und der
Broker holt bis zu `REFRESH_MINUTES = 240` Minuten nach — Ausstiege werden
also später aufgelöst, nicht übersehen. Die Minute, die der Papierhandel
zuletzt verarbeitet hat, war durchgehend aktuell.

**Was fehlte, war die Meldung.** Gefunden wurde der Ausbruch, weil jemand die
Datenbank abgefragt hat. Das ist derselbe Fall, der dieses Projekt schon
zwölf Stunden Tape-Aufnahme gekostet hat: ein Zustand, den man nur durch
Nachsehen findet.

**Behoben:** `FailureWatch` in `scripts/papertrade.py` meldet eine
Fehlerquote über 20 % im gleitenden 20-Zyklen-Fenster — einmal beim Eintritt,
einmal bei der Entwarnung, nie dazwischen. Ein einzelner Fehlschlag alarmiert
nicht; gemeldet gehört ein **Zustand**. Die Meldung sagt auch, was er
bedeutet, sonst steht da eine Zahl und niemand weiss, ob gerade Trades
verloren gehen.

`tests/test_failure_watch.py`, **6 Tests**, erzwungen geprüft statt erst nach
zwei Stunden Laufzeit: Schweigen im Normalbetrieb, Alarm genau einmal,
Entwarnung genau einmal, Schweigen vor vollem Fenster, die Schwelle knapp
darunter und darüber, und der echte Vorfall nachgespielt.

> Dabei ist mein eigener Test zuerst fehlgeschlagen, weil er `int(20 × 0,47)`
> rechnete und 45 % erzeugte, während er 47 % erwartete. Die erwartete Zahl
> wird jetzt aus dem gerechnet, was der Test tatsächlich erzeugt — eine fest
> hingeschriebene 47 hätte den Code beschuldigt statt den Test.

**Offen:** warum W1. Dass es der erste Abruf jedes Zyklus ist, ist eine
Beobachtung und keine Erklärung.

> **Gemessen am 09.10., 13:14–15:44 UTC — es ist nicht W1.** 1 415 Abrufe,
> fünf Zeitebenen, Reihenfolge je Durchgang gedreht. Die Streuung über
> **Zeitebenen** ist **3 ms**, die über **Positionen 37 ms**: eine Wochenkerze
> kostet nichts Eigenes, der *erste* Abruf eines Zyklus kostet 36 ms mehr.
> W1 trug den Hut der Position 1.
>
> **Der Ausbruch ist damit trotzdem nicht erklärt.** ccxt bricht bei 10 000 ms
> ab; der schlechteste Einzelwert aus 1 415 Abrufen war 840 ms, und der
> Kaltstart verschiebt die Verteilung, ohne einen Rand hinzuzufügen — ein
> Timeout ist aber ein Randereignis. Dazu wiederholt sich der Ausbruch nicht:
> 0 Fehler in dieser Messung, und **4 010 Zyklen des Papierhandels durch ccxt
> seit dem Ausbruch mit 0 neuen Fehlschlägen** (der Zähler steht unverändert
> auf 5 043). Richtig gestellt lautet die Frage jetzt: warum scheitert der
> erste Abruf, in Ausbrüchen, die sich in Ruhe nicht andeuten. Vollständig in
> `audit/WARUM_W1.md`.

## 5c. Phase 1 Punkt 5: veraltete Daten sperren jetzt ein Signal

Der Auftrag verlangt: *„Erkenne veraltete Daten und sperre daraus abgeleitete
Signale."* Beim Nachsehen, ob das fehlt, zeigte sich erst, **dass der
naheliegende Pfad schon sicher ist** — und dann, dass ein anderer es nicht war.

**Sicher, und zwar aus einem konkreten Grund.** Bei einem Abruffehler wird
`self._newest` nie gesetzt: die Zuweisung in `settle()` passiert erst nach
einem vollständig gelungenen `refresh_data()`. Der Zeiger bleibt stehen, und
`decide()` tut nichts. Gemessen während des 47-%-Ausbruchs: keine verlorene
Entscheidung, Konto durchgehend aktuell. *Ich hatte vermutet, die Sicherheit
hänge an der Reihenfolge von `context` — W1 zuerst, also bricht ein
W1-Fehlschlag alles ab. Das war falsch: die Zuweisung-nach-Erfolg trägt es
unabhängig von der Reihenfolge.*

**Nicht sicher war der andere Fall:** eine Abfrage, die **gelingt** und einen
**alten** Balken zurückgibt. `decide()` verglich `newest == last_decided_ts` —
ein Rückschritt ist *ungleich* und wäre durchgegangen. Er hätte zwei Dinge
getan:

1. einen längst entschiedenen Balken erneut entschieden,
2. den Zeiger **rückwärts** gesetzt (`last_decided_ts = newest`), womit jeder
   Balken dazwischen zum zweiten Mal entschieden worden wäre.

Dass eine gelungene Antwort alt sein kann, ist an demselben Tag belegt: auf
`stream.binancefuture.com` waren die Preise auf den Cent richtig und der
Kennraum um Faktor 11 falsch (siehe `E5_ORDERFLOW.md` §3). Eine Antwort kann
richtig aussehen und falsch sein.

**Behoben:** der Vergleich ist jetzt `>` statt `!=`, in `decide()` **und** in
`wants_decision` — hätte nur eines gewechselt, hätte ein Läufer die teure
Analyse für einen Balken angestossen, den `decide()` danach verwirft. Ein
Rückschritt wird verworfen, gezählt (`tally.stale_bars`) und vermerkt, mit
beiden Zeitstempeln in der Meldung. Still verwerfen wäre derselbe Fehler wie
still entscheiden.

`tests/test_stale_bar.py`, **10 Tests**: neuerer Balken wird entschieden,
derselbe nicht zweimal, älterer entscheidet nichts, älterer bewegt den Zeiger
nicht zurück, älterer wird gezählt und laut gemeldet, kein Balken bleibt
stumm, und `wants_decision` stimmt mit `decide()` in allen vier Fällen überein.

**Zum Stand der Veralterung, gemessen:** alle zwölf Märkte über alle fünf
Zeitebenen liegen bei **1,36 bis 1,71 Balken-Intervallen** — der neueste
Balken ist der gerade geschlossene. Nichts ist derzeit veraltet. Die Wache ist
also ein **Netz**, kein Fix für einen laufenden Schaden, und so gehört sie
berichtet. Der Schwellwert muss dabei je Zeitebene gelten: zwei Wochen sind
für W1 normal und für M15 ein Ausfall.

## 6. Was in Phase 1 **nicht** erledigt ist

| Auftragspunkt | Stand |
|---|---|
| Rohereignisse mit Event- und Empfangszeit | **offen** — die Tape-Collectoren speichern `received_ms`, aber es gibt keinen WebSocket-Collector mit Sequenzkontrolle |
| Reconnect, Heartbeat, Backoff mit Jitter | **offen** — Polling mit Wiederholung, kein Streaming |
| Stale-Data-Erkennung sperrt abgeleitete Signale | **erledigt** — siehe §5c. Ein Signalbalken vor dem zuletzt entschiedenen wird verworfen, gezählt und gemeldet; der Zeiger geht nicht rückwärts |
| Zentrales Rate-Limit-Handling | **offen** — jeder Prozess begrenzt sich selbst; der Lock verhindert jetzt den schlimmsten Fall |
| Fehlerfall-Tests (DNS, Sequenzlücke, doppelte Nachricht, …) | **teilweise** — nur die Lock-Fälle sind getestet |
| Absichtlich eingeführter Fehler ⇒ klarer ungültiger Status | **nicht erfüllt** — das Abnahmekriterium von Phase 1 ist damit **nicht** erreicht |

**Ehrliche Einordnung:** Von Phase 1 sind der Datenintegritäts-Report und P44
erledigt. Die Streaming-Anforderungen (Punkte 3–5 und 10 des Auftrags) gehören
zum Collector aus Phase 3 und sind ohne ihn nicht erfüllbar. Das Phase-1-
Abnahmekriterium ist deshalb **offen**, und nicht als bestanden darzustellen.
