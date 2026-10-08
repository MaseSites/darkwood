# E8 — Alpha oder Beta: das System *ist* die Marktrichtung, gehebelt

Reproduktion:

```bash
python scripts/study_beta_alpha.py
```

Angemeldet in `audit/EXPERIMENTS_NEXT.yaml` als Arm E8 am 08.10.2026, vor dem
ersten Lauf. `total_comparisons` dabei von 46 auf 48 erhöht, Niveau also
99.8958 %.

---

## 1. Warum die Frage gestellt werden musste

Der Vorwärtslauf stand nach 14 Trades bei **+0.8023 R je Trade** — die erste
positive Vorwärtszahl dieses Projekts. Im selben Fenster fiel LINK 13.4 %,
DOGE 12.2 %, ADA 6.0 %, BTC 4.4 %. Und nach Seite aufgeteilt:

| Seite | n | Mittel | netto |
|---|---|---|---|
| short | 10 | **+1.0598 R** | +71.32 |
| long | 4 | +0.1586 R | −0.83 |

Beide Seiten wurden gehandelt. Verdient hat nur die, die zur Marktrichtung
passte. Damit stehen zwei Erklärungen auf derselben Zahl, und sie führen zu
entgegengesetzten Entscheidungen: entweder wählt das System die Richtung, oder
es war überwiegend short in einer Abwärtswoche.

> **Eine Zählung, die ich vorher falsch hatte.** Mein erster Durchgang meldete
> „14 von 14 short". Er las `payload["side"]` — ein Schlüssel, den es nicht
> gibt; die Seite steht in `payload["reason"]["side"]`. Jeder Trade kam als
> short zurück, weil `.get()` für jeden None liefert. Die korrigierte Zahl
> stützt dieselbe Schlussfolgerung **stärker**: ein System, das nur short war,
> hätte die Frage offen gelassen. Eines, das beide Seiten nahm und nur auf der
> Marktseite verdiente, hat sie fast schon beantwortet.

## 2. Die Zerlegung

Je Trade, nicht in Eimern nach Regime. Für jeden Trade die BTC-Rendite über
**sein** Haltefenster, mit dem Vorzeichen der Trade-Seite versehen und durch
die Stop-Weite geteilt — damit steht sie in derselben Einheit wie das
Ergebnis, nämlich R:

```
r_multiple  ~  a  +  b · (seite · btc_rendite / stop_anteil)
```

`b` ist das Beta des Trades zum Kryptomarkt. `a` ist, was übrig bleibt, wenn
die Marktbewegung erklärt ist.

**Gegen BTC und nicht gegen das eigene Symbol**, weil die Frage gegen das
eigene Symbol fast tautologisch ist: wer short ist und dessen Symbol fällt,
gewinnt. Gegen BTC gerechnet ist der Rest genau die Auswahlleistung — „dieses
Symbol fiel mehr, als sein Beta zu BTC erwarten liess, und wir waren auf der
richtigen Seite".

Die Stop-Weite steht nicht im Journal und wird zurückgerechnet:
`risk_amount = qty · |entry − stop|`, also `stop_anteil = risk / (qty · entry)`.

## 3. Die Mechanik stimmt

Bevor die Zahl zählt, muss das Skript eine bekannte Antwort treffen. Gegen das
**eigene** Symbol gerechnet muss `b` nahe 1 liegen:

| | a | b |
|---|---|---|
| alle Trades, eigenes Symbol | −0.0505 R [−0.0868, −0.0113] | **+0.874** [+0.767, +0.950] |

0.874 statt 1.000, und der Rest ist −0.05 R. Das ist nicht Rauschen, das ist
die Maut plus der Pfad: ein Trade bekommt sieben Achtel der Bewegung seines
Symbols und zahlt ein Zwanzigstel R dafür. Die Mechanik ist damit geprüft.

## 4. Die beiden angemeldeten Zellen

| Zelle | n | a (Rest in R) | b (Beta) | Null aus |
|---|---|---|---|---|
| **E8.1** alle Journal-Trades | 2 748 | **−0.0823** [−0.1414, −0.0119] | **+0.985** [+0.873, +1.105] | **JA** |
| **E8.2** nur Live, vorwärts | 14 | **+0.0048** | **+1.788** | kein Intervall |

**E8.1: das Beta ist eins.** Ein Trade bewegt sich eins zu eins mit BTC, und
das Intervall [+0.873, +1.105] schliesst nichts anderes zu. Was daneben liegt,
ist **zuverlässig negativ**: −0.0823 R je Trade, Intervall ohne Null auf dem
korrigierten Niveau.

