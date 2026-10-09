# Wann weiss man es? Das Ziel prüft sich selbst — bis zum 30.10.

Reproduktion: die Rechnung steht unten vollständig; sie braucht nur `σ` aus
dem Journal und das korrigierte Niveau.

Stand 09.10.2026, 13:50 UTC. Commit `7633612`.

---

## 1. Die Frage

Der Vorwärtslauf ist die einzige Evidenzquelle, die noch wächst. Nach 18
Trades steht er bei **+0,3938 R je Trade**, Intervall über die Null. Die
naheliegende Frage ist nicht „ist er positiv", sondern:

> **Wie viele Vorwärtstrades bräuchte es, um einen echten Vorteil von der Null
> zu trennen?**

Das ist eine Mächtigkeitsrechnung, keine neue Vergleichszelle — sie liest
kein Ergebnis, sie rechnet eine Stichprobengrösse. Darum braucht sie keine
Anmeldung.

## 2. Die Rechnung

```
  n  =  ( z · σ / μ )²
```

* **σ = 1,406 R** — die Streuung je Trade, aus den **2 734 Replay-Trades**.
  Bewusst nicht aus den 18 Vorwärtstrades: achtzehn Beobachtungen schätzen
  eine Streuung schlecht, und die Replay-Streuung ist mit 1,406 gegen 1,492
  ohnehin fast dieselbe.
* **z = 3,317** — das korrigierte Niveau, Bonferroni auf 55 Vergleiche.
* **1,9 Trades/Tag** — die gemessene Vorwärtsrate.

## 3. Das Ergebnis

| nötiger Vorteil | Trades | Tage | fertig am |
|---|---|---|---|
| **+0,7280 R** ← *was das Ziel verlangt* | **41** | **22** | **30.10.2026** |
| +0,4000 R | 136 | 72 | 19.12.2026 |
| +0,2000 R | 544 | 286 | 22.07.2027 |
| +0,1000 R | 2 175 | 1 145 | 26.11.2029 |
| +0,0500 R | 8 701 | 4 580 | 23.04.2039 |

Vorhanden: **18 Trades.**

## 4. Was daran bemerkenswert ist

**Der Vorteil, den das Ziel verlangt, wäre bis zum Zieldatum nachweisbar.**
41 Trades bei 1,9 am Tag sind 22 Tage, und 22 Tage ab heute ist der
**30.10.2026** — genau der Stichtag, den das Ziel nennt.

Das ist kein hineingelesener Zufall, sondern eine Folge der Grössen: ein
Vorteil, der 1 000 CHF in sechs Monaten auf 20 000 bringt, ist so gross, dass
eine Handvoll Trades ihn zeigt. **Das Ziel prüft sich selbst.**

Daraus folgt eine Aussage, die nützlicher ist als jede weitere Simulation:

> Wenn der Vorwärtslauf bis zum 30.10. bei etwa 41 Trades **nicht** ein
> Intervall ohne Null auf der richtigen Seite zeigt, ist das Ziel nicht nur
> arithmetisch unwahrscheinlich, sondern **empirisch widerlegt** — mit der
> einzigen Evidenzart, die dieses Projekt als entscheidend anerkennt.

Und es folgt die Kehrseite, die genauso wichtig ist:

> **Der Vorwärtslauf kann nur grosse Vorteile beantworten.** Ein echter
> Vorteil von +0,10 R — der über sechs Monate aus 1 000 CHF 1 511 machen
> würde — bräuchte **2 175 Trades und bis 2029**. Ein kleiner, echter Edge
> ist auf dieser Rate nicht nachweisbar, solange das System lebt.

## 5. Was die Rechnung nicht sagt

**Sie sagt nichts darüber, ob ein Vorteil existiert.** Sie sagt, wie viele
Beobachtungen ein Vorteil **gegebener Grösse** bräuchte, um sich zu zeigen.
Die 18 vorhandenen Trades stehen bei +0,3938 R — ein Wert, der bei dieser
Streuung 136 Trades bräuchte und mit 18 nichts belegt.

**Sie unterstellt unabhängige Trades.** Vier offene Positionen gleichzeitig,
alle auf korrelierten Krypto-Perps, sind das nicht. Die effektive
Stichprobengrösse ist kleiner als die Zahl der Trades, also sind die Tage
oben eine **Untergrenze**.

**Sie unterstellt eine stabile Rate.** 1,9 Trades/Tag ist über den bisherigen
Vorwärtslauf gemessen; 87 von 106 Vorschlägen wurden von der Risk Engine
abgelehnt, und diese Quote kann sich mit dem Regime ändern.

**Und das korrigierte Niveau ist hart.** Bei einem unkorrigierten 95 %-Test
(z = 1,96) wären es 14 Trades statt 41 für die +0,7280 R. Die Korrektur ist
richtig — 55 angemeldete Vergleiche sind 55 Chancen auf einen Zufallstreffer
— aber sie verdreifacht die nötige Stichprobe.

## 6. Die praktische Folge

Es gibt **einen** Termin, an dem dieses Projekt eine Antwort hat, und er liegt
drei Wochen entfernt. Bis dahin ist die nützlichste Handlung: **den
Vorwärtslauf laufen lassen und nichts an ihm ändern.**

Jede Änderung an Strategie, Risiko oder Schwellen setzt den Zähler zurück —
nicht formal, aber inhaltlich: die Trades davor und danach gehören dann nicht
mehr zur selben Frage. Das ist der Grund, warum `run_signature` existiert.
