---
typ: aufgabenliste
projekt: traidingBrain
status: offen
aktualisiert: 2026-10-03
naechster_schritt: Punkt 1 bis 3 beantworten — die kosten je eine Minute
verwandt:
  - "[[traidingBrain]]"
  - "[[traidingBrain — Übergabe]]"
---

# Deine To-Do-Liste

Alles, was gerade an dir hängt. Jeder Punkt sagt: **was zu tun ist**, **warum**
und **was danach passiert.**

Die Reihenfolge ist nach Aufwand sortiert, nicht nach Wichtigkeit. Punkt 1 bis 3
kosten dich je eine Minute und schalten jeweils etwas frei.

---

## Erst kurz: wie das System überhaupt funktioniert

Damit die Punkte unten Sinn ergeben. Es sind vier Teile, die hintereinander
arbeiten:

**1. Daten.** Alle Kerzen von vier Märkten (BTC, ETH, SOL, XRP) auf sechs
Zeitebenen (Woche, Tag, 4 Stunden, 1 Stunde, 15 Minuten, 1 Minute), vier Jahre
zurück. Liegen als Dateien auf dem Laptop.

**2. Analyse.** Aus den Kerzen werden Dinge berechnet, die du im Chart sehen
würdest: Trend, Struktur, Zonen, Liquidität, 42 Indikatoren. Daraus entsteht die
**Bewertung von 1 bis 100** — sie sagt, *wie eindeutig* das Bild ist, nicht wie
wahrscheinlich ein Gewinn ist. 90 mit „abwärts" heisst: alle Zeichen zeigen klar
nach unten.

**3. Setups.** Deine Regeln aus den 13 Videos, als Code. Jedes Setup schaut auf
eine bestimmte Situation. Wenn es sie findet, schlägt es einen Trade vor:
Einstieg, Stop Loss, Take Profit.

| Setup | Was es sucht | Zustand |
|---|---|---|
| **A** | Liquidity Sweep, dann Strukturbruch | läuft |
| **B** | Trendlinien-Fakeout | läuft (neu seit 01.10.) |
| **C** | Supply/Demand-Retest | läuft — **verliert, siehe Punkt 4** |
| **D** | — | **gesperrt, braucht deinen Stop (Punkt 5)** |
| **E** | — | **gesperrt, braucht dein Ziel (Punkt 5)** |
| **F** | Fair-Value-Gap-Füllung | läuft |
| **G** | Session-Eröffnung | läuft |

**4. Risiko und Ausführung.** Hier wird aus dem Vorschlag eine Position:
Wie viel riskieren wir? Wie gross wird die Position? Welcher Hebel? Und:
**darf dieser Trade überhaupt stattfinden?** Mehrere Regeln können ihn ablehnen.

Das Papertrading läuft gerade ständig im Hintergrund und macht genau das —
automatisch, mit Spielgeld, ohne Börse, ohne Konto.

---

## Was „R" heisst

Es steht in fast jeder Zahl, die ich dir schicke, also hier einmal richtig.

**R ist ein Risiko** — genau der Betrag, den ein Trade verliert, wenn der Stop
greift. Bei 1 000 Franken Konto und 0,5 % Risiko pro Trade sind das **5 Franken**.

    +1.00 R   so viel gewonnen, wie riskiert wurde          +5 CHF
    −1.00 R   der Stop hat gegriffen                        −5 CHF
    +2.50 R   zweieinhalbmal den Einsatz gewonnen          +12.50 CHF

**Warum nicht einfach Franken?** Weil Franken nur auf einem Konto vergleichbar
sind. Deine ersten beiden Vorwärts-Trades:

    BTC  −1.10 R  =  −55.05 CHF    lief noch auf dem 10 000er-Konto
    BNB  +1.40 R  =   +6.99 CHF    lief auf dem 1 000er-Konto

In Franken sieht der Verlust achtmal so schwer aus wie der Gewinn. In R stimmt
das Verhältnis: einer hat ein Risiko verloren, der andere anderthalb gewonnen.
Deshalb ist die Verlaufskurve in R — sonst hätte die Umstellung des
Startkapitals eine Klippe hineingerissen, die kein Trade verursacht hat.

**Warum ein Verlust grösser als 1.00 R sein kann:** Der Stop lag bei 86 923, der
Markt ist durchgelaufen, der Ausstieg kam erst bei 86 949. Der Simulator füllt
zum tatsächlich erreichbaren Preis, nicht zum geplanten — einer, der immer
sauber am Stop füllt, meldet Verluste, die das Konto nie hatte.

---

## 1. Ist der Raspberry Pi an? ⏱ 1 Minute

