---
typ: forschung
status: entschieden
aktualisiert: 2026-10-21
naechster_schritt: Vorgabe 20x bestätigt (21.10.); E25 Beständigkeit über eine Woche vorregistriert, Sammler läuft; danach E0 mit echtem Unterkonto; E24-Ergebnis abwarten
tags: [durchbruch, ziel, familie, market-making, kapital, evidenz]
---

# 🎯 Was ein Durchbruch bräuchte — 21.10.2026

Auftrag des Eigentümers: *„mache eine komplette Analyse, was brauchst du, um
stark profitabel zu werden — etwas, das wirklich der Durchbruch sein wird."*

Diese Notiz ist die Antwort. Sie erfindet nichts; jede Zahl steht in einem
Audit-Dokument des Repos oder wurde heute daraus gerechnet. Was sie nicht
liefert, ist der Durchbruch selbst — den liefert nur eine Messung, die ein
Intervall ohne Null auf der richtigen Seite zurückgibt, und das hat in 124
registrierten Armen über 22 Familien noch keine getan.

## 1. Was „stark profitabel" in Zahlen heisst

| Ziel | je Tag | je Monat | je Trade bei 3,5 Trades/Tag, 1 % Risiko |
|---|---|---|---|
| **20× in 182 Tagen** (Vorgabe) | **+1,66 %** | **+63,9 %** | **+0,4536 R** |
| 5× in 182 Tagen | +0,89 % | +30 % | ~+0,25 R |
| 2× in 182 Tagen | +0,38 % | +12 % | ~+0,10 R |

Gemessen über 7'335 Trades: **−0,0129 R**, Intervall **[−0,087; +0,059]**,
Streuung 1,39 R je Trade. Die Schranke nach fixed-fractional Sizing an der
günstigsten Stelle (`EV_min = SD·√(2·ln20/N)`) verlangt bei 312 Trades
+0,19 R, bei 643 Trades +0,13 R — Faktor 4,8 bis 7,1 über der oberen
Intervallgrenze, je nach Clusterung (Briefing 04, Nachtrag 19.10.).

**Was ein kleiner echter Vorteil wert wäre, falls er existierte** (Kelly-
Rechnung, SD 1,39 R, 182 Tage):

| Vorteil je Trade | 1,7 Trades/Tag, halbes Kelly | 3,5 Trades/Tag, halbes Kelly | Nachweis im Vorwärtslauf |
|---|---|---|---|
| +0,05 R | 1,16× | 1,37× | 3'081 Trades ≈ 4,4 Jahre |
| **+0,10 R** | 1,84× | **3,5×** | 770 Trades ≈ 13 Monate |
| +0,20 R | 11× | 150× | 193 Trades ≈ 3,3 Monate |
| +0,45 R | — | — | 37 Trades ≈ 3 Wochen |

Lesart: **+0,10 R je Trade wäre bereits „stark profitabel"** (3,5× im
Halbjahr bei halbem Kelly), und das ist ein Viertel der Vorgabe. Das Problem
ist nicht, dass die Vorgabe zu hoch ist. Das Problem ist, dass **kein
gemessener Arm überhaupt von null zu trennen ist** — und dass ein Vorteil
dieser Grösse im Vorwärtslauf erst nach über einem Jahr sichtbar würde. Der
Vorwärtslauf kann nur grosse Vorteile beantworten.

## 2. Warum die laufende Familie es nicht sein wird

Die Familie „direktionale Preisstruktur-Setups auf Perpetuals" ist gemessen
erschöpft. Nicht als Meinung, sondern als Liste geschlossener Achsen:

| Achse | Befund | Quelle |
|---|---|---|
| Einstiege | brutto null, der Verlust ist Gebühr | `entries-carry-no-edge`, Freqtrade 15'624 Trades |
| Richtung | 35 Merkmale, Korrelation 0,004; Beta 1,0 zu BTC, Rest negativ | E8, Outlook-Studie |
| Auswahl (ML) | besser als Zufall, absolut negativ (−0,10 / −0,07 R) | E1 |
| Ausgänge | sieben Arme, alle schlechter als Stop+Ziel | E3, E14, E15, E22 |
| Zeitebene | +0,0856 R in-sample → +0,0341 R out-of-sample, Null drin | E17 |
| Kosten | billig ist besser (+0,056 R brutto), aber nicht positiv | Kostendeckel-Studie |
| Deckel, Grösse, Hebel | ändern nur die Skala, R ist grössenunabhängig | E13 |
| Bewertungsschicht | trennt über 7'335 Trades nichts | 21.10. |
| Takt der Balken | **läuft** (E24), Erwartung „unentschieden" | heute |

