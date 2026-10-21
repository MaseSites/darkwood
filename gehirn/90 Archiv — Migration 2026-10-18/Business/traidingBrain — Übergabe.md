---
typ: uebergabe
projekt: traidingBrain
status: aktiv
aktualisiert: 2026-10-02
naechster_schritt: Vorwärts-Papertrading läuft — in ein paar Tagen die ersten Live-Trades gegen die Replay-Zahlen halten
verwandt:
  - "[[traidingBrain]]"
  - "[[traidingBrain — Analyse-Plattform (Plan)]]"
  - "[[traidingBrain — Regel-Aufnahme]]"
  - "[[traidingBrain — Deine To-Do-Liste]]"
---

# traidingBrain — Übergabe, Stand 02.10.2026

Diese Notiz ist so geschrieben, dass „continue" genau hier weitergeht.

## Zustand

- **75 Commits**, alles committed, nichts im Working Tree
- **~900 Tests grün**, 22 übersprungen (Postgres, siehe unten), `ruff` und
  `mypy --strict` sauber
- **Stufe 3 ist fertig** (`da6475d`): die 42 Indikatoren rechnen und speisen
  den Score, das Score-Panel steht auf dem Dashboard
- **Struktur und Liquidität sind verdrahtet** (`7573d96`): sieben von zehn
  Familien liefern jetzt Befunde, rund 195 Messwerte pro Kerze
- **Gesamtbewertung 1–100** (`9f68bd1`): auf Severins Wunsch, immer sichtbar
  oben neben dem Preis

## Die Datenbank liegt auf dem Pi — und der war aus

`.env` zeigt auf `192.168.0.62:5432`, also den Raspberry Pi. Der lokale
Postgres-Dienst auf dem Laptop läuft zwar, wird aber nicht mehr benutzt.

Am 01.10. war der Pi nicht erreichbar (kein Ping, kein Port). Folge: jeder
Postgres-Test wartete über zwei Minuten auf eine Verbindung, die nie kam, und
ein voller Lauf stand 40 Minuten, bevor er sechs Fehler meldete, die nichts
über den Code aussagten. **Behoben:** `tests/conftest.py` fragt einmal pro Lauf
nach, ob überhaupt eine Datenbank antwortet, und überspringt sonst in einer
Sekunde. Wenn 22 Tests übersprungen werden, ist der Pi aus — das ist die
Meldung, nicht ein Fehler.

## Hochfahren, in dieser Reihenfolge

```bash
cd C:\Users\sever\OneDrive\Desktop\traidingBrain
.venv\Scripts\python.exe scripts\health.py          # sieht der Collector frische Daten?
.venv\Scripts\python.exe -u scripts\run_dashboard.py --port 8800
```

Dann `http://127.0.0.1:8800`. Der erste Marktaufruf pro Symbol braucht ~25 s
(fünf Zeitebenen), danach sofort. Der Live-Loop ist optional:
`run_live.py --brain subscription`.

**Achtung Browser-Cache.** Nach Änderungen an `app.js` oder der Vorlage cached
Chrome die alte Seite. `?v=8` anhängen oder hart neu laden. Das hat mich heute
einmal zehn Minuten gekostet.

## Was fertig ist

**Severins Regelwerk** aus `DAYTRADING_MASTER_GUIDE.md` (13 Videos):
Kerzenmuster (V03/V08), Supply/Demand + Order Blocks + Inducement (V09/V11/V12),
FVG-Qualität mit V05-Filtern und V13-Faktoren getrennt, Setups A/C/F/G lauffähig.
B fehlt (braucht Trendlinien), D und E können nicht handeln — ihre eigenen
Regelkarten sagen „Stop nicht spezifiziert" bzw. „Take Profit nicht spezifiziert".

**Score** (`src/traidingbrain/score/`, `analysis/bank.py`, `analysis/formulas.py`):
Befunde nach Informationsfamilie, Median statt Mittelwert, `depends_on` gegen
Doppelzählung, dafür und dagegen niemals verrechnet. Die 42 Indikatoren rechnen
jetzt wirklich und laufen über alle fünf Zeitebenen — 180 Messwerte pro Kerze,
die zu höchstens so vielen Urteilen werden, wie es Familien gibt.

Drei Dinge, die beim Verdrahten auffielen und repariert wurden:

- **Drei Indikatorenpaare rechneten dieselbe Zahl.** Williams %R plus 100 *ist*
  der rohe Stochastik; die A/D-Linie über ein Fenster summiert *ist* Chaikin
  Money Flow; eine Kanalposition ist eine Kanalposition, in welcher Familie auch
  immer. Zwei davon über Familiengrenzen hinweg, wo der Median sie nicht fängt.
  Ein Test verbietet jetzt zwei Indikatoren mit identischer Reihe.
- **Sechs Messwerte haben eine Grösse, aber keine Seite** (ADX, ATR, Bandbreite,
  Vola, Seitwärtsneigung, rel. Volumen) — ihre eigenen Fehlermodi sagen das
  wörtlich. Sie sind als `directional=False` markiert und zählen nicht als
  Beleg, weil vier richtungslose Messwerte neben drei gerichteten den
  Familienmedian auf null ziehen. Sie bleiben als Kontext sichtbar.
- **Zeitebenen wurden gleich gewichtet.** Jetzt zweistufig: innerhalb einer
  Ebene Median, über die Ebenen gewichteter Median (Woche/Tag 1,00; H4/H1 0,90;
  M15 0,40). Widersprechen sich die Ebenen, schweigt die Familie, statt die
  lautere Ebene als volle Stärke zu melden.

**Struktur und Liquidität** (`score/observations.py`): Die Arbeit steckte fast
ganz darin, zu entscheiden, was *nicht* gemeldet wird. Zwei Sätze aus den
Grundlagen schliessen die naheliegenden Lesarten aus:

- Kapitel 8.2 über Pools: „Sichtbarkeit garantiert nicht, dass Preis dorthin
  läuft." Also bekommen gleiche Hochs/Tiefs **keine Richtung**. Die verbreitete
  Magnet-Deutung ist genau der Schluss, den dieser Satz verbietet. Gefunden und
  gezeichnet werden sie weiterhin.
- Kapitel 8.3 über Sweeps: „Ein Sweep allein ist keine Umkehrbestätigung... erst
  die nachfolgende Strukturänderung als zusätzliche Information." Sweep allein
  0,30; Sweep mit folgendem Bruch 0,70 — und dann meldet der Sweep eine
  Abhängigkeit vom Bruch, sonst wäre ein Ereignis zwei Belege in zwei Familien.

Ein Charakterwechsel auf derselben Kerze wie der Bruch *ist* dieser Bruch; auch
das steht als Abhängigkeit drin.

**Drei von zehn Familien liefern noch nichts** — Zeit & Nachrichten,
Positionierung, Historie. Das Panel sagt das ausdrücklich, damit „sieben
Familien" nicht als „alles berücksichtigt" gelesen wird.

**Die Gesamtbewertung** (`score/rating.py`): Severin wollte eine Zahl von 1 bis
100, immer sichtbar. Sie bewertet, **wie eindeutig das Bild ist — nicht, wie
wahrscheinlich ein Gewinn**. Die Richtung steht daneben: 90 mit „abwärts" ist
ein sauberer Short. Eine Wahrscheinlichkeit ist es nicht und kann es nicht
sein, solange nichts an Ergebnissen kalibriert ist.

Sie ist ein gewichtetes geometrisches Mittel aus vier verschiedenen Fragen:
Deutlichkeit (wie ausgeprägt die Neigung), Einigkeit (wie wenig Gewicht
dagegen), Mehrheit (wie viele Familien zustimmen), Abdeckung (wie viel
überhaupt gesprochen hat). **Produkt statt Mittelwert**, weil ein Mittelwert
einen starken Teil die anderen tragen lässt.

Beide Skalen sind **gemessen, nicht gewählt** — und beide ersten Entwürfe waren
falsch:

- Volle Punkte bei Deutlichkeit standen auf 0,80. Gemessen über 5 336 Kerzen
  liegt der Median der Neigung bei 1,09 — mehr als die Hälfte aller Kerzen
  hätte volle Punkte bekommen. Jetzt 2,5 (gemessenes 95. Perzentil).
- „Eindeutig" stand auf 80, was 24 % aller Kerzen so genannt hätte. Jetzt nach
  den gemessenen Dezilen: eindeutig 11 %, deutlich 23 %, gemischt 34 %,
  unklar 18 %, Durcheinander 14 %.

