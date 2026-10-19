# Briefing 04 für ChatGPT — was genau fehlt für 20x in sechs Monaten

*Stand 19.10.2026. Zum Kopieren in ChatGPT. Alle Zahlen sind gemessen, die
Befehle stehen im Repo.*

---

## Deine Rolle

Du bist unabhängiger Prüfer. Ich (Claude) habe seit Wochen an diesem System
gemessen und komme zu dem Schluss, dass das Ziel mit dem vorhandenen Signal
nicht erreichbar ist. **Bestätige das nicht aus Höflichkeit.** Ich suche
genau zwei Dinge:

1. **Einen Rechen- oder Denkfehler in der Schranke unten.** Beim letzten Mal
   hast du einen gefunden, der das Ergebnis um den Faktor 16 verschoben hat.
2. **Eine Mechanismusklasse, die wir nicht getestet haben** — kein anderer
   Parameter einer getesteten Familie, sondern eine andere Ertragsquelle.

Wenn du keines von beiden findest, sag das klar. Eine Bestätigung ist ein
gültiges Ergebnis, aber nur als Ergebnis einer Prüfung, nicht als Gefallen.

---

## 1. Das System in fünf Sätzen

Krypto-Perpetuals, zwölf Märkte (BTC, ETH, SOL, XRP, ADA, AVAX, LINK, DOGE,
BNB, LTC, DOT, ATOM), Binance USD-M. Fünf regelbasierte Setups lesen
Multi-Timeframe-Struktur (W1/D1/H4/H1/M15) und schlagen Einstieg, Stop und
Ziel vor. Eine Risikoschicht mit fünf Ablehnungsregeln entscheidet, ob daraus
ein Trade wird. Ausgeführt wird nur auf Papier; es ist nie echtes Geld
geflossen. Die Auswertungspopulation sind **7.335 nachgespielte Trades** über
2.076 Tage und zwölf Märkte.

**Das Ziel des Auftraggebers:** aus 1.000 CHF sollen in sechs Monaten 20.000
werden (Faktor 20). Grössenregel ausdrücklich gewünscht: 30 % des Kontos als
Margin bei 7x Hebel, aufstockend (fixed-fractional).

---

## 2. Was gemessen ist

| Grösse | Wert |
|---|---|
| Erwartung je Trade | **−0,0129 R**, 95 % **[−0,0513, +0,0254]** |
| Streuung der R-Vielfachen | SD = **1,3877 R** |
| Stichprobe | 7.335 Trades, 12 Märkte, 2.076 Tage |
| Intervallmethode | Bootstrap, **nach Markt geclustert** (4.000 Ziehungen) |
| Haltedauer | Mittel **33,00 h**, Median 6,67 h |
| Trades in 182 Tagen (mit Margin-Buchhaltung) | **312**, also 1,7/Tag |

Das Intervall **schliesst null ein**. Es gibt also keine belegte Kante,
weder positiv noch negativ.

**Methodik, die bei uns gilt** (bitte darauf prüfen, ob ich sie eingehalten
habe): ein Arm gilt nur als bestätigt, wenn (a) das Bonferroni-korrigierte
Intervall (73 Vergleiche) die Null ausschliesst UND (b) die Replikation
zwischen 0,5x und 2,0x liegt. Die operative Halbbreite ist 0,0649 R.

---

## 3. Die Schranke — PRÜFE DIESE RECHNUNG ZUERST

Bei fixed-fractional Sizing wächst das Konto je Trade um `(1 + f·R)`, wobei
`f` der Anteil des Kontos ist, den **ein R** bewegt. Der erwartete Logertrag
je Trade ist näherungsweise

```
g(f) = f·EV − ½·f²·SD²
```

Für Faktor 20 über N Trades braucht es `N·g(f) = ln(20) = 2,9957`.

Nach `f` minimiert (also an der GÜNSTIGSTEN Stelle, nicht an einer zufällig
gewählten):

```
f*      = sqrt( 2·ln20 / (N·SD²) )
EV_min  = SD · sqrt( 2·ln20 / N )
```

Daraus die Grenzkurve:

| N (Trades/182 Tage) | je Tag | bestes f | **nötiges EV** | über der oberen Intervallgrenze |
|---|---|---|---|---|
| 312 *(heute)* | 1,7 | 0,0999 | **+0,1923 R** | **7,6x** |
| 662 | 3,6 | 0,0686 | +0,1320 R | 5,2x |
| 3.000 | 16,5 | 0,0322 | +0,0620 R | 2,4x |
| 10.000 | 54,9 | 0,0176 | +0,0340 R | 1,3x |
| **17.840** | **98** | 0,0132 | **+0,0254 R** | **1,0x** |

Umgestellt: damit die **optimistischste** vom Intervall zugelassene Kante
(+0,0254 R) reicht, braucht es

```
N = 2·ln20·SD² / EV²  =  17.840 Trades in 182 Tagen  =  98 je Tag
```

also **Faktor 57** gegenüber heute.

**Fragen an dich zu Abschnitt 3:**

* Ist `g(f) = f·EV − ½f²·SD²` hier die richtige Näherung, oder unterschätzt
  sie bei f ≈ 0,10 und SD = 1,39 den höheren Term so stark, dass die
  Schranke falsch ist? Wir haben R-Vielfache mit linkem Rand bei etwa −1
  (Stop) und rechtem Rand offen — also schief, nicht normal.
* Ist es zulässig, über f zu minimieren und das Ergebnis als untere Schranke
  für die nötige Kante zu lesen? Oder übersehe ich eine Nebenbedingung, die
  f nach oben begrenzt und die Schranke damit noch höher legt?
* Die Fenster, aus denen ich die Verteilung unten ziehe, überlappen. Ich
  behaupte, das macht die Spannweite eher zu **eng**. Stimmt das?

---

## 4. Die Kopplung, die den Durchsatz-Ausweg verschliesst

Der Durchsatz ist nicht frei wählbar. Zwei Bindungen:

**(a) Das Kostentor.** Rundenkosten dürfen höchstens 8 % des Risikos
ausmachen. Das reduziert sich exakt auf eine **Mindest-Stopweite**:

```
Stopweite ≥ c / max_cost_fraction
c = maker + taker + Schlupf = 0,02 % + 0,05 % + 0,03 % = 0,100 %
→ Stopweite ≥ 1,2500 %
```

Dieses Tor lehnt **48 % aller Signale** ab. Es ist also die bindendste Regel
im System.

**(b) Little.** `Durchsatz = Plätze / Haltedauer`. Bei 30 % Margin je
Position passen nur **drei** Positionen ins Konto (die vierte findet keine
Margin). Daraus:

| Trades/Tag | erzwungene mittlere Haltedauer (3 Plätze) |
|---|---|
| 1,7 *(heute)* | 42,4 h |
| 16,5 | 4,4 h |
| 98 *(nötig)* | **44 Minuten** |

Gemessen sind **33 Stunden**. Der nötige Durchsatz verlangt also eine 45-fach
kürzere Haltedauer — **bei unverändert ≥ 1,25 % Stopweite**. Ein Trade müsste
im Mittel in 44 Minuten eine Bewegung von mindestens 1,25 % auflösen.

**Fragen an dich zu Abschnitt 4:**

* Ist das wirklich eine Bindung, oder rechne ich Little falsch? Ich nehme den
  MITTELWERT der Haltedauer (33,00 h), nicht den Median (6,67 h) — eine
  frühere Version nahm den Median und war damit um den Faktor 5 zu
  optimistisch.
* Gibt es Marktregime oder Instrumente, in denen 1,25 % in 44 Minuten der
  Normalfall ist, ohne dass die Gebühren proportional steigen? (Wir zahlen
  Binance USD-M VIP0: Maker 0,02 %, Taker 0,05 %.)
* Ist die Schlussfolgerung „Durchsatz und Kostentor sind gekoppelt, also ist
  die Durchsatzachse nicht frei" korrekt, oder gibt es einen Weg, beide
  gleichzeitig zu bedienen?

---

## 5. Was bereits geschlossen ist — bitte NICHT erneut vorschlagen

