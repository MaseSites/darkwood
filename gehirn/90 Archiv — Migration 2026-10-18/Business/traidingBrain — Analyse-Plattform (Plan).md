---
typ: projekt-plan
projekt: traidingBrain
status: entwurf-freigegeben
naechster_schritt: Stufe 1 bauen — Score-Kern mit Familien-Gewichtung
aktualisiert: 2026-09-30
entscheidungen:
  chart: Lightweight Charts als Hauptchart + TradingView-Widget als Tab
  budget: 24/7 deterministisch, Modell nur auf Klick
verwandt:
  - "[[traidingBrain]]"
  - "[[traidingBrain — Regel-Aufnahme]]"
---

# traidingBrain — Analyse-Plattform

Severins Vorgabe in einem Satz: **ein vollständiges Analysewerkzeug**, in dem fünf
Sektoren zusammen eine Bewertung pro Asset ergeben, nicht ein Signalgeber.

Dieser Plan setzt zwei getroffene Entscheidungen um und sagt bei jedem Punkt
dazu, was messbar ist und was ein Modell bleibt.

---

## 0. Zwei harte Tatsachen vorweg

### Die echte TradingView-Oberfläche ist nicht nutzbar

TradingViews FAQ, wörtlich: *"we don't provide the Advanced Charts and the
Trading Platform libraries for personal use, hobbies, studies, or testing."* Frei
ist sie **nur für Firmen in öffentlichen Projekten**. Ein privates Werkzeug fällt
nicht darunter, und daran ändert auch ein Firmenmantel nichts, solange das
Projekt privat bleibt.

Was bleibt:

| | echte TV-Oberfläche | unsere Zeichnungen darin | deine Zeichnungen lesbar |
|---|---|---|---|
| Lightweight Charts (Apache 2.0) | nein | **ja** | **ja** |
| TradingView-Widget (gratis, iframe) | **ja** | nein | nein |
| Advanced Charts | ja | ja | nicht lizenziert |

**Entschieden: beides nebeneinander.** Hauptchart ist Lightweight Charts — dort
lebt die Analyse und die Lernschleife. Daneben ein Tab mit dem echten
TV-Widget für manuelle Arbeit. Was du dort zeichnest, sieht das System nicht;
was du im Hauptchart zeichnest, lernt es.

### „Institutionelle Liquidität" ist aus Chartdaten nicht bestimmbar

Severins Wunsch, private und institutionelle Liquidität zu unterscheiden und
beide einzuzeichnen, geht so nicht — und die eigene Wissensbasis sagt es auch:
Kapitel 12.7 nennt als Hauptgrenze der Volumenfluss-Familie *"keine direkte
Identifikation institutioneller Käufer/Verkäufer"*, Kapitel 11.5 warnt, dass
ohne echte Aggressor-Klassifikation das Signal unvollständig ist.

Was **tatsächlich messbar** ist und stattdessen kommt:

| Anzeige | Datenquelle | Was es wirklich sagt |
|---|---|---|
| Stop-Cluster über/unter Swings | eigene Swing-Erkennung | wo Stops liegen dürften |
| Orderbuchtiefe | Börsen-Websocket | sichtbare, noch nicht ausgeführte Liquidität |
| Grosse Einzelausführungen (Tape) | Trade-Stream, Schwelle in ATR | ungewöhnlich grosse Aggression — **nicht** „Institution" |
| Open Interest + Funding | Börse | Positionsaufbau und Schieflage |
| Liquidationen | Börse | erzwungene Schliessungen, modellierte Cluster |
| CVD / Delta | Trade-Stream | Aggressorseite, nicht Käuferzahl |

Auf dem Chart heisst die Ebene deshalb **„Grossaufträge"** und nicht
„institutionell". Ein Etikett, das mehr behauptet als die Daten hergeben, wäre
genau die Sorte Fehler, die man erst nach Geldverlust bemerkt.

---

## 1. Die fünf Sektoren und ihre Taktung

Severins Entscheidung: **Zahlen laufen durchgehend und gratis, das Modell läuft
nur auf Klick.** Daraus folgt die Aufteilung.

### Dauerlauf, deterministisch, kostenlos

