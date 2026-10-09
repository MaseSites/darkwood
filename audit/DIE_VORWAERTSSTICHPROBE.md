# Die Vorwärtsstichprobe sind 14 Trades, nicht 18 — und das Journal konnte es nicht sagen

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