Jeder Punkt wurde gemessen, nicht vermutet. Wo ein Intervall steht, schliesst
es null ein oder liegt auf der falschen Seite.

**Einstiege und Signal**
* Die Einstiege tragen **keine Kante**: die Brutto-Erwartung ist ~null, der
  Verlust ist praktisch vollständig Gebühren.
* Ein Vorwärts-Score über **35 Merkmale in zwei Familien** rangiert BTCs
  nächste 5–10 h mit Korrelation **0,004**.
* **19 Kandidaten über acht Datenfamilien** wurden getestet, alle 19 fielen —
  drei unabhängige Suchprogramme, dasselbe Null.
* Hit-Rate ist ein irreführendes Ziel: zwei Messungen fanden Populationen mit
  HÖHERER Trefferquote, die WENIGER verdienen.

**Ausstiege und Give-back**
* Der durchschnittliche Trade erreicht **+1,1840 R** und endet bei
  **−0,0129 R**; 62,9 % berühren ihr Ziel nie.
* Zwei registrierte Arme auf genau dieses Problem (E14, E15) sind **beide
  gefallen**, sechs von sechs Teilarmen. Ein Breakeven-Stop halbiert die
  Voll-R-Verluste und macht das Ergebnis **monoton schlechter**.
* Ein schlusskursbestätigter Stop (E10) verbesserte den Mittelwert und
  **verdreifachte den schlimmsten Verlust**.

**Kosten und Ausführung**
* Die ganze Kostenachse ist **+0,029 R** wert. Die Null-Gebühren-Schranke
  liegt bei **+0,0164 R [−0,016, +0,048]** — Intervall schliesst null ein.
* Freqtrade bestätigt unabhängig über 15.624 Trades: die Einstiegskante ist
  **3,8x kleiner** als ein Maker/Maker-Roundtrip.

**Grösse, Hebel, Kurvenregeln**
* Sieben Kurvenregeln geprüft, **keine** erfüllte das vorher festgelegte
  Kriterium. „Nicht handeln" (1,0000x) schlägt jede handelnde Regel.
* Bei der gemessenen Erwartung sind **beide** Terme von `g(f)` negativ. Es
  gibt kein f > 0, das die Summe positiv macht.
* Das System ist **gehebeltes Beta**: Beta 1,0 zu BTC, Residuum verlässlich
  negativ.

**Querschnitt und Carry**
* Der Toll (7,2 bp täglich) übersteigt das Querschnittssignal (5,2 bp/Tag) —
  Reversion UND Momentum verlieren beide.
* Funding-Carry bestand ein Intervall bei 180 Tagen Haltedauer, **fiel dann
  in der Replikation mit Vorzeichenwechsel**; das ganze positive Ergebnis
  liegt vor November 2024.

**Der einzige positive Kandidat**
* Setup A auf D1+H4: **+0,0856 R** in-sample, nach realistischerer Ausführung
  ~+0,0728 R. Das ist **in-sample** und noch nicht out-of-sample bestätigt.
  Selbst wenn es hält, ist es 2,2x unter der Schranke von +0,1923 R.

**Auflösungsgrenze des Prüfstands:** 0,077 R. Die Schranke (+0,1923 R) liegt
deutlich DARÜBER, Messauflösung ist also nicht der Engpass.

---

## 6. Was die Simulation über sechs Monate sagt

Über alle 64 Fenster von 182 Tagen in den Daten, mit Margin-Buchhaltung,
30 % × 7x, Start 1.000:

| | günstige Lesart | strenge Lesart |
|---|---|---|
| schlechtestes | 9 | 4 |
| unteres Viertel | 63 | 10 |
| **Mitte** | **150** | **87** |
| oberes Viertel | 377 | 275 |
| **bestes überhaupt** | **2.223** | 1.038 |
| über dem Start | 10,9 % | 1,6 % |
| **20.000 erreicht** | **0 von 64** | **0 von 64** |
| mehr als 90 % verloren | 39,1 % | 53,1 % |

(Die beiden Lesarten unterscheiden sich darin, ob ein Trade, dessen Stop
jenseits der Liquidation liegt, auch als Gewinner liquidiert wird. Die Daten
führen keine ungünstigste Zwischenbewegung, deshalb zwei Ränder statt einer
geratenen Zahl.)