### Was zu tun ist

Geh zum Pi und schau nach:

- Leuchtet eine **rote LED**? (= er hat Strom)
- Blinkt eine **grüne LED**? (= er arbeitet)
- Steckt ein **Netzwerkkabel** drin, oder soll er über WLAN gehen?

Dann sag mir, was du siehst. Falls er läuft und du an den Router kommst:
Schau in der Geräteliste nach, welche IP-Adresse er bekommen hat, und gib sie
mir durch.

### Warum

Ich habe eben das ganze Netzwerk abgesucht — alle 254 Adressen. **Kein einziges
Gerät antwortet.** Der Pi soll unter `192.168.0.62` erreichbar sein, dort ist
aber nichts, und unter den zehn Geräten, die im Netz sichtbar sind, hat keines
eine Raspberry-Pi-Adresse. Er ist also aus oder in einem anderen Netz — das ist
kein Einstellungsproblem auf meiner Seite.

### Was danach passiert

Der Pi sammelt rund um die Uhr Kursdaten, auch wenn dein Laptop aus ist. Solange
er aus ist, entstehen Lücken in der Historie, sobald der Laptop zu ist. Mit ihm
hat das System eine durchgehende Datenbasis.

---

## 2. UTC oder Schweizer Zeit? ⏱ 1 Minute

### Was zu tun ist

Antworte mir mit einem Wort: **UTC** oder **Schweiz**.

Wenn du unsicher bist: Öffne deinen Chart (TradingView o.ä.), schau auf die
aktuelle Uhrzeit unten rechts und vergleich sie mit deiner Handy-Uhr. Gleich =
Schweizer Zeit. Zwei Stunden früher (im Sommer) = UTC.

### Warum

Alles, was das System speichert, ist UTC. Als du gesagt hast „am 30. September
um 5 Uhr morgens wäre ein guter Einstieg gewesen" — habe ich die falsche Kerze
angeschaut, wenn du Schweizer Zeit meintest. Im Sommer sind das zwei Stunden
Unterschied, im Winter eine.

### Was danach passiert

Ich rechne alle Zeitangaben auf dem Dashboard in deine Zeit um, und wir reden
nie wieder über verschiedene Kerzen.

---

## 3. Risiko pro Trade: Prozent oder Franken? ⏱ 1 Minute

### Was zu tun ist

Eine von zwei Antworten:

- **„Prozent"** — dann riskiere ich immer denselben Anteil vom Konto. Wird das
  Konto kleiner, werden die Positionen automatisch kleiner.
- **„X Franken"** — dann riskiere ich immer denselben Betrag, egal wie das Konto
  steht. Sag mir die Zahl.

Zur Orientierung: aktuell sind es 0,5 % des Kontos. Bei 1 000 Franken Konto sind
das **5 Franken Risiko pro Trade**.

### Warum

Dein Guide sagt in Kapitel 23 ausdrücklich nichts über Positionsgrössen. Das ist
also keine Regel aus deinen Videos, sondern eine Entscheidung, die jemand treffen
muss — und das bist du, weil es dein Geld ist.

**Wichtig, weil es oft verwechselt wird:** Risiko ist nicht der Einsatz. Wenn du
500 Franken Position hast und der Stop 1 % entfernt liegt, verlierst du beim Stop
**5 Franken**, nicht 500. Deshalb rechnet das System rückwärts: erst Risiko, dann
Positionsgrösse, dann Hebel.

### Was danach passiert

Fester Betrag müsste ich erst bauen (gibt es noch nicht). Prozent läuft schon.

---

## 4. Setup C: abschalten oder behalten? ⏱ 10 Minuten

### Was zu tun ist

Lies die Zahlen unten, dann sag mir **„C abschalten"** oder **„C behalten"**.

### Die Zahlen

Über 2 734 simulierte Trades, vier Märkte, vier Jahre:

| Setup | Trades | Ergebnis pro Trade | Trefferquote | Sicher? |
|---|---|---|---|---|
| A | 1 061 | −0,042 R | 41 % | nein, könnte Zufall sein |
| B | 665 | −0,079 R | 32 % | nein |
| **C** | **872** | **−0,149 R** | **23 %** | **ja, verliert sicher** |
| G | 132 | −0,121 R | 30 % | nein |

„R" heisst: Vielfaches dessen, was riskiert wurde. −0,149 R bedeutet, dass jeder
Trade im Schnitt knapp 15 % des eingesetzten Risikos verliert.

Die Spalte „Sicher?" ist die wichtige. Bei A, B und G ist der Verlust so klein,
dass er auch Zufall sein könnte. **Bei C nicht** — das ist über drei unabhängige
Messungen hinweg stabil geblieben. Und die Trefferquote von 23 % ist die
niedrigste von allen.