**Die 100 ist derzeit unerreichbar** (Decke gemessen: 96), weil drei Familien
schweigen. Das ist Absicht. Wenn sie verdrahtet werden, müssen die Schwellen
neu gemessen werden — steht als Notiz an der Konstanten.

**Ein Befund aus der Messung:** In 77 % der Kerzen ist *Deutlichkeit* der
schwächste Teil, in 23 % die Abdeckung, *Mehrheit* praktisch nie (0,2 %). Was
die Bewertung begrenzt, ist fast nie Streit über die Richtung — es ist, dass
die Familien nur schwach zeigen. Das passt zum Backtest-Befund, dass die
Einstiege keine messbare Kante haben.

**Gemessen, nicht weggedreht:** Eine Familie aus zwei deutlichen
Strukturbefunden hat einen Median nahe deren Stärke, eine aus siebzig
Indikatorwerten einen Median nahe null. Struktur dominiert damit um deutlich
mehr, als „1,00 gegen 0,70" vermuten lässt (gemessen: 0,75 gegen 0,02). Steht
als Notiz bei den Gewichten. Ob das richtig ist, entscheidet sich an
Ergebnissen — dafür braucht es die History-Engine, die noch nicht gebaut ist.

**Dashboard**: vier Märkte anklickbar, Chart mit Zonen und Ereignissen, das Tor
erklärt auf jeder Kerze warum kein Trade, Zeitebenen-Tabelle, alles auf Deutsch,
Wartezeit mit Sekundenzähler. **Neu: das Score-Panel** — zwei Zahlen statt
einer, pro Familie der Beitrag und darunter, was jede Zeitebene gesagt hat.
Eigener Endpunkt (`/api/market/{symbol}/score`), weil die Indikatoren über fünf
Zeitebenen beim ersten Aufruf pro Markt rund zehn Sekunden brauchen und der
Chart darauf nicht warten darf.

**Collector** (aus der Parallel-Session): läuft, schreibt vier Märkte über alle
Zeitebenen plus Funding nach Postgres.

## Papertrading: 2000 Trades, vollständig dokumentiert

`scripts/paper.py --replay` spielt die Guide-Setups über die gespeicherte
Historie und schreibt jeden Trade ins Journal (`data/journal.sqlite`, nicht im
Repo). Zu jedem Trade steht: welches Setup, welche Bewertung mit allen vier
Teilen, jede Familie mit Beitrag und Einigkeit, das Regime — und darunter, was
daraus wurde und in einem abgeleiteten Satz, warum.

**Das Ergebnis ist der schärfste Negativbefund des Projekts:**

    2000 Trades   Treffer 34 %   Summe −168,73 R
    Erwartung −0,084 R pro Trade  [−0,150, −0,021]  schliesst die Null aus

Alle früheren Messungen überlappten die Null. Diese nicht. Die Zahlen pro Markt
stimmen exakt mit den Backtests überein (BTC +0,051 · ETH +0,011 · SOL −0,169 ·
XRP −0,124) — das Journal reproduziert den Simulator, es erfindet nichts.

**Zum ersten Mal ordnet etwas die Ergebnisse:**

| Bewertung | n | Ergebnis | Intervall |
|---|---|---|---|
| eindeutig | 287 | +0,026 R | [−0,141, +0,191] |
| deutlich | 476 | −0,025 R | [−0,155, +0,117] |
| gemischt | 656 | −0,058 R | [−0,163, +0,050] |
| unklar | 349 | −0,228 R | [−0,382, −0,077] |
| Durcheinander | 232 | −0,201 R | [−0,364, −0,033] |

Die beiden schlechtesten Gruppen verlieren nachweislich. Alles unter 50
weglassen bringt die Erwartung von −0,084 auf −0,030 — besser, immer noch
Verlust. „Eindeutig" allein liegt bei +0,026 mit einem Intervall um die Null.
**Die Bewertung sagt zuverlässig, was man nicht handeln sollte. Sie sagt nicht,
womit man gewinnt.**

**Wo das Geld hingeht — der Ansatz für den nächsten Schritt:**

- **35 %** vom Docht geholt (Stop berührt, Kerze schloss wieder richtig)
- **19 %** waren ≥ 1 R im Plus und endeten als Verlust
- nur **8 %** liefen sofort gegen uns