---

## 7. Die Fragen, auf die es ankommt

**A. Ist die Schranke richtig?** Abschnitt 3. Wenn `EV_min = SD·√(2·ln20/N)`
falsch ist, ändert sich alles andere. Rechne sie nach.

**B. Gibt es eine Mechanismusklasse, die wir nicht geprüft haben?** Kein
weiterer Parameter einer Familie aus Abschnitt 5, sondern eine andere
Ertragsquelle. Wenn du eine nennst, nenne bitte dazu:
  * woraus der Ertrag kommen soll (wer zahlt ihn, und warum),
  * eine Grössenordnung, und ob sie die Schranke aus Abschnitt 3 erreicht,
  * woran man sie in sechs Monaten widerlegen könnte.
Eine Idee, die nicht widerlegbar ist, hilft uns nicht.

**C. Ist der Durchsatz-Ausweg real oder durch Abschnitt 4 verschlossen?**
57x mehr Trades bei 1,25 % Mindest-Stopweite und 44 Minuten Haltedauer — geht
das bei diesen Gebühren, und wenn ja, wäre das noch dasselbe System oder ein
anderes, das neu validiert werden müsste?

**D. Ist die Zielgrösse das, was revidiert gehört?** Wenn die Antwort auf
A–C „nein" lautet: welcher Faktor über sechs Monate wäre mit der gemessenen
Verteilung ein ehrliches Ziel, und mit welcher Wahrscheinlichkeit?

---

## 8. Was du nicht tun sollst

* Keine Parameter einer gefallenen Familie neu vorschlagen.
* Keine Idee ohne Grössenordnung — „probiert mal Machine Learning" ist keine
  Antwort, wenn die Schranke +0,1923 R verlangt.
* Nicht optimistisch sein, um nett zu sein. Der Auftraggeber trifft auf
  Grundlage dieser Antwort eine Entscheidung über echtes Geld.
* Nichts behaupten, was du nicht aus den Zahlen oben oder aus Literatur
  belegen kannst — und wenn aus Literatur, dann mit der Grössenordnung dort
  und dem Hinweis, ob sie nach Kosten gemessen wurde.

---

# NACHTRAG 19.10.2026 — was die Nachprüfung geändert hat

ChatGPT hat drei Punkte benannt. Alle drei wurden gemessen, jeder Befund
anschliessend adversarisch gegengeprüft, und die beiden tragenden Zahlen habe
ich danach selbst reproduziert. **Zwei der drei Punkte korrigieren das
Briefing — und beide zu Gunsten des Systems.**

## Punkt 1 (Näherung bei f ≈ 0,10) — beantwortet, günstig

Die quadratische Näherung war **pessimistisch**, nicht optimistisch. Exakt über
die empirische Verteilung gerechnet (`max_f E[ln(1+f·R)]`, Schiefe +0,7706,
Exzess −0,7200):

| N | Näherung | exakt | Differenz |
|---|---|---|---|
| 312 | +0,1923 R | **+0,1851 R** | −3,8 % |
| 662 | +0,1320 R | +0,1287 R | −2,5 % |
| 3.000 | +0,0620 R | +0,0613 R | −1,2 % |
| 17.840 | +0,0254 R | +0,0253 R | −0,5 % |

Die Schranke im Briefing war also um 3,8 % zu hoch angesetzt. **Ruin tritt ab
f > 0,5290 ein** (schlechtester Trade −1,8905 R); das f-Optimum bei N=312
liegt mit ~0,10 weit darunter.

## Punkt 2 (die obere Intervallgrenze) — der eigentliche Fehler

Die **+0,0254 R waren gleich zweifach zu niedrig**:

1. **Zu wenige Ziehungen.** Mit 4.000 Ziehungen kommt +0,0254, mit 20.000
   **+0,0262**. Die Zahl war ein Ziehungsartefakt.
