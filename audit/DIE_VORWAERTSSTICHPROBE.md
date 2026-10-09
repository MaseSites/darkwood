# Die Vorwärtsstichprobe sind 14 Trades, nicht 18 — und das Journal konnte es nicht sagen

> **DRITTE PRUEFUNG, 09.10.2026, 16:40 UTC — die 11 stimmen, die Begruendung
> in Abschnitt 7 nicht.** Die beiden dort genannten Commits sind im
> Live-Entscheidungspfad **wirkungslos** (eine inaktive Strategie je Commit,
> plus ein Beschriftungsfeld). Die echte Grenze liegt bei **04.10. 21:52 UTC**
> und heisst *"Stop losing forward evidence while it is being recorded"* --
> `MAX_DECISION_ATTEMPTS = 3`, womit ein Balken nach einem Fehlversuch nicht
> mehr verloren geht. Dieselben **11 Trades**, dieselbe Zahl, richtiger Grund.
> Ich hatte die Commits nach ihren **Titeln** ausgewaehlt; die beiden
> strategisch klingenden waren inert, der entscheidende klingt nach
> Buchhaltung. Siehe Abschnitt 8 und `scripts/live_path_changes.py`.
>
> **ZWEITE KORREKTUR, 09.10.2026, 15:15 UTC — es sind 11, nicht 14.** Dieser
> Bericht schnitt bei der letzten *Konfigurations*-Änderung. Danach kamen noch
> zwei **Code**-Änderungen, die verändern, welche Trades entstehen: am 04.10.
> 20:43 UTC *„Prefer a target that gets hit over one that pays more"* und am
> 05.10. 12:38 UTC eine zweite Strategiefamilie. **Keine von beiden bewegt
> `run_signature`** — die Signatur deckt Konfiguration, nicht Code. Die
> homogene Stichprobe sind **11 Trades**, Mittel **+0,7867 R**, Intervall
> [−1,043; +1,976]. Termin: 30 fehlende Trades, 16 Tage, **24.10.2026**.
>
> **Und der Mittelwert steigt mit jedem Schnitt** — 18 → +0,3938, 14 →
> +0,6208, 11 → +0,7867. Das ist ein Warnzeichen und gehört benannt: wer den
> Schnitt nach hinten schiebt, wählt die jüngeren Trades, und die waren
> besser. Die Schnitte stammen aus Commit-Zeitstempeln, nicht aus Ergebnissen
> — aber die Richtung der Drift ist eine Gefahr, nicht ein Ergebnis. Bei 11
> Trades und einem Intervall von drei R Breite ist nichts belegt.
>
> Siehe Abschnitt 7 für die Konsequenz an den Daten.

Stand 09.10.2026, 14:15 UTC. Commit vor der Arbeit: `610f021`.

---

## 1. Warum die Frage gestellt werden musste

`audit/WANN_WEISS_MAN_ES.md` leitet einen Termin aus einer
Mächtigkeitsrechnung ab: bräuchte das System die +0,7280 R, die das Ziel
verlangt, wären das nach **41 Vorwärtstrades** sichtbar. Diese Rechnung hängt
an einer Voraussetzung, die ich beim Schreiben nicht geprüft hatte:

> **Sind die Vorwärtstrades überhaupt *eine* Stichprobe?**

Wenn Strategie, Kadenz oder Schwellen sich während des Laufs geändert haben,
beantworten die Trades davor und danach nicht dieselbe Frage — und 18 Trades
sind dann keine 18 Beobachtungen zu *einer* Hypothese.

## 2. Das Journal konnte es nicht beantworten

**`run_signature` stand nicht im Journaleintrag.** Der Begriff existiert
(`journal/version.py`), und der *Signalspeicher* trägt ihn je Zeile — der
Journaleintrag nicht. Abgefragt: alle 18 Live-Trades melden
`(keine im Payload)`.

Beantworten liess sich die Frage daher nur über die **Git-Historie der
Konfiguration**. Dort standen innerhalb von zwei Tagen **vier
strategiewirksame Änderungen**:

| UTC | Commit | was |
|---|---|---|
| 03.10. 15:03 | `cd75e7e` | Papierkonto auf den Betrag gesetzt, den Severin haben wird |
| 03.10. 15:50 | `b1fd19d` | acht Märkte hinzugefügt |
| 03.10. 15:59 | `79a224f` | alle zwölf Märkte handeln |
| **04.10. 10:07** | `600685b` | **alle fünfzehn Minuten entscheiden** (Kadenz H1 → M15) |
| **04.10. 12:30** | `8a29c02` | **Setup C abgeschaltet** |

Die beiden letzten verändern, *welche Signale überhaupt entstehen*. Damit
beginnt die homogene Stichprobe erst danach.

## 3. Die Zahlen, je Schnitt

| Schnitt | n | Mittel | Streuung | korrigiertes Intervall |
|---|---|---|---|---|
| alle | 18 | +0,3938 R | 1,492 | [−0,918; +1,875] |
| nach 8 Märkten (03.10. 15:50) | 17 | +0,4819 | 1,489 | [−0,894; +1,914] |
| nach 12 Märkten (03.10. 15:59) | 17 | +0,4819 | 1,489 | [−0,894; +1,914] |
| nach M15-Kadenz (04.10. 10:07) | **14** | **+0,6208** | 1,524 | **[−1,070; +1,960]** |
| nach Setup C aus (04.10. 12:30) | **14** | **+0,6208** | 1,524 | [−1,070; +1,960] |

**Die homogene Stichprobe ist 14 Trades**, Mittel **+0,6208 R**, Intervall
über die Null.

Das berichtete +0,3938 R über alle 18 ist damit eine Mischung aus vier
Konfigurationen. In **R** sind die drei Risiko-Einstellungen (49,8 / 5,0 /
10,0 USDT) unschädlich, weil `r_multiple` skalenfrei ist — die *Strategie*-
Änderungen sind es nicht.

## 4. Was das mit dem Termin macht

| | |
|---|---|
| nötig für +0,7280 R | **41** Trades |
| homogen vorhanden | **14** |
| fehlen | **27** |
| bei 1,9 Trades/Tag | 14 Tage |
| **Antwort am** | **23.10.2026** |

**Der Termin wird früher, nicht später** — die 41 zählen ab dem Beginn der
homogenen Stichprobe, und davon sind 14 schon da. Die Antwort fällt also
**vor** dem Stichtag des Ziels, nicht danach.

Und die Bedingung dafür bleibt dieselbe und wird jetzt wichtiger: **nichts an
der Strategie ändern.** Jede weitere Änderung setzt den Zähler bei 0 und
verschiebt die Antwort um 22 Tage.

## 5. Behoben: der Eintrag trägt jetzt seine Signatur

`JournalEntry.run_signature`, geschrieben von `paper.py`, mit Default `""`
für alles, was vor heute entstanden ist. Geprüft an einem echten Händler:
`"1000.0|['A', 'B', 'E', 'F', 'G']|0.08|M15|refused-v1"`.

Zwei Tests in `tests/test_journal.py`: das Feld steht im Objekt **und** im
gespeicherten Schema (`asdict`), und ein alter Eintrag ohne Signatur lädt
weiter.

**Eine Eigenschaft, die man nur durch Git-Archäologie findet, ist keine
aufgezeichnete Eigenschaft.** Genau dafür existiert der Signaturbegriff, und
er fehlte an der einen Stelle, an der die Frage aufkam.

## 6. Grenzen

**Die Signatur deckt nicht alles.** Sie trägt Startkapital, Setup-Liste,
Kostendeckel, Signalzeitebene und Ablehnungsversion. Eine Änderung, die keinen
dieser Bestandteile berührt — etwa eine andere ATR-Länge — würde sie **nicht**
verändern, und zwei Trades mit gleicher Signatur wären trotzdem aus
verschiedenen Konfigurationen. Was die Signatur deckt, steht in
`journal/version.py`; was sie nicht deckt, bleibt Git-Arbeit.

**Die 14 sind nachträglich bestimmt.** Die Schnitte kommen aus
Commit-Zeitstempeln, nicht aus den Daten. Dass ich sie *nach* dem Schreiben
der Mächtigkeitsrechnung gezogen habe, heisst: die Rechnung stand zuerst auf
18 und ist auf 14 korrigiert, nicht umgekehrt. Ab jetzt beantwortet das Feld
die Frage ohne mich.