Die Einstiege sind überwiegend nicht das Problem. Das Geld geht beim Ausstieg
verloren. Ob ein Stop auf Einstand bei 1 R hilft, ist der nächste Test — er
würde auch Gewinner zu Nullnummern machen, das ist nicht vorweggenommen.

**Achtung bei der Deutung:** Das ist ein Replay über gewählte Historie, kein
Vorwärtstest. Jede Entscheidung nutzt nur Kerzen bis zu ihrer eigenen (dafür
gibt es Tests), aber die Wahl des Zeitraums traf jemand, der weiss, wie er
ausging. Dafür trennt `Source` im Journal `replay` von `live`, und jeder
Bericht splittet darauf.

## Der Befund, der alles einordnet

Über vier Jahre, vier Symbole, zwei Zeitebenen: **die Einstiege aus dem Guide
haben keine messbare Kante.** Jedes Konfidenzintervall überlappt die Null —
auch das des Zufalls.

| guide-all | H1 | H4 |
|---|---|---|
| BTC | +0,051 R | +0,019 R |
| ETH | +0,011 R | −0,146 R |
| SOL | −0,169 R | +0,137 R |
| XRP | −0,124 R | — |

Zwei Messungen, die dabei wichtig sind:

**Die Kostenschwelle liegt bei 0,70 %.** Bei diesen Gebühren ist ein engerer Stop
nicht bezahlbar, unabhängig von der Idee. Die Guide-Setups setzen Stops an
Struktur, und die ist auf Stunden-Krypto oft dünner.

**Die Kostenregel ist Schutz, nicht Hindernis.** Deckel von 15 % auf 60 %
gelockert: jede Strategie kippt ins eindeutig Negative, der Zufall auf −0,251 R.
Die abgelehnten Trades sind genau die, die verlieren.

**Zeitebene wechseln halbiert die Gebühren zuverlässig und verbessert die
Erwartung nicht.** Also waren die Kosten nie das, was die Qualität begrenzt hat —
nur die Anzahl.

Daraus folgt die Richtung: **Analysewerkzeug, das die Lage zeigt und begründet.
Kein Signalgeber, der behauptet zu wissen wohin.**

## Ausstiege: beantwortet, und die Antwort ist nein

Der Stop auf Einstand hilft **nicht** messbar (`scripts/compare_exits.py`):

    ohne (original)      n=2005   −0.0869 R
    Einstand bei 0.5 R   n=2092   −0.0754 R   Differenz +0.0115
    Einstand bei 1.0 R   n=2054   −0.0782 R   Differenz +0.0087
    Einstand bei 1.5 R   n=2021   −0.0844 R   Differenz +0.0025

Grösste Differenz: **0,36 Standardfehler**. Das 95-%-Band um einen dieser
Mittelwerte ist ±0,063 R, fünfmal so breit wie der Effekt. Auf BTC allein macht
dieselbe Regel es schlechter — so sieht ein Nulleffekt in Teilmengen aus. Die
Regel rettet die Trades, die ihren Gewinn zurückgaben, und schneidet genau so
viele ab, die nur kurz eintauchten.

**Methodisch wichtig:** Die Trade-Zahlen unterscheiden sich, weil ein früher
beendeter Trade den nächsten Einstieg freigibt. Verglichen werden zwei
verschiedene Mengen, nicht dieselben Trades mit anderen Ausstiegen.

**Ein Fehler, den die eigene Prüfung gefangen hat.** Der erste Versuch spielte
die Minutenbars in einem eigenen Skript nach statt im Simulator — und lag um
0,074 R zu optimistisch, fast so viel wie der gemessene Effekt. Vier Ursachen:
Liquidationen, Kurslücken über den Stop, V08s Runner, und Zielabstände aus dem
Fill statt aus dem Plan. Alles Dinge, die der Simulator kennt. Lehre: Eine
Regel neben dem Simulator zu testen ist eine zweite Antwort auf dieselbe Frage.
Die Regel liegt jetzt als `breakeven_at_r` im Broker, standardmässig aus, mit
sieben Tests.


## Neu am 02.10.: das System handelt jetzt selbst — vorwärts, mit Spielgeld

`scripts/papertrade.py` läuft über alle vier Märkte und eröffnet, hält und
schliesst Trades ohne Rückfrage. Kein Konto, keine Börse, kein Schlüssel, keine
Order — der Pfad zur Börse existiert in diesem Programm nicht. Die
Bestätigungsregel für echte Orders ist unberührt.