2. **Die falsche Clusterung.** Nach MARKT zu clustern erfasst die Abhängigkeit
   nicht: gemessen trägt ein gemeinsamer **Wochenfaktor** 96,9 % der Struktur
   (Intervall schliesst null aus, 8,9 SD über der Permutationsnull). Gegen
   bekannte Wahrheit kalibriert erfasst Markt-Clustering nur **0,682** der
   echten Streuung, Zeitblöcke 0,821, Zwei-Wege-Clusterung 0,914.

Zwei-Wege-Clusterung nach Cameron/Gelbach/Miller (`V = V_markt + V_zeit −
V_schnitt`), selbst nachgerechnet:

| Blocklänge | SE | obere Grenze |
|---|---|---|
| 7 Tage | 0,02631 | **+0,0387** |
| 14 Tage | 0,02537 | +0,0368 |
| 30 Tage | 0,02491 | +0,0359 |
| 90 Tage | 0,02273 | +0,0316 |

**Die 7-Tage-Wahl ist die weiteste des Gitters, also eine Auswahl.** Der
Gittermedian liegt bei ~+0,0363.

## Die korrigierte Antwort

| Methode | obere Grenze | Faktor zur Schranke | nötige Trades/182 T | je Tag |
|---|---|---|---|---|
| Markt-Cluster *(Briefing)* | +0,0262 | 7,06 | 16.642 | 91,4 |
| Zeitblock 7 T | +0,0337 | 5,49 | 10.030 | 55,1 |
| Zwei-Wege, Gittermedian | +0,0363 | 5,10 | 8.637 | 47,5 |
| **Zwei-Wege, 7 T** | **+0,0387** | **4,78** | **7.592** | **41,7** |

Gemessener Durchsatz: **3,533/Tag** unbeschränkt (7.335 / 2.075,9 Tage),
**1,714/Tag** mit der Margin-Grenze des Plankontos. Der nötige Durchsatz ist
also Faktor **11,8 bis 25,9** über dem unbeschränkten System.

## Punkt 3 (Belegung) — geht anders aus als vermutet

Die 44-Minuten-Schranke war **zu locker, nicht zu streng**. `λ ≤ L/W ≤
Plätze/W` gilt für jede Belegung; Dauerbelegung ist der **günstigste** Fall,
keine nötige Annahme. Bei L < Plätze sinkt der mögliche Durchsatz weiter.

Dazu zwei Korrekturen an der Belegungsmessung selbst:
* Die zwölf Replay-Läufe sind **unabhängige Einzelmarkt-Läufe ohne
  Portfoliodeckel**. „L = 4,86" ist der Anteil der Zeit, in der mindestens k
  von 12 Märkten offen sind — **nicht** die Belegung eines gemeinsamen Kontos.
* Dass nie zwei Positionen im selben Markt offen sind, ist eine
  **Architektur-Invariante** (`sim/broker.py:354`, `:488`), kein Messergebnis.
  Der Schattenpfad zeigt für BTCUSDT **930 Signale ohne jeden
  Ablehnungsgrund**, die nur am besetzten Platz scheiterten — gegen 555
  genommene Trades im selben Lauf.

## Punkt 4 (überlappende Fenster) — mein Satz fällt

„Die Spannweite ist darum eher zu eng als zu weit" ist **nicht haltbar**. Die
genaue Antwort ist schärfer als ChatGPTs Einwand: die Frage ist bei dieser
Auflösung **in keine Richtung entscheidbar**. min-max wächst monoton mit der
Zahl der Fenster (n=11: 1,27; n=63: 2,41; n=1894: 7,22) und schätzt daher
nichts — es zählt, wie oft man hingesehen hat. Gegen die Wahrheit aller 1.894
möglichen Tagesstarts gemessen verfehlt der **nicht**-überlappende Entwurf die
Spannweite stärker (−0,0872) als der überlappende (−0,0150).

## Was sich NICHT geändert hat

Das Fazit. Es fehlt Faktor **4,8 bis 7,1** je nach Methode statt 7,6 — und die
Durchsatzachse ist durch Punkt 3 eher enger geworden, nicht weiter. Keiner der
124 eingetragenen Arme erreicht die Schranke: 12 schliessen die Null aus, und
**alle zwölf sind negativ**.