| Sektor | Was läuft | Frequenz |
|---|---|---|
| **1 Historie** | 24-h-Fenster: Vortageshoch/-tief, Sessionrange, Gap, POC, Eventkerzen; Einordnung des aktuellen Kurses darin | pro Bar |
| **2 News** | Wirtschaftskalender mit Actual/Forecast/Previous, Überraschung = Actual − Forecast, Revisionen; Risiko-Herabsetzung im Fenster um hohe Wichtigkeit | 15 min |
| **3 Indikatoren** | die Familien aus Kapitel 12, je Familie ein Nettobefund | pro Bar |
| **4 Liquidität** | Pools, Sweeps, Orderbuchtiefe, Grossaufträge, OI, Funding, Liquidationen | Stream + pro Bar |

### Auf Klick, mit sichtbarer Ladezeit

| Sektor | Was läuft | Dauer |
|---|---|---|
| **5 Chart-Analyse** | Zonen über alle Zeitebenen, FVGs, Order Blocks, eigene Linien, Bewertung jeder einzelnen, Mehr-Zeitebenen-Übereinstimmung, Prognosekerzen | ~30 s, mit Fortschrittsanzeige |

Der Fortschritt zeigt, **was** gerade gerechnet wird — nicht einen Balken.
„Wochenstruktur", „Zonen H4", „FVGs bewerten", „Prognose". Eine Ladezeit, bei
der man sieht wofür, ist eine andere Erfahrung als dieselbe Ladezeit mit einem
Kreisel.

---

## 2. Der Score — und warum nicht 50 Indikatoren addiert werden

Severins Wunsch: 50 Indikatoren laufen gleichzeitig, jeder fliesst gewichtet ein.

Die Indikatoren kommen. Das **Addieren** kommt nicht, und der Grund steht in
deiner eigenen Wissensbasis, Kapitel 12.6:

> *„RSI, Stochastic, StochRSI und Williams %R sind alle Momentum-/Range-Lage-Werkzeuge;
> vier gleiche Richtungen sind nicht vier unabhängige Belege."*

und Kapitel 17:

> *„Konfluenz bedeutet mehrere verschiedene Informationsfamilien stimmen in einer
> Hypothese überein... Drei Momentumindikatoren sind eine Familie."*

Fünfzig Indikatoren auf dieselbe Preisreihe sind keine fünfzig Meinungen. Sie
summieren heisst, dieselbe Information zwanzigmal zu zählen — und der Score
würde immer extrem ausschlagen, weil eine Familie ihn allein kippen kann.

### Wie es stattdessen rechnet

**Stufe 1 — jeder Indikator einzeln**, mit den Pflichtfeldern aus Kapitel 12.7:
`input_series`, `venue`, `lookback`, `formula_version`, `output_unit`, `lag`,
`family`, `failure_modes`, `source`.

**Stufe 2 — Verdichtung je Familie.** Innerhalb einer Familie zählt nicht die
Mehrheit, sondern der Median mit Streuung. Vier gleichlaufende
Momentum-Oszillatoren ergeben **einen** Befund mit hoher Sicherheit, nicht vier.
Widersprechen sie sich, ergibt das einen schwachen Befund — was die ehrliche
Auskunft ist.

**Stufe 3 — Befunde über Familien hinweg**, jeder mit den Feldern aus Kapitel 17:

```
family        trend | momentum | volatilitaet | volumen | struktur |
              ort   | liquiditaet | zeit_news | positionierung | historie
direction     bullish | bearish | neutral
strength      0..1
freshness     Bars seit Entstehung, in ATR-normierter Distanz
timeframe     W1 | D1 | H4 | H1 | M15
source        V09 | Z12 | eigene Messung
dependent_on  Liste von Befunden, aus denen dieser folgt
```

**`dependent_on` ist das Feld, das Doppelzählung verhindert.** Ein FVG und die
Displacement-Kerze, die es erzeugt hat, sind nicht unabhängig — Kapitel 17 sagt
das ausdrücklich. Hängt ein Befund an einem anderen, wird sein Gewicht geteilt,
nicht addiert.

**Stufe 4 — Gegenevidenz getrennt führen.** Kapitel 17 verlangt es: HTF-Widerstand
gegen bullischen LTF-BOS, negatives CVD gegen steigenden Preis, News in fünf
Minuten gegen ruhiges technisches Bild. Der Score zeigt **zwei Zahlen** — dafür
und dagegen — und nie nur die Differenz. Eine 70 aus „80 dafür, 10 dagegen" ist
eine andere Lage als eine 70 aus „85 dafür, 15 dagegen", und die Differenz
allein verschweigt das.