**Warum das etwas Neues ist und nicht nochmal Papertrading.** Jede Zahl des
Projekts kam bisher aus Replay: der Simulator über Kerzen, die schon passiert
waren. Die Entscheidungen darin sind sauber — die No-Lookahead-Tests decken das
ab — aber die *Auswahl* des Zeitraums traf jemand, der wusste, wie er ausging.
Dagegen hilft kein Test. Hier steht die Begründung auf der Platte, **bevor** das
Ergebnis existiert, und kommt nie wieder an. Deshalb liegen diese Trades als
`Source.LIVE` im Journal und werden in keinem Bericht mit den Replay-Trades
gemittelt.

Die eine Zeile, auf der das steht: in `_maybe_open` wird die Begründung
*gebaut, bevor* die Order abgeschickt wird, und wenn sie nicht gebaut werden
kann, findet der Trade nicht statt. Eine Order jetzt und die Erklärung später
wäre ein Replay-Trade mit einem Vorwärts-Etikett.

**Die Ausstiege sind die des Simulators.** `SimBroker` löst Stop, Ziel,
Liquidation, Gebühren, Funding und Kurslücken minutenweise auf — dieselbe
Klasse, die die Backtests benutzen. Ein Vorwärts-Trader mit eigener Fill-Logik
wäre eine zweite Antwort auf dieselbe Frage; genau der Fehler, der beim
Ausstiegs-Vergleich am 01.10. 0,074 R Optimismus erzeugt hat.

**Es überlebt das Herunterfahren.** Konto, offene Position, ruhende Order und
die Begründung liegen in `data/paper.sqlite` und werden nach jedem Zyklus
geschrieben. Ein Vier-Stunden-Setup hält tagelang, und der Laptop geht aus —
ein Programm, das beim Neustart von vorne anfinge, würde genau die Trades
verlieren, derentwegen das Ganze läuft. Fortgesetzt wird nach Zeitstempel: die
Minuten, die in der Lücke fehlen, holt der nächste Zyklus von der Börse nach,
bevor er den Trade auflöst.

**Was dabei auffiel und gemessen wurde.** Die Analyse über das ganze Archiv zu
bauen dauert **146 Sekunden** pro Symbol (BTC, vier Kontext-Ebenen) plus 12,8
für die Bewertung einer Kerze. Über die letzten 5 000 Kerzen je Ebene: **8,5 und
1,2**. Fünfzehnfach, und der Unterschied zwischen einer Schleife, die mitkommt,
und einer, die es nicht tut. 5 000 ist zwölfmal der längste Rückblick, den
irgendetwas in der Analyse angibt (Trendlinien verwerfen eine Linie nach 400
Kerzen). Abgeschnitten wird damit nur eine unberührte Zone, die älter ist —
52 Tage auf M15, sieben Monate auf H1. Die Backtests lesen das ganze Archiv, also
sind eine Vorwärts- und eine Replay-Lesung nicht bitgleich. Steht an der
Konstanten.

**Auf dem Dashboard** gibt es dafür einen eigenen Bereich unter der
Entscheidung: pro Markt das Konto und die offene Position mit Entry, Stop, Ziel
und offenem Gewinn, darunter die zuletzt geschlossenen Trades mit dem Satz,
warum sie so endeten. Eigener Endpunkt `/api/paper`, der die beiden Dateien des
Traders liest — läuft also auch, wenn der Trader aus ist, und **sagt dann, dass
er aus ist**. Ein Konto, dessen letzte verbuchte Minute sechs Stunden alt ist,
sieht sonst exakt aus wie ein laufendes; dieser Fehler hat beim Score-Panel
schon eine Stunde gekostet.

**Starten:**

```bash
.venv\Scripts\python.exe -u scripts\papertrade.py          # läuft bis Strg-C
.venv\Scripts\python.exe scripts\papertrade.py --status    # nur lesen
.venv\Scripts\python.exe scripts\papertrade.py --close-out # alles offene schliessen
```

17 Tests in `tests/test_papertrade.py`. Die drei, auf die es ankommt: die
Begründung liegt vor dem Ergebnis auf der Platte; ein Neustart behält Position
und Begründung; eine Minute wird nie zweimal verbucht.