**Vier gleichzeitig offene Positionen auf korrelierten Perps sind keine vier
unabhängigen Beobachtungen.** Die effektive Stichprobe ist kleiner als 14, und
die 27 fehlenden sind damit eine Untergrenze.


## 7. Zweite Konsequenz: die Signatur allein genügt nicht

**Der Signalspeicher konnte die Frage bereits exakt beantworten.** Er trägt
seit längerem `code_version` je Zeile, und für die Live-Signale sieht das so
aus:

| `code_version` | Signale | Zeitraum |
|---|---|---|
| `870d12c` | 27 | 08.10. 11:00 – 09.10. 13:00 |
| `8f26cdb-dirty` | 1 | 09.10. 13:45 |
| `dee4d98` | 1 | 09.10. 14:45 |

Er unterscheidet damit sogar die drei Neustarts von heute. Der
**Journaleintrag** trug das nicht — und genau dort kam die Frage auf.

**Behoben, mit dem vorhandenen Helfer statt einem neuen.** `JournalEntry`
trägt jetzt `code_version`, erzeugt von `journal/version.py:code_version()` —
derselbe Aufruf, den der Signalspeicher benutzt. *Ich hatte zuerst eine eigene
Fassung geschrieben und dabei nicht nachgesehen; `ruff` meldete die
Doppeldefinition, und meine Fassung ist geflogen.*

**Beide Felder sind absichtlich da, weil keines allein reicht:**

| | deckt | verpasst |
|---|---|---|
| `run_signature` | Startkapital, Setup-Liste, Kostendeckel, Signalzeitebene, Ablehnungsversion | **Verhalten, das im Code wohnt** |
| `code_version` | den Code exakt | nichts — aber **ändert sich auch, wenn nur ein Bericht geschrieben wird** |

Die Signatur ist zu **grob**, der Commit zu **fein**. Zusammen lassen sie die
Frage entscheiden: gleiche Signatur heisst gleiche Konfiguration, und für die
Commits dazwischen lässt sich prüfen, ob einer von ihnen Verhalten berührt
hat. Einzeln entscheidet keines.

---

## 8. Dritte Prüfung: die Zahl stimmt, die Begründung war falsch

Reproduktion:

```bash
python scripts/live_path_changes.py --since "2026-10-04 23:52"
```

**Es sind 11 Trades. Aber nicht aus den Gründen, die in Abschnitt 7 stehen.**

Abschnitt 7 schnitt bei zwei Commits, die ich **nach ihren Titeln** ausgewählt
hatte. Nachgesehen, was sie am Code tun:

| Commit | Titel | was er wirklich tut |
|---|---|---|
| `c6e28cf` 04.10. 20:43 | *„Prefer a target that gets hit over one that pays more"* | ein Feld `setup: str = ""` zur Beschriftung, plus `strategies/modest_target.py` — eine Strategie, die der Live-Pfad **nicht importiert** |
| `dd7c0c1` 05.10. 12:38 | *„Open a second strategy family"* | eine neue Datei `strategies/vol_breakout.py`, erreichbar nur über `scripts/challenge.py`. `config/settings.yaml` unberührt, die aktive Liste bleibt `['A','B','E','F','G']` |

**Beide sind im Live-Entscheidungspfad wirkungslos.** Belegt, nicht vermutet:
`live/` und `scripts/papertrade.py` importieren weder `modest_target` noch
`vol_breakout` noch `brain_judge`; alle Live-Trades laufen unter der Strategie
`guide-all`; und `live/paper.py` verzweigt an keiner Stelle auf das neue
`setup`-Feld.

### Die echte Grenze trägt einen Buchhaltungstitel

Der Import-Abschluss von `live/paper.py` umfasst **56 Dateien**. Seit dem
Konfigurationsschnitt berühren ihn **19 Commits** — nicht zwei. Von hinten
durchgelesen, bis der erste auftaucht, der verändert, *welche Trades
entstehen*:

| UTC | Commit | Urteil |
|---|---|---|
| 09.10. 14:24 / 14:37 / 15:26 | Signatur, `code_version`, Typ-Annotation | Buchhaltung |
| 09.10. 13:28 | Veraltungs-Wache | Verhalten, aber **nie ausgelöst** (`stale_bars` 0) |
| 08.10. 07:27 | `plan_entry(...)` → `assess(...).entry` | **identisch** — `plan_entry` *ist* `assess(...).entry`, seit 05.10. 06:16, und dieser Commit fasst `plan.py` nicht an |
| 07.10. 16:41 | Betrag und Hebel je Trade ausgeben | Buchhaltung (`print`) |
| 07.10. 14:55 | `binance_spot` als Venue ergänzt | berührt `binance` nicht |
| 07.10. 09:38 | `exit_price` in den Datensatz | Buchhaltung |
| 06.10. 15:45 | `last_failure`, `last_failure_ts` | Buchhaltung |
| 05.10. 11:10 | *„Give the broker the time exit"* | **Schalter ist aus** — `max_hold_hours` steht nicht in `settings.yaml`, Default `None` |
| 05.10. 09:42 | *„Cache the close times"* | Memoisierung, gleiches `searchsorted`-Ergebnis |
| 05.10. 08:11 | *„Cap risk by decision"* | der 1-%-Deckel hielt davor und danach jeden Trade; geändert wurde **warum**, nicht **ob** |
| **04.10. 21:52** | **„Stop losing forward evidence while it is being recorded"** | **die Grenze**: `MAX_DECISION_ATTEMPTS = 3`. Vorher ging ein Balken nach einem Fehlversuch verloren, jetzt bekommt er zwei weitere Versuche. Das verändert, **welche Balken überhaupt entschieden werden** |

**Schnitt also bei 04.10. 21:52 UTC.** Und weil die drei Trades, die der
14er-Stichprobe mehr hat, um 15:00, 15:00 und 20:02 UTC eröffneten — alle
davor —, fallen genau dieselben **11 Trades** heraus. Mittel **+0,7867 R**,
Intervall [−1,043; +1,976]. Termin unverändert **24.10.2026**.

### Warum das trotzdem berichtet gehört

Die Zahl ist zufällig richtig geblieben. Die Methode war es nicht:

> **Ich habe Commits danach ausgewählt, wie strategiewirksam ihr Titel
> klingt.** Die zwei strategisch klingenden waren inert. Der entscheidende
> heisst *„Stop losing forward evidence while it is being recorded"* und
> klingt wie Buchhaltung.

Ein Commit-Titel ist Prosa. Er beschreibt die Absicht des Autors, nicht die
Wirkung des Diffs — und ich war der Autor und habe mich selbst falsch gelesen.
Behoben mit dem Werkzeug, das gefehlt hat: `scripts/live_path_changes.py`
bildet den Import-Abschluss des Live-Einstiegs und listet die Commits auf
genau diese Dateien. **Es liefert die Kandidatenliste, nicht das Urteil** — ob
ein Diff wirkt, entscheidet nur das Lesen, und drei der obigen Zeilen hängen
an je einem Detail (ein Wrapper, ein nicht gesetzter Schalter, ein Deckel, der
schon vorher band).

*Und einmal kam dieser Lauf lautlos leer zurück.* Die Pfadliste lag in einer
Datei, die Python mit `\r\n` geschrieben hatte; jedes Muster endete auf `\r`
und passte auf nichts. `git log` meldete **keine Commits** — was aussieht wie
„keine Änderungen". Das Skript übergibt die Pfade jetzt als Argumente und hat
den Fall im Docstring stehen.

### Was fehlt, und es ist kein Werkzeug, sondern ein Test

Die Archäologie oben war nötig, weil der Live-Entscheidungspfad **keinen
Golden-Test** hat. Der Replay-Pfad hat einen: `tests/golden/` friert über
`fingerprint(...)` die Fills und die Kapitalkurve eines Backtests ein, und
eine Verhaltensänderung bricht ihn. Der Papierhandel hat nichts
Entsprechendes — und **er ist der Pfad, der die einzige noch wachsende
Evidenz erzeugt.** `MAX_DECISION_ATTEMPTS = 3` hätte einen solchen Test
gebrochen und wäre am Tag seines Entstehens als Schnitt sichtbar gewesen,
statt vier Tage später aus Diffs rekonstruiert.