E24 ist der letzte Arm, den das Register in dieser Familie noch zulässt. Fällt
er, ist die Familie geschlossen, auch formal.

**Die Grenze, die alles bindet:** Die Auszahlung ist fest (+1,50 / −1,01 R).
Jeder Trade ist eine Wette auf Richtung über Stunden, und Richtung über
Stunden ist auf diesen Märkten gemessen nicht vorhersagbar. Kein Filter, kein
Modell, kein Ausgang ändert das, weil alle auf derselben Information sitzen:
öffentliche Kerzen.

## 3. Was ein Durchbruch strukturell braucht

Ein Durchbruch ist eine **andere Ertragsquelle**, nicht ein weiterer Parameter.
Drei Dinge müssen zusammenkommen, und heute fehlt jedes davon:

### 3.1 Eine Quelle, bei der jemand anderes zahlt — und zwar messbar, warum

| Quelle | Wer zahlt | Evidenz hier | Was fehlt |
|---|---|---|---|
| **Market Making BTC auf Lighter** | Taker zahlen den Spread | E23: Maker behalten +4,47 bp/Tag auf Nominal, 79 % Handwerk, 974'938 Geschäfte in 24 h | Füllquote 2,88 % (E20), keine Beständigkeit der Gewinner (E23b), Latenz |
| Funding-Carry | Longs zahlen Shorts | E6: positiv bis Nov 2024, dann Replikation mit Vorzeichenwechsel | ein Regime, das zurückkommt; nur beobachten, nicht bauen |
| Querschnitt / Relative Value | Konvergenz | E4V, E4W: Maut 7,2 bp/Tag gegen 5,2 bp/Tag Signal | ein Signal, das die Maut übersteigt — nicht gefunden |
| Orderflow / Liquidationen | Zwangsverkäufer | E5 blockiert: kein Streaming-Sammler, nur Polling | Infrastruktur (P19), dann eine Vorregistrierung mit Schranke |
| Cross-Venue-Arbitrage | Preisabweichung | nie gemessen; Lighter-Preise sind centgenau (WS) | zwei Venues mit Kapital, Sub-Sekunden-Ausführung |
| Optionen / Vol-Prämie | Käufer von Konvexität | keine Daten, keine Venue im Projekt | alles |

**Die einzige Zeile mit einem gemessenen positiven Ertrag für irgendjemanden
ist Market Making auf BTC.** Sie hat zwei bezifferte Hürden. Grössenordnung,
falls beide fielen: +4,47 bp je Tag auf das gehandelte Nominal. Bei einem
Umschlag von 5× Kapital am Tag sind das +0,22 %/Tag ≈ +50 % im Halbjahr,
bei 20× ≈ +400 % — **vor** Füllquote und vor Beständigkeit. Das ist die
Grössenordnung, in der ein Durchbruch läge, und sie kommt nicht aus
Richtungswetten.

### 3.2 Information oder Geschwindigkeit, die andere nicht haben

Das System liest öffentliche Kerzen, die jeder liest, mit Verzögerung. Gegen
wen soll es gewinnen? Ein Durchbruch braucht eine von zwei Sachen:

- **Ein Buch in Echtzeit** (L2 und Trade-Tape, Streaming statt Polling) auf
  mindestens einer Venue. Der Lighter-Sammler ist der Anfang (läuft seit
  20.10., `-tape`, `-ws`). Er muss eine Woche durchlaufen, bevor E23b eine
  Beständigkeit auflösen kann.
- **Eine eigene Ausführungsmessung** (E0): nicht „was ein Maker verdient",
  sondern „was WIR gefüllt bekommen". Das geht nur mit echten, winzigen
  Orders auf einem Unterkonto — Grössenordnung 100 USD, Verlust begrenzt,
  Erkenntnis unbegrenzt. Papier kann diese Frage nicht beantworten
  (`the-maker-assumption-costs-more-than-the-maker-fee`).

### 3.3 Kapital, das zur Quelle passt

Mit 1'000 CHF binden drei Dinge: der Kostendeckel (bei engen Stops frisst
die Gebühr den Risikobetrag), die Mindestgrössen (1'000 USD übersteigen bei
manchen Märkten den ganzen Antritt, P28) und die Margin (bei 30 % × 7 passen
drei Positionen). Market Making braucht Umschlag, nicht Hebel; Carry braucht
Grösse; Arbitrage braucht zwei gefüllte Konten. **Die Zielgrösse 20× ist
vom Kapital her die falsche Frage — die richtige ist: welche Quelle trägt bei
diesem Kapital überhaupt eine positive Zahl?**

## 4. Was ich konkret brauche, in Reihenfolge