**Stufe 5 — Mehr-Zeitebenen.** Stimmen Zeitebenen überein, steigt `strength`.
Widersprechen sie sich, gibt es **kein** binäres Urteil, sondern die Beschreibung
aus Kapitel 13: `HTF_uptrend / MTF_discount_pullback / LTF_bearish_internal`.

### Situative Gewichtung

Severins Wunsch, dass jedes Element situationsabhängig gewichtet wird, ist
genau richtig und wird so umgesetzt:

- **Regime entscheidet zuerst.** Momentum-Oszillatoren wiegen in einer Range
  schwer und in einem starken Trend fast nichts — Kapitel 12.2: *„overbought
  kann in starkem Trend lange bestehen"*.
- **Frische.** Ein unberührtes FVG wiegt mehr als ein dreimal getestetes. Nach
  welcher Regel — V05 oder V13 — bleibt eine Einstellung, weil die Quellen sich
  widersprechen und keine ihn entscheidet.
- **Ort.** Ein Befund an einer Zone wiegt mehr als derselbe Befund im Nichts.
- **Nähe zu News.** Innerhalb des Fensters um eine hochwichtige Veröffentlichung
  wird technisches Gewicht reduziert und das Risikobudget gesenkt.
- **Jedes Gewicht steht in `config/weights.yaml`** mit Begründung, und jede
  Änderung ist ein Commit. Kein Gewicht wird im Code versteckt.

---

## 3. Die Chart-Analyse auf Klick

Was in den ~30 Sekunden passiert, in dieser Reihenfolge:

1. **Struktur je Zeitebene** — Swings, BOS, CHoCH, mit Bestätigungsindex
2. **Zonen** — Supply/Demand (V09), Order Blocks (V11), Inducement/True Zone (V12)
3. **FVGs** — mit V05-Filtern und V13-Sechs-Faktoren, getrennt bewertet
4. **Eigene Linien** — Trendlinien, Kanäle, aus den Ankern der bestätigten Swings
5. **Bewertung jeder Zeichnung** einzeln: Frische, Anzahl Tests, Zeitebene,
   Übereinstimmung mit anderen Ebenen, Abstand zum Preis in ATR
6. **Prognose**

### Prognosekerzen — ehrlich gezeichnet

Severins Wunsch: durchsichtige Kerzen, die zeigen, wie es weitergehen könnte.

Das kommt, aber **nicht als ein Pfad**. Ein einzelner durchscheinender Verlauf
sieht aus wie eine Vorhersage und ist keine. Stattdessen:

- **Ein Fächer** aus Quantilen der historisch ähnlichen Situationen (die
  History-Engine mit Purging und Embargo liefert die Nachbarn)
- Die mittleren 50 % dunkler, die mittleren 90 % heller
- Darüber die Zahl, auf der es beruht: *„aus 84 ähnlichen Lagen"*
- Sind es zu wenige Nachbarn, wird **nichts gezeichnet** und das steht da

Ein Fächer, der breit ist, sagt ehrlich „unklar". Eine Linie kann das nicht.

### Gespräch über den Chart

Du klickst eine Zone an und fragst: *„warum sollte die halten?"* Das Modell
bekommt die Befunde zu genau dieser Zone — Frische, Tests, Zeitebene,
Gegenevidenz — und antwortet darauf. Sagst du *„die bricht, weil X"*, wird X als
Befund mit `source: severin` aufgenommen und der Score **sichtbar** neu gerechnet:
vorher, nachher, und welcher Befund es bewegt hat.

### Lernen aus deinen Korrekturen

Löschst du eine Zeichnung oder markierst sie als schlecht, wird gespeichert:
welcher Detektor, welche Parameter, welches Regime, welche Zeitebene, welcher
Abstand zum Preis. Nach genug Fällen zeigt eine Auswertung, **welcher Detektor
unter welchen Umständen abgelehnt wird**.

Wichtig: das verändert **nicht automatisch** die Gewichte. Sonst hättest du
selbstmodifizierende Handelslogik — genau das, was die Bestätigungsregel
verhindern soll. Es landet in einer Review-Liste mit Zahlen, und du entscheidest.

---

## 4. Broker, Journal und die Fehlersuche

- **Broker-Anbindung** über ccxt, wie gehabt. Ausführung nur mit gehaltener
  Bestätigung, Auszahlungsrechte nie.