**Der nächste Schritt an dieser Stelle:** ein Golden-Test, der die echte
Strategie (`GuidePool`, nicht `FixedIntent`) auf einem eingefrorenen Band
durch N Zyklen fährt und die **Signalfolge** hasht — jeden Vorschlag und jede
Ablehnung, aus dem `SignalStore`. Die Vorrichtung dafür steht schon in
`tests/test_papertrade.py`: `TapeSource` mit wanderndem Schnitt, `FixedClock`,
`synthetic_rows`.

**Und die Falle, die dabei ausdrücklich zu vermeiden ist.** Die bestehenden
Tests nehmen `FixedIntent` statt der echten Strategie, und zwar mit Begründung
im Modul: *„a real setup fires on a handful of bars in a fixture and on none in
some."* Feuert die echte Strategie auf der Fixture **nie**, ist der Hash über
eine leere Folge stabil, egal was sich ändert — ein Test, der immer dasselbe
sagt. Der Test muss deshalb seine eigene Signalzahl als Untergrenze mit
behaupten, sonst besteht er leer. Begonnen und bewusst nicht halb
hinterlassen: die Fixture muss erst nachweislich Signale erzeugen.

## 9. Was dabei nebenbei gemessen wurde

Drei Dinge, die ohne diese Prüfung offen geblieben wären.

**Die Streuung der Trades über Episoden ist klein.** Die Mächtigkeitsrechnung
unterstellt unabhängige Trades; vier gleichzeitig offene Perps sind das nicht.
Gemessen über **508 Episoden** im Replay (transitiv überlappende
Haltefenster): Intraklassen-Korrelation **ρ = 0,0249**, auf Episoden der
Grösse 3–5 sogar 0,0038. Bei der vorwärts beobachteten Episodengrösse von
2,20 ist der Designeffekt **1,03** — aus 41 Trades werden **42**, nicht 72.
*Mein erster Versuch schätzte die Episodenstreuung aus den fünf
Vorwärtsepisoden und kam auf 72; fünf Ziehungen schätzen eine Streuung
nicht.*

**Die beiden Vorwärts-Cluster sind nicht auffällig.** Vier Gewinner am 08.10.,
dann vier Verlierer — das sieht nach Regime aus. Im Replay haben von 23
Episoden mit genau vier Trades **5 (21,7 %)** alle vier mit gleichem
Vorzeichen; unabhängige Trades bei der beobachteten Trefferquote von 32,5 %
ergäben **21,9 %**. Die Übereinstimmung ist so eng, dass hier nichts zu
erklären ist.

**Und die Vorhersage, die das System an sich selbst macht.** Die 11 Trades
haben eine geplante Chance-Risiko-Relation von 1,5 (fünf) und 2,0 (sechs).
Dieselbe Mischung im Replay:

| geplantes R:R | n | Mittel | Treffer |
|---|---|---|---|
| 1,5 | 1 107 | −0,0417 R | 41,1 % |
| 2,0 | 595 | −0,1242 R | 30,6 % |
| **gewichtet wie vorwärts (5:6)** | | **−0,0867 R** | **35,4 %** |

**Das ist die vorab festgelegte Erwartung für die nächsten 30 Trades:
−0,0867 R und 35,4 % Treffer.** Beobachtet sind +0,7867 R und 63,6 % — aber
der Abstand beträgt **2,06 Standardfehler**, über der unkorrigierten Schwelle
von 1,96 und weit unter der korrigierten von 3,317. Und 7 von 11 Treffern
haben unter der Vorhersage von 35,4 % eine Wahrscheinlichkeit von 11 %. Nichts
daran ist belegt.

*Ich hatte zuerst den falschen Vergleich gezogen:* den Eimer „≤ 1,75" aus dem
Commit `c6e28cf` mit −0,0261 R. Den trifft das System aber nicht — sechs der
elf Trades liegen bei R:R 2,0, also im Eimer, den jene Regel vermeiden
*sollte*. Die Regel ist als eigene Strategie gebaut (`CAP = 1.75`) und live
**nicht aktiv**; die Signatur sagt `refused-v1`, nicht `modest-1.75`. Eine
Grundlinie gegen etwas, das das System nicht tut, ist keine Grundlinie.