1. **Eine Entscheidung über die Zielgrösse.** 20× in sechs Monaten ist mit
   jeder gemessenen Verteilung ausserhalb des Intervalls. Ein ehrliches Ziel
   für ein System, das einen Vorteil von +0,10 R *belegt* hätte, wäre 2–3×
   im Halbjahr. Ohne belegten Vorteil ist das ehrliche Ziel: **Kapital
   erhalten, bis eine Messung positiv ist.**
2. **Die Entscheidung, die Familie zu wechseln**, sobald E24 gefallen ist.
   Das Register sieht das so vor („on_failure: Register schliesst sie
   endgültig"). Jede weitere Woche in Parametern dieser Familie ist gemessen
   verloren.
3. **Eine Woche Lighter-Tape** (läuft, kostet nur Zeit) und danach E23b
   erneut: bleiben dieselben BTC-Maker über Hälften gewinnend? Das
   unterscheidet ein Geschäftsmodell von Glück. Auflösungsgrenze sinkt unter
   |ρ| 0,1, wenn mehrere hundert Konten 30+ Geschäfte je Hälfte haben.
4. **Ein Unterkonto mit ~100 USD echtem Geld und API-Schlüssel** für E0: die
   eigene Füllquote am Touch, die eigene adverse Selektion, die eigene
   Storno-Latenz. Vorab registriert, Kill-Switch, Verlustdeckel 100 USD.
   Ohne diese Messung bleibt Market Making ein Satz über andere.
5. **Ein Streaming-Sammler** für mindestens eine Venue (P19), damit
   Orderflow- und Liquidationsfragen überhaupt messbar werden.
6. **Zeit und Nüchternheit.** Ein Vorteil von +0,10 R ist im Vorwärtslauf
   erst nach 13 Monaten nachweisbar. Wer schneller „sieht", dass es
   funktioniert, sieht Rauschen — das haben die 54 Live-Trades heute
   nochmals gezeigt (`the-live-patterns-are-not-in-the-replay`).

## 5. Was ich NICHT brauche — und was ich nicht tun werde

- Keinen weiteren Indikator, kein weiteres Modell auf Kerzen, keine
  „Konfluenz-Bewertung". Gemessen: trennt nichts.
- Keine Positionsgrösse, keinen Hebel, keine Kurvenregel als Hebel für den
  Ertrag. R ist grössenunabhängig; Grösse skaliert Verlust und Gewinn gleich.
- Kein echtes Geld in die laufende Familie. Nicht bei einem Intervall, das
  die Null enthält.
- Keine Behauptung „praktisch nur noch gewinnen". Die beste je gemessene
  Zelle hat 47,1 % Treffer; bei fester Auszahlung bräuchte 20× 66,75 %.

## 6a. Entscheidung des Eigentümers, 21.10.

Die Vorgabe 20x in sechs Monaten **bleibt bestehen**. Damit ist Punkt 1 oben entschieden, und zwar gegen die Empfehlung. Was daraus folgt: das Register prüft jeden Arm gegen +0,4536 R, und der einzige Pfad mit einer positiven Messung — Market Making BTC auf Lighter — wird als E25 (Beständigkeit) und danach E0 (eigene Füllmessung) verfolgt. Fällt E25, hat die Vorgabe keinen Pfad mehr, und das wird dann so gesagt.

## 6. Das ehrliche Urteil

Der Durchbruch, falls es ihn gibt, liegt **nicht in diesem Code**. Er liegt in
einer Ertragsquelle, bei der ein Gegenüber messbar zahlt, mit einer
Infrastruktur, die schneller ist als Polling, und mit einer Messung an echten,
winzigen Orders. Alles drei ist baubar; keines ist gebaut. Der einzige Ort,
an dem dieses Projekt je eine positive Zahl für irgendjemanden gemessen hat,
ist das BTC-Buch auf Lighter — und dort stehen zwei bezifferte Hürden, die
mit einer Woche Daten und 100 USD Risiko beantwortbar sind.

Das ist der Plan. Er verspricht nichts, und das ist seine Stärke.

## Verwandt

[[📊 Evidenzstand]] · [[🧪 Experimentregister]] · [[🔬 E23 — Lighter Maker-P&L, beobachtet statt geschätzt]] ·
[[💸 Verlustanalyse Plankonto — 21.10.2026]] · [[📌 Aktueller Stand]] ·
Repo: `audit/CHATGPT_BRIEFING_04_WAS_FEHLT_FUER_20X.md`, `audit/PROBLEMBERICHT_20X.md`, `audit/E23_LIGHTER_MAKER_PNL.md`, `audit/BLINDFLECK_AUDIT_18OKT.md`
