# Warum jeder Trade so endete — 7.335 Trades, 19.10.2026

**Auftrag:** „schaue alle verlorenen und gewonnenen trades an finde heraus
warum genau dieses ergebnis zustande gekommen ist und lerne daraus was kannst
du besser machen was kannst du weiterführen."

Gerechnet mit `scripts/study_trade_postmortem.py` über alle 7.335 Trades, zwölf
Märkte, fünf Jahre. Jeder trägt einen Nachbericht mit `max_favourable_r`,
`max_adverse_r`, `stopped_by_wick`, `never_in_profit` und den vollständigen
Entscheidungsblock.

---

## 1. Wohin das Geld geht

| | USDT | R je Trade |
|---|---|---|
| **brutto** (was die Einstiege verdienen) | **+1.473,58** | **+0,0206** |
| Gebühren | −2.043,87 | −0,0286 |
| Funding | +54,48 | +0,0008 |
| **netto** | **−515,81** | **−0,0072** |

**Die Einstiege verdienen brutto etwas.** Nur kostet der Handel mehr, als sie
verdienen: die Gebühr ist 1,39-mal so gross wie der Bruttoertrag.

*(Die −0,0072 R hier sind risikogewichtet, die bekannten −0,0129 R sind der
ungewichtete Mittelwert über Trades. Beide sind richtig; sie beantworten
„wie viel je riskiertem Franken" gegen „wie viel je Trade".)*

---

## 2. Wie die Trades endeten — die Mechanik

| Mechanismus | n | Anteil | R je Trade | R gesamt |
|---|---|---|---|---|
| Ziel erreicht | 2.684 | 36,6 % | +1,7695 | **+4.749,2** |
| **Docht holte den Stop** | **2.053** | **28,0 %** | −1,0433 | **−2.141,9** |
| nie im Plus | 1.058 | 14,4 % | −1,0465 | −1.107,2 |
| kam nie weit ins Plus | 605 | 8,2 % | −1,0433 | −631,2 |
| war ≥ 0,5 R im Plus, gab zurück | 480 | 6,5 % | −1,0443 | −501,2 |
| war ≥ 1 R im Plus, gab zurück | 452 | 6,2 % | −1,0246 | −463,1 |

**Der grösste einzelne Verlustgrund ist der Docht.** 2.053 Trades — mehr als
ein Viertel aller — wurden von einer Spitze ausgestoppt, und die Kerze schloss
danach wieder auf der richtigen Seite. Das sind −2.141,9 R, fast die Hälfte
aller Verluste.

**Und genau dieser naheliegende Hebel ist schon gemessen und gescheitert.**
E10 hat den close-bestätigten Stop getestet: er verbesserte den Mittelwert und
**verdreifachte den grössten Einzelverlust**. Der Grund ist mechanisch — wer
den Stop erst auf Schlusskurs akzeptiert, hält durch jede Spitze hindurch, auch
durch die, die weiterlaufen. Man tauscht viele kleine Dochtverluste gegen
wenige sehr grosse.

Das ist die wichtigste Lehre dieses Abschnitts: **der grösste Verlustposten ist
nicht automatisch der beste Angriffspunkt.**

---

## 3. Was Gewinner von Verlierern trennt — und was nicht

| | Gewinner | Verlierer |
|---|---|---|
| wie weit ins Plus (`max_favourable_r`) | 2,195 | 0,599 |
| wie weit ins Minus (`max_adverse_r`) | 0,383 | 1,188 |
| gehaltene Kerzen | 157,2 | 118,3 |
| **Bewertung (`rating`)** | **68,2** | **67,3** |
| Stopweite in Prozent | 2,898 | 2,966 |

**Die eigene Bewertung trennt nichts.** 68,2 gegen 67,3 — ein Unterschied von
0,9 Punkten auf einer 100er-Skala. Das ist der schärfste Befund dieser Analyse,
weil die ganze Staffelung der Positionsgrösse nach Zuversicht auf dieser Zahl
ruht. Sie weiss nicht, welcher Trade gewinnt.

Die ersten beiden Zeilen sind dagegen **keine** Erkenntnis, sondern Tautologie:
ein Gewinner ist weit ins Plus gelaufen, weil er gewonnen hat. Sie stehen hier,
damit man sie nicht für ein Merkmal hält.