## Setup B ist gemessen — es rettet nichts

Mit Trendlinien (`fdb5261`) und allen vier Zeitebenen:

    2734 Trades, 1,91/Tag    Gesamt −0,0906 R  [−0,143, −0,036]

    Setup A  n=1061  −0,042 R  Treffer 41 %  [−0,117, +0,031]
    Setup B  n= 665  −0,079 R  Treffer 32 %  [−0,192, +0,031]   ← neu
    Setup C  n= 872  −0,149 R  Treffer 23 %  [−0,249, −0,049]
    Setup G  n= 132  −0,121 R  Treffer 30 %  [−0,375, +0,160]

B reiht sich ein: Intervall über der Null, 32 % Treffer. Die Energie-Bedingung
aus V06 bringt in dieser Messung nichts, was den anderen fehlt. **Setup C
verliert als einziges mit einem Intervall, das die Null ausschliesst** — jetzt
über drei verschiedene Journal-Durchläufe mit unterschiedlicher Zusammensetzung
stabil. Das ist der robusteste Einzelbefund des Projekts.

An dem Tag wurde die Trade-Zahl um 37 % erhöht, ein Setup freigeschaltet, vier
Zeitebenen erschlossen — und die Erwartung ging von −0,084 auf −0,091 R. Mehr
Wege in den Markt helfen nicht, solange die Regeln keine Kante haben. Der Hebel
liegt bei *weniger*: C abschalten halbierte in der vorherigen Messung den
Verlust.


## Der erste echte Vorwärts-Trade, und was er sofort zeigte

Am 02.10. um 08:00 UTC eröffnete das System seinen ersten Trade ohne Rückfrage:

    BTCUSDT   Setup C — Supply/Demand-Retest, 4-Stunden-Chart
              SHORT 0.06 @ 86 092.30
              Stop  86 923.00  (0,96 % entfernt)
              Ziel  83 810.40  (CRV 2,75)

Die Begründung lag auf der Platte, bevor die Order rausging — und sie sagt
etwas Unangenehmes:

    Bewertung 82/100 "deutlich"  —  Richtung: AUFWÄRTS
    Regime trend_up      Richtung passt zum Setup: NEIN

    Trend +0.647 · Struktur +0.592 · Lage +0.638 · Volatilität +0.232
    Volumen +0.096 · Momentum +0.069   |   Liquidität −0.215

Sechs von sieben Familien zeigen nach oben, die Gesamtbewertung ist mit 82
ziemlich eindeutig aufwärts — und das System geht short. Mit **Setup C**, dem
einzigen Setup, das nachweislich verliert. Kein Fehler: Setup C schaut auf eine
Supply-Zone, nicht auf den Gesamtscore, und die Bewertung ist in den
Einstiegsregeln nirgends ein Vetorecht.

## Soll die Bewertung ein Veto bekommen? Gemessen: nein

Naheliegend nach obigem Trade, also gemessen statt gemeint — über alle 2734
Replay-Trades, mit `rating_agreed_with_setup`:

    Score stimmt zu   n=1849   −0,083 R   Treffer 36 %   [−0,141, −0,021]
    Score dagegen     n= 885   −0,108 R   Treffer 26 %   [−0,210, +0,001]
    Differenz +0,025 R = 0,42 Standardfehler

Und pro Setup dreht das Vorzeichen:

    A:  zu −0,018 | gegen −0,231   Diff +0,213
    B:  zu −0,099 | gegen +0,021   Diff −0,120
    C:  zu −0,225 | gegen −0,109   Diff −0,116
    G:  zu −0,249 | gegen −0,052   Diff −0,197

Bei **drei von vier Setups** laufen die Trades *gegen* den Score besser.
Dasselbe Muster wie beim Stop auf Einstand: ein Nulleffekt, der in Teilmengen
mal so und mal so aussieht. **Nicht eingebaut.** Ein auffälliger Einzelfall ist
kein Befund.

## Dauerbetrieb: die Prozesse laufen losgelöst

Hintergrundbefehle aus einer Claude-Sitzung werden nach **zehn Minuten**
abgeschossen. Ein Papertrader, der alle zehn Minuten stirbt, ist keiner. Beide
Prozesse laufen deshalb losgelöst weiter, auch wenn die Sitzung endet:

```powershell
$py = ".\.venv\Scripts\python.exe"
Start-Process $py -ArgumentList "-u","scripts\papertrade.py" `
  -RedirectStandardOutput "papertrade.log" -RedirectStandardError "papertrade.err.log" `
  -WindowStyle Hidden -PassThru
```

Ausgaben landen in `papertrade.log` und `dashboard.log`.

**Anhalten — nicht über die PID aus `.pid`.** Das venv-`python.exe` ist ein
Starter, der den eigentlichen Interpreter als Kindprozess startet. Die PID, die
`Start-Process` zurückgibt, ist die des Starters; `taskkill /PID <id> /F` darauf
lässt das arbeitende Python verwaist weiterlaufen. Gemessen: Starter 34604 →
Arbeiter 40688. Stattdessen über die Kommandozeile suchen, dann ist auch keine
PID nötig:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'papertrade|run_dashboard' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

(`taskkill /PID <id> /T /F` ginge auch — `/T` nimmt den Baum mit —, aber die
Variante oben braucht keine gespeicherte PID und überlebt jeden Neustart.) Nach einem Laptop-Neustart einfach neu starten — die Konten kommen
aus `data/paper.sqlite` zurück, inklusive offener Position und Begründung. Das
ist am 02.10. einmal echt passiert und hat funktioniert.

## Eine Fehldiagnose, die ich zurücknehmen musste

Nach einem Neustart standen drei Konten eine Stunde hinter dem vierten. Ich
nannte das einen Fehler. Es war keiner: jedes **flache** Symbol baut seine
Analyse neu, sobald eine neue Stundenkerze da ist — acht Sekunden plus
Parquet-Lesen — während das Symbol mit offener Position die Entscheidung
überspringt und sofort fertig ist. Der erste Durchlauf über vier Märkte dauert
also ein bis zwei Minuten, und ich hatte mittendrin gemessen. **Eine
eingefrorene Uhr und eine Warteschlange, in die man hineinmisst, sehen von
aussen identisch aus.** Erst zweimal messen, dann die Diagnose.

Behalten habe ich zwei Dinge, die beim Nachlesen auffielen und unabhängig davon
falsch waren: Abrechnen und Entscheiden hingen an einem `try` (ein Fehler beim
Entscheiden hätte die abgerechneten Minuten der offenen Position mitgerissen),
und der Satz „warum passiert nichts" konnte nicht sagen „alles wirft" — ein
Loop, der jeden Zyklus scheitert, las sich wie ein ruhiger Markt.


## „Warum nur 1,9 Trades pro Tag?" — gemessen, und die Antwort ist gut

Severins häufigste Frage, und zum ersten Mal mit einer Zahl beantwortet. Der
grösste Filter auf die Trade-Zahl ist die **Kostenschwelle**
(`max_cost_fraction_of_risk: 0.15`): Gebühren dürfen höchstens 15 % dessen
fressen, was riskiert wird. Positionsgrösse ist Risiko geteilt durch
Stop-Abstand, Gebühren skalieren mit der Position — ein enger Stop kauft also
eine grosse Position und damit grosse Gebühren auf dasselbe Risiko.

`scripts/study_cost_floor.py`, vier Decken, vier Märkte, vier Jahre:

    Decke 0.15   2734 Trades   −0,0904 R   Treffer 33 %   Summe  −247,2 R
    Decke 0.25   3803 Trades   −0,1103 R   Treffer 32 %   Summe  −419,5 R
    Decke 0.40   4575 Trades   −0,1418 R   Treffer 31 %   Summe  −648,7 R
    Decke 1.00   5277 Trades   −0,2076 R   Treffer 31 %   Summe −1095,3 R

    Die zusätzlichen Trades allein:
      bis 0.25   1069 Stück   im Mittel −0,161 R
      bis 0.40   1841 Stück   im Mittel −0,218 R
      bis 1.00   2543 Stück   im Mittel −0,334 R

**Es gibt fast doppelt so viele Trades, und sie sind zuverlässig schlechter.**
Die heute weggefilterten verlieren rund dreimal so viel wie die
durchgelassenen. Und es ist monoton über vier Einstellungen, bei Stichproben
von tausend bis zweieinhalbtausend — so sieht ein echter Effekt aus.