**E8.2: der Rest ist null.** Die +0.8023 R des Vorwärtslaufs sind ein Beta von
**1.79** auf einen fallenden Markt. Daneben: **+0.0048 R**. Nicht negativ,
nicht positiv — nichts.

Kein Intervall, weil 14 Trades unter der Grenze liegen. Das war vorab
festgelegt und ist kein Grund, das Niveau nachträglich zu senken.

## 5. Tor 2: die Replikation

| Fenster | n | a | b |
|---|---|---|---|
| Entwicklung 2025-10-01 … 2026-03-31 | 323 | −0.0560 [−0.1914, +0.1028] | +1.096 |
| Bestätigung 2026-04-01 … 2026-10-06 | 282 | −0.1321 [−0.2762, +0.0125] | +1.115 |

**Verhältnis +2.36× — ausserhalb des Bandes 0.5–2.0×.**

Ehrlich gelesen: das **Vorzeichen** repliziert, in beiden Fenstern negativ,
und das Beta repliziert eng (1.096 gegen 1.115). Die **Grösse** repliziert
nicht — der Rest ist im zweiten Fenster mehr als doppelt so negativ.

Und das Tor bleibt stehen, auch wenn das Ergebnis negativ ist. Hätte hier ein
positives `a` mit 2.36× Streuung gestanden, wäre es abgelehnt worden; ein
negatives darf nicht mit derselben Streuung als gesichert gelten. **Was E8
belegt, ist die Abwesenheit eines positiven Rests, nicht die genaue Grösse
eines negativen.**

## 6. Was das für das Ziel heisst

Vorab festgelegt stand da: *ein positives `b` bei einem Achsenabschnitt,
dessen Intervall die Null enthält, heisst gehebelte Marktposition ohne eigenen
Beitrag — und ist für diesen Arm ein negatives Ergebnis.* Genau das steht
jetzt da, auf beiden Stichproben.

Damit ist die Zahl, die vor zwei Tagen wie der erste Erfolg aussah, erklärt,
und sie ist kein Erfolg:

* **Die 44 Trades bis zum 30.10. tragen keinen eigenen Beitrag.** Sie tragen
  1.0 bis 1.8 Einheiten Marktrichtung und eine Maut von 0.08 R je Trade.
* **Diese Maut ist rechenbar**: 44 × 0.0823 R ≈ **3.6 R**, bei 1 % Risiko je
  Trade also rund **3.6 % des Kontos**, nur dafür, dass die Marktmeinung durch
  44 Trades hindurchgeschickt wird statt durch eine Position.
* **Die einzige Grösse, die noch zählen würde, ist die Marktrichtung selbst.**
  Und die ist in diesem Projekt gemessen: 35 Merkmale in zwei Familien ordnen
  die nächsten fünf bis zehn Stunden von BTC mit Korrelation **0.004**.

Das ist die Antwort auf „finde dein System, Taktik und wie wir wirklich Geld
machen heraus", und sie ist unbequem: das System in seiner heutigen Form ist
eine Art, eine Marktmeinung teuer auszudrücken. Es hat keine eigene.

## 7. Grenzen dieser Zahlen

**Ein Benchmark, kein Index.** BTC und kein gewichteter Korb, weil ein
selbstgebauter Index eine ungeprüfte Entscheidung mehr wäre. In einem Fenster,
in dem Altcoins und BTC auseinanderlaufen, wäre `b` gegen BTC die falsche
Zerlegung.

**Die Benchmark-Reihe hatte Löcher, und sie wurden gefüllt.** Der Speicher
trug acht Lücken seit dem 01.10., weil dort nur der Papierhändler schreibt und
der holt je Zyklus nur wenige Kerzen. Vier Live-Trades fielen deshalb zuerst
aus der Rechnung — und **drei der vier waren Gewinner** (+1.45, +1.98, +2.25 R
gegen einen Verlierer mit −1.12 R). Ein Ausfall, der Gewinner bevorzugt
entfernt, ist kein zufälliger Ausfall. Nach dem Nachladen (`resume=False`,
sonst springt der Zeiger auf die neueste Kerze und die Löcher bleiben) sind
alle 14 drin, und erst diese Fassung steht oben.

**14 Vorwärts-Trades sind kein Intervall.** E8.2 ist eine Punktschätzung. Dass
sie fast exakt auf der Null liegt, ist auffällig und nicht belastbar.

**`a` ist nicht „das, was das System falsch macht".** Es ist der Rest nach
einer linearen Zerlegung gegen einen Benchmark über das jeweilige
Haltefenster. Nichtlineare Beiträge, Timing innerhalb des Fensters und
Symbolauswahl stecken teilweise in `b`, nicht in `a`.