Die dritte ist interessant: **Gewinner werden ein Drittel länger gehalten**
(157 gegen 118 Kerzen). Das ist kein Hebel — man weiss vorher nicht, welcher es
wird — aber es erklärt, warum ein Haltedeckel hier schadet: er schneidet
bevorzugt die Gewinner ab. Genau das wurde am 18.10. gemessen (Trades ≤12 h
liefern −0,1157 R, Trades >12 h liefern +0,1590 R).

---

## 4. Wo die Unterschiede liegen

**Zeitebene — monoton, und der einzige Gradient mit Mechanismus:**

| Ebene | n | Anteil | R je Trade |
|---|---|---|---|
| M15 | 3.604 | 49,1 % | **−0,0374** |
| H1 | 2.396 | 32,7 % | −0,0073 |
| H4 | 1.083 | 14,8 % | **+0,0429** |
| D1 | 252 | 3,4 % | **+0,0443** |

Die Hälfte aller Trades liegt auf der schlechtesten Ebene. Das deckt sich mit
dem registrierten Kandidaten „Setup A auf D1+H4" — und dessen Problem bleibt:
weniger Trades heissen eine **höhere** Marke je Trade.

**Richtung — 70 % der Trades sind short, und die Shorts verlieren:**

| | n | Anteil | R je Trade |
|---|---|---|---|
| short | 5.126 | 69,9 % | −0,0223 |
| long | 2.209 | 30,1 % | +0,0089 |

**Regime:** `trend_down` −0,0342 (42,5 %), `range` −0,0172, `trend_up` +0,0215,
`manipulation` +0,0365. Das System handelt also am häufigsten in dem Regime, in
dem es am meisten verliert.

**Bewertungsband:** `eindeutig` +0,0401, `unklar` **+0,0262**, `deutlich`
−0,0285, `gemischt` −0,0493, `Durcheinander` −0,0408. Dass „unklar" besser
abschneidet als „deutlich" ist ein weiteres Zeichen, dass die Bewertung nicht
das misst, was ihr Name verspricht.

**Setup:** A −0,0133 (48,0 %), B −0,0110 (41,4 %), G +0,0410 (5,2 %),
C −0,0892 (2,8 %), E +0,0224 (2,3 %), F −0,6322 (0,3 %).

---

## 5. Die Warnung, die zu dieser Tabelle gehört

Oben stehen über vierzig Zellen. Bei dieser Zahl ist es **Arithmetik**, dass
einige gut aussehen — das ist kein Befund. Und fast alle Unterschiede liegen
**innerhalb** der Auflösungsgrenze des Apparats (±0,0649 operativ, Bonferroni
plus Clusterung je Markt). Nur zwei Zellen überschreiten sie, und beide sind
Märkte und keine Strategieentscheidung: AVAXUSDT +0,1228 und DOTUSDT −0,1066.

Jede Zelle hier ist ein **Kandidat für eine Anmeldung**, kein Ergebnis. Dieses
Projekt hat genau diesen Fehler schon zweimal bezahlt.

---

## 6. Was ich daraus mitnehme

**Was ich besser machen kann:**

1. **Die Bewertung ist nachweislich blind** (68,2 gegen 67,3). Eine
   Positionsgrösse, die nach ihr staffelt, staffelt nach Rauschen. Wenn eine
   neue Grössenregel gebaut wird, darf sie nicht auf dieser Zahl ruhen.
2. **Der Dochtverlust ist der grösste Posten und trotzdem kein Angriffspunkt** —
   E10 hat das gemessen. Ich hätte ihn ohne diese Vorgeschichte als „die
   Lösung" vorgeschlagen.
3. **Die Zeitebene ist der einzige Gradient mit einem Mechanismus dahinter**
   (weiter Stop, längere Haltedauer, weniger Dochtkontakt). Sie ist auch der
   einzige, der schon als Arm registriert ist.

**Was ich weiterführe:**

* Die Mechanik-Tabelle aus §2 als Standardausgabe jedes Laufs — sie sagt in
  sechs Zeilen, *wie* ein Ergebnis zustande kam, und das stand bisher in keinem
  Bericht.
* Die Trennung „Tautologie gegen Merkmal" aus §3. `max_favourable_r` als
  Unterscheidungsmerkmal zu lesen wäre ein Zirkelschluss gewesen.
* Die Warnung aus §5 **als Teil der Ausgabe**, nicht als Fussnote. Sie steht im
  Skript selbst.

**Was ich NICHT tue:** aus einer dieser Zellen eine Regel machen. Der nächste
Schritt für jede davon ist eine Anmeldung in `audit/EXPERIMENTS_NEXT.yaml` mit
vorab deklarierten Rand-Kennzahlen und eine Prüfung out-of-sample.