Eine genauere Messung läuft gerade und ist heute Abend fertig: sie sagt nicht
nur, wie C selbst lief, sondern was **das ganze System ohne C** täte. Das ist die
Zahl, auf die es ankommt — wenn C wegfällt, kommen auf denselben Kerzen andere
Setups zum Zug.

### Warum du das entscheidest

Es ist dein Regelwerk aus deinen Videos. Ich kann messen und empfehlen, aber eine
deiner Regeln abzuschalten ist keine technische Entscheidung.

**Meine Empfehlung: abschalten.** Es ist der am besten belegte Einzelbefund im
ganzen Projekt.

---

## 5. Setup D und E: deine Regeln fehlen ⏱ 10 Minuten

### Was zu tun ist

Beantworte zwei Fragen in deinen eigenen Worten:

**Für Setup D:** Wo kommt der Stop Loss hin? Beispiele, wie eine Antwort aussehen
könnte:
- „unter das Tief der Signalkerze"
- „unter die Zone, minus ein bisschen Puffer"
- „1,5 × ATR unter dem Einstieg"

**Für Setup E:** Wo kommt das Take Profit hin?
- „beim nächsten Widerstand"
- „2 × das Risiko" (also bei 1 % Stop → 2 % Ziel)
- „beim vorherigen Hoch"

### Warum

In den Regelkarten aus deinen Videos steht wörtlich *„Stop Loss: für dieses
Beispiel nicht numerisch spezifiziert"* bzw. dasselbe für das Take Profit. Die
Videos erklären, **wann** man einsteigt, aber nicht **wo** man aussteigt.

Ohne diese Angabe kann ich die Setups nicht handeln lassen — ich müsste raten,
und ein geratener Stop ist meine Regel, nicht deine. Dann würde die Messung
meine Erfindung bewerten statt dein Regelwerk.

### Was danach passiert

Zwei zusätzliche Setups gehen scharf. Das sind mehr Trades pro Tag — und zwar
echte zusätzliche aus deinem Regelwerk, nicht aufgeweichte Regeln.

---

## 6. Maximale Trades pro Tag? ⏱ 2 Minuten

### Was zu tun ist

Eine Zahl, oder „kein Limit".

### Warum

Gibt es noch nicht. Gerade kein dringendes Problem — gemessen sind es 1,9 Trades
pro Tag über alle vier Märkte zusammen. Aber es gehört in die Risikoregeln,
bevor echtes Geld fliesst: ein Tag, an dem fünfzehn Setups feuern, ist ein Tag,
an dem etwas Ungewöhnliches passiert, und das ist selten der beste Moment für
fünfzehn Trades.

---

## 7. Das volljährige Börsenkonto 🔴 blockiert echtes Geld

### Was zu tun ist

Mit deinen Eltern reden. Konkret brauchst du:

1. Eine **volljährige Person**, die ein Konto bei der Börse eröffnet.
2. Diese Person muss **selbst den Bestätigungsknopf drücken** — und zwar 1,2
   Sekunden lang halten — bevor eine Order rausgeht. Das ist technisch
   erzwungen und lässt sich nicht umgehen.
3. Der API-Schlüssel bekommt **Handelsrecht, aber kein Auszahlungsrecht**.

### Warum

Börsen verlangen 18+. Das ist nicht verhandelbar, und ich baue es auch nicht um.

### Was du dabei ehrlich sagen kannst

Wir haben jetzt Zahlen statt Hoffnungen, und die sind unbequem: **in der
aktuellen Form verliert das Regelwerk Geld.** 2 734 simulierte Trades über vier
Jahre, Erwartung −0,09 R pro Trade. Das ist kein Grund aufzuhören — es ist der
Grund, warum wir mit Spielgeld traden, bis sich das ändert. Aber es ist das
Gegenteil von „die KI verdient Geld für mich", und es ist besser, wenn deine
Eltern das von dir hören als später von einem Kontoauszug.

---

## Was ich in der Zwischenzeit mache

- Startkapital auf **1 000 Franken pro Markt** (= 4 000 gesamt) statt 10 000 —
  realistischer für das, was du tatsächlich haben wirst.
- Das Dashboard bekommt mehrere Seiten: **Konto** (Stand, Geld nachlegen,
  Einstellungen), **Trades** (alle, mit Begründung und Ergebnis) und
  **Verlauf** (Kurve, wie viel Plus/Minus über die Zeit).
- Das Papertrading läuft durchgehend weiter und sammelt Fälle.