- **Journal**: jeder Trade mit dem **vollständigen Score-Zustand zum
  Einstiegszeitpunkt** — alle Befunde, alle Gegenevidenz, alle Gewichte. Ohne
  das ist eine spätere Fehlersuche Raten.
- **Auswertung**: nach jedem abgeschlossenen Trade prüft das System, welche
  Befunde bei Gewinnern und welche bei Verlierern vorlagen. Nach genug Fällen
  entsteht eine Liste wie *„Befunde der Familie Momentum ohne Struktur-Befund:
  31 Trades, Erwartung −0,3 R"*.
- Auch das geht in die Review-Liste, nicht direkt in die Gewichte.

---

## 5. Was die Messungen dieser Session für den Plan bedeuten

Zwei Ergebnisse ändern die Voreinstellungen:

**Die Kostenschwelle.** Bei diesen Gebühren ist ein Stop näher als **0,70 %** nicht
bezahlbar, egal wie gut die Idee ist. Der Score zeigt deshalb bei jedem
vorgeschlagenen Trade an, ob er diese Schwelle überhaupt erreicht.

**Die Zeitebene.** Dieselben Regeln auf SOLUSDT:

| | Trades | Erwartung | Rendite | Drawdown | Gebühren |
|---|---|---|---|---|---|
| H1 | 729 | **−0,169 R** (belegt negativ) | −47,1 % | 51,3 % | 1.651 |
| H4 | 242 | **+0,137 R** | +17,0 % | 15,3 % | 578 |

Das Vorzeichen kippt, die Gebühren fallen auf ein Drittel, der Drawdown auf ein
Drittel. **Die Voreinstellung wird H4**, nicht H1. Das Intervall auf H4 enthält
noch die Null — profitabel ist damit nicht belegt, aber verlustreich auch nicht
mehr, und das ist ein anderer Ausgangspunkt.

---

## 6. Baureihenfolge

Jede Stufe hat ein überprüfbares Kriterium. Keine Stufe beginnt, bevor die
davor steht.

| Stufe | Inhalt | Abnahme |
|---|---|---|
| **1** | Score-Kern: Befunde, Familien, `dependent_on`, Gegenevidenz getrennt | Ein Test beweist, dass vier Momentum-Indikatoren **einen** Befund ergeben, nicht vier |
| **2** | Indikator-Inventar nach Kapitel 12, alle mit Pflichtfeldern | Jeder Indikator meldet `family` und `lag`; ein Test findet jeden ohne Familie |
| **3** | Sektoren 1, 3, 4 im Dauerlauf; Score live | Score aktualisiert sich pro Bar ohne Modellaufruf |
| **4** | News-Sektor mit Überraschung und Revision | Ein Test beweist: kein Kalendereintrag wird vor seiner Veröffentlichung gelesen |
| **5** | Chart: Lightweight Charts, unsere Ebenen, TV-Widget als Tab | Zonen, FVGs, Liquidität sichtbar; Umschalten funktioniert |
| **6** | Chart-Analyse auf Klick mit benannter Fortschrittsanzeige | < 45 s kalt, Fortschritt nennt den Schritt |
| **7** | Prognose-Fächer aus der History-Engine | Zu wenige Nachbarn → nichts gezeichnet, und das steht da |
| **8** | Zeichnen, Löschen, Lernschleife in die Review-Liste | Gelöschte Zeichnung erscheint mit Begründungsfeldern in der Liste |
| **9** | Journal mit vollständigem Score-Zustand | Jeder Trade lässt sich Monate später vollständig rekonstruieren |
| **10** | Gespräch über den Chart, Score-Neuberechnung sichtbar | Vorher/nachher und der bewegende Befund werden angezeigt |

---

## 7. Was in diesem Plan bewusst fehlt

- **Kein Auto-Trading.** Unverändert: jede Order braucht eine 1,2 Sekunden
  gehaltene Bestätigung durch einen Menschen.
- **Keine automatische Gewichtsanpassung.** Lernen landet in einer Review-Liste.
- **Keine erfundenen Zahlen.** Wo die Quellen schweigen — Positionsgrösse,
  Tagesverlustlimit, Sessions — bleibt es leer, bis Severin es festlegt.
- **Kein „institutionell"-Etikett** auf Daten, die das nicht hergeben.

Verwandt: [[traidingBrain]] · [[traidingBrain — Regel-Aufnahme]]