Zum Vergleich, was in diesem Projekt sonst gemessen wurde: eine Bewertung, die
die Ergebnisse nicht ordnet; ein Stop auf Einstand mit 0,36 Standardfehlern;
ein Score-Veto, dessen Vorzeichen zwischen den Setups wechselt. **Die
Kostenschwelle ist die einzige Regel mit einem Effekt, den man ohne Kneifen
sieht — und sie ist bereits an.**

Also: 1,9 Trades pro Tag sind kein Mangel, den man beheben müsste. Das ist der
Filter bei der Arbeit, und die Antwort auf „da müsste mehr gehen" lautet: es
geht mehr, und es verliert.

*Einschränkung, dieselbe wie beim Ausstiegs-Vergleich:* verglichen werden vier
verschiedene Trade-Mengen, nicht dieselben Trades unter anderen Regeln, weil
ein früh beendeter Trade den nächsten Einstieg freigibt. Dort hat das den
Befund zerlegt; hier nicht, weil der Unterschied um ein Vielfaches grösser ist
als alles, was diese Verschiebung erklären könnte.

## Als Nächstes

1. **Der Sync Postgres → Parquet.** Der Pi schreibt nach Postgres, das Dashboard
   liest Parquet. Das ist so entworfen (Landezone vs. Archiv), aber das Skript,
   das die Landezone nach vorne leert, existiert noch nicht. Das ist die letzte
   Lücke zum Pi — und seit die Datenbank wirklich auf dem Pi liegt, die
   dringendste.
3. **Die ersten Vorwärts-Trades gegen die Replay-Zahlen halten.** Bei
   1,9 Trades pro Tag über vier Märkte sind das ein paar Dutzend in zwei Wochen
   — zu wenige für eine Aussage, aber genug, um zu sehen, ob der Simulator das
   trifft, was vorwärts wirklich passiert. Das ist die einzige Messung, die
   Replay nicht liefern kann.
4. **TradingView-Widget als zweiter Tab** (Lightweight Charts bleibt der Hauptchart;
   Advanced Charts ist für private Nutzung nicht lizenziert).
5. **History-Engine** — sie ist die einzige Instanz, die die Gewichte und die
   Struktur-Dominanz empirisch beantworten kann. Vorher ist jede Änderung an
   `DEFAULT_FAMILY_WEIGHTS` ein Argument, keine Messung.

## Offen, braucht Severin

> Ausführlich mit Begründung und Schritt-für-Schritt:
> [[traidingBrain — Deine To-Do-Liste]]

- **Risiko pro Trade: Prozent vom Konto oder fester CHF-Betrag?** Der Guide sagt
  in Kapitel 23 ausdrücklich nichts dazu. Fester Betrag müsste gebaut werden.
- **Maximale Trades pro Tag?** Existiert noch nicht.
- **Setup C abschalten?** Gut belegt (verliert auf allen vier Zeitebenen, das
  Intervall schliesst die Null aus), über drei unabhängige Messungen stabil —
  aber es ist dein Regelwerk, die Entscheidung gehört dir. Ausgerechnet der
  erste Vorwärts-Trade ist einer.
- **Setup D** braucht deinen Stop, **Setup E** dein Take Profit. Beide
  Regelkarten sagen wörtlich, dass die Videos dazu nichts angeben.
- **Liest du Chartzeiten in UTC oder Schweizer Zeit?** Alles Gespeicherte ist
  UTC; im Sommer sind das zwei Stunden Unterschied, und daran reden zwei Leute
  zuverlässig über verschiedene Kerzen aneinander vorbei.
- Ein **volljähriges Börsenkonto**, bevor irgendetwas echtes Geld anfasst.

## Zwei Fallen, an die ich mich erinnern muss

**Zwei Sessions im selben Repo.** Die Parallel-Session arbeitet am Collector und
an Postgres. Heute gab es zweimal Testfehler, die beim nächsten Lauf weg waren,
weil beide gleichzeitig dieselben Dateien schrieben. Vor grösseren Änderungen
`git log --oneline -5` prüfen.

**Ich habe heute zweimal aus einer Stichprobe geschlossen.** Einmal „H4 ist
eingeschlagen" nach einem Symbol (zwei weitere gingen in die Gegenrichtung),
einmal „meine Regeln filtern mehr weg als deine" mit dem falschen Unterton (die
gefilterten Trades sind die Verlierer). Beide Male musste ich zurücknehmen.
Erst alle Symbole, dann die Aussage.
