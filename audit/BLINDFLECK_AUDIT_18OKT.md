# Blindfleck-Audit, 18.10.2026 — welche Achse wurde nie *gestellt*?

**Methode.** Vier unabhängige Linsen, die meine Prioritäten nicht teilen, haben
`audit/` (43 Dokumente), `src/` und `config/` gelesen und gesucht, welche Grösse
in *jedem* Lauf gleich geblieben ist. Jeder Kandidat ging danach durch eine
**adversarische Prüfung** mit Ablehnung als Vorgabe: er überlebt nur, wenn er
nicht auf eine der 17 geschlossenen Achsen zurückzuführen ist **und** seine
Belegstelle stimmt. Die Prüfer mussten zusätzlich eine **Obergrenze rechnen**.

14 Kandidaten, 11 überlebt, 3 zurückgeführt. 8 Agenten, 1,17 Mio. Token, 22
Minuten, 0 Fehler.

**Die Prüfung war echt.** Ein Prüfer hat eine falsch zitierte Zeilennummer
aufgedeckt (`broker.py:636-738` existiert in keinem der beiden Dateizustände; die
Nummern waren aus Arbeitsbaum und HEAD gemischt), die Behauptung dann
*unabhängig* nachgeprüft und sie **schärfer** bestätigt als der Finder: `grep`
über die ganze `broker.py` findet `FrameAnalysis` nicht einmal als Import.

---

## Das Ergebnis in einem Satz

**Die Achsen sind nicht alle formal geschlossen — aber jede, deren Obergrenze
sich rechnen lässt, liegt unter der Anforderung.** Und die einzige mit einer
unbegrenzten Decke bräuchte eine um ~30 Prozentpunkte höhere Trefferquote, was
keine Eigenschaft des Messgitters ist.

| Kandidat | Obergrenze | gegen +0.42 R | gegen ±0.077 R |
|---|---|---|---|
| **Volumen-/Dollar-Balken statt Zeitbalken** | von keiner Arithmetik begrenzt | bräuchte +30 Pp Trefferquote | Punktwert erwartet **innerhalb** der Grenze |
| Ausstieg sieht die Struktur nie | ~+0.12 R | 3,5× zu kurz | messbar |
| `max_hold_hours` (bewegt die **Anforderung**) | +0.42 → +0.284 R | nutzbar ~0,14 R Marke | — |
| Teilausstieg / Runner (nie implementiert) | +0.028 R | Faktor 15 | **unter** der Grenze |
| Schiedsregel des Pools | ≤+0.02 R, Vorzeichen eher negativ | Faktor >20 | nicht messbar |
| `swing_lookback = 3` | +0.011 R | Faktor 38 | **Faktor 7 unter** der Grenze |
| `min_reward_risk`-Boden nie gehoben | **null** (der Finder sagt es selbst) | — | — |
| 35 Detektorkonstanten | **unbekannt**, offline nicht rechenbar | — | — |

---

## 1. Der wertvollste Fund: `max_hold_hours` war immer `None`

**Warum er anders ist als alles andere.** Er bewegt nicht den Erwartungswert,
sondern **die Anforderung**. Die Anforderung von +0.42 R folgt aus Little's Law
mit der *mittleren* Haltedauer; ein Haltedeckel senkt diese Dauer, erhöht die
Zahl der Gelegenheiten und senkt damit die nötige Kante je Trade. Der Schalter
ist implementiert, hat sechs Tests — und stand in **jedem** Lauf auf `None`.

Gerechnet: ein Deckel bei 168 h senkt die Marke auf **+0.284 R**, bei 72 h auf
+0.217 R, bei 24 h auf +0.132 R.

**Und die Prüfung hat ihn erledigt — in beide Richtungen zugleich.** Der
168-h-Deckel trifft nur 3,38 % der Trades und kostet dabei schon +81,8 R des
Pools. Der 24-h-Deckel trifft 23,4 % der Trades, und diese tragen **+398,3 R**
gegen einen Pool von −94,8 R. Die direkte Gegenmessung:

| Schnitt | darunter | darüber |
|---|---|---|
| ≤12 h | **−0.1157 R** (n=4.591) | **+0.1590 R** (n=2.744) |
| ≤24 h | −0.0877 R | +0.2322 R |
| ≤48 h | −0.0550 R | +0.2668 R |

**Der Deckel amputiert prospektiv genau die Teilpopulation, in der der gesamte
positive R liegt** — und zahlt dafür Taker zum Marktpreis. Der Prüfer nennt die
erwartete Kante nicht null sondern *wahrscheinlich negativ*, und markiert die
Schnitttabelle selbst ausdrücklich als Rückschaufalle, die nicht als Argument
*fürs Halten* gelesen werden darf.

Die eine vorhandene Messung dazu: −0.0028 R [−0.091, +0.090] auf einem Markt.

---

## 2. Ein echter Defekt: Setup A handelt einen Ausstieg, den niemand vorschreibt

`scale_out_fraction = 0.5` und `trail_atr_multiple = 2.0` sind gesetzt und
werden **von niemandem gelesen**. V08 schreibt vor: halbe Position bei 1,5 R
schliessen, Rest mit Chandelier-Trail laufen lassen. Der Broker kann keinen
Teilausstieg — ein Trade hat genau *ein* Ausstiegsereignis.

**Setup A ist 3.529 Trades, also 48,1 % der ganzen Population.** Knapp die Hälfte
des Pools handelt also eine Regel, die ihre eigene Quelle nicht vorschreibt. Das
ist eine Abweichung zwischen Strategiedefinition und Implementierung, und sie
ist eine eigene Aufgabe wert.

**Nur löst sie das Problem nicht**, und das ist unabhängig nachgerechnet. Der
Prüfer hat die Verteilung selbst gezogen (`post_mortem.max_favourable_r`,
n=7.335) und die Zahlen des Finders **auf die Dezimale** bestätigt: ≥1,5 R in
2.992 Fällen (40,79 %), ≥2,0 R in 19,63 %, ≥3,0 R in 3,30 %.

Die harte Obergrenze, die der Finder nicht gezogen hatte: der Mittelwert von
`max_favourable_r` über die 2.992 Trades, die 1,5 R erreichten, ist **2,201 R**.
Ein Runner kann nicht mehr erlösen, als der Trade je erreicht hat. Realistisch
bleiben **+0.028 R** — unter der Auflösungsgrenze. Für +0.42 R müsste das
laufende Bein im Mittel **+5,76 R** halten.

---

## 3. Der einzige Kandidat mit offener Decke — und seine ehrliche Erwartung

**Volumen- oder Dollar-Balken statt Zeitbalken.** Jede Messung dieses Projekts
liegt auf Zeitbalken: `Timeframe` ist ein `StrEnum` mit genau M1/M15/H1/H4/D1/W1,
`timeframe_ms = minutes * 60_000`, der ganze Gitterbegriff ist Zeit. Eine
Gegenprobe über `src/`, `scripts/` und `EXPERIMENTS_NEXT.yaml` nach
`renko|heikin|volume bar|dollar bar|imbalance bar|tick bar|range bar` gibt
**null Treffer**. Die eigene Grundlagennotiz nennt die Alternative wörtlich.

Er ist der einzige Kandidat, den keine Arithmetik unter +0.42 R begrenzt — weil
er die **Einstiegspopulation austauscht** statt sie umzupreisen oder
auszuwählen. Und er ist baubar: `data/ohlcv/BTCUSDT/M1/*.parquet` trägt eine
`volume`-Spalte über sechs Jahresdateien.

**Aber die Decke ist leer.** Die Auszahlung ist fest (1,50 / −1,01), heute sind
36,6 % Zielausstiege, symmetrisch bräuchte es ~66,75 % Trefferquote. Der Takt
müsste die Trefferquote um rund **30 Prozentpunkte** heben — „das ist kein
Takteffekt, das ist ein anderer Markt". Dazu zwei aggregationsinvariante
Schranken: 35 Preismerkmale bei Korrelation 0,004 bis 168 h, und Beta 1,0 zu BTC
mit verlässlich negativem Residuum.

**Erwartung des Prüfers: Punktwert innerhalb ±0.077 R, also unentschieden.
Lizenzieren ja — als Falsifikation, nicht als Rettung.**

Eine scharfe Grenze gehört ins Protokoll: ein *Imbalance*-Balken-Arm fiele unter
die toten Datenfamilien (Orderflow-Imbalance ist dort ausdrücklich als
„Umlackierung" verworfen, und `data/flow/` hält schon Taker-Volumen). Nur der
reine Volumen-/Dollar-**Takt** überlebt. Und `volume` ist Basis-Asset-Volumen,
ein Dollar-Balken also `close * volume` — ein Proxy.

---

## 4. Die Achse, auf der der Apparat die Frage nicht beantworten kann

`swing_lookback = 3` definiert, was ein Swing **ist**, und damit stromabwärts,
ob BOS/CHoCH vorliegt, wo jeder Stop und jedes Ziel landet und welche Setups
überhaupt feuern. Dazu rund 35 weitere Detektorkonstanten. **Keine davon steht
in der `run_signature`.**

Der Prüfer rechnet +0.011 R aus dem einzigen vergleichbaren Anker herunter
(1,67-fache Vergröberung gegen 96-fache für +0.0856 R) — nicht die behaupteten
+0.05 bis +0.10 R. Und dann der eigentliche Satz:

> +0.011 R liegt um Faktor 7 **unter** der Auflösungsgrenze des Apparats bei
> zwölf Märkten. Dieser Kandidat kann auf der vorhandenen Population **richtig
> sein und nicht nachweisbar** — ein Lauf würde mit Sicherheit „Intervall
> enthält die Null" liefern, unabhängig davon, ob der Hebel wirkt.

Für die 35 Konstanten zusammen ist die Obergrenze **unbekannt und offline nicht
rechenbar**, weil die Zahl die Signalmenge *erzeugt* statt sie umzurechnen. Kein
Feld in den gespeicherten Fills trägt das nicht-realisierte Gegenstück. Der
Prüfer hält dazu fest, dass in-sample beliebig viel herauskommt und out-of-sample
null erwartet wird — und dass das Replikationstor genau diesen Fall schon einmal
gefangen hat.

---

## 5. Was zurückgeführt wurde

| Kandidat | Zurückgeführt auf |
|---|---|
| Was als Struktur zählt (35 Konstanten + 4 Schwellen) als *Hypothesenklasse* | Zeile 1 (Brutto ~null) in Verbindung mit Zeile 11 (19 Kandidaten, drei Programme) |
| Universum: 12 von 68 Märkten, Auswahl am engen Stop-Ende | Zeile 2 für den genannten Mechanismus, Zeile 1 + 16 für den Rest |
| Die Messlatte selbst (+0.45 R in jedem Exit-Vergleich festgehalten) | keine Zeile — aber zweimal ausserhalb der Liste schon gerechnet |

Bemerkenswert: dieselbe Sache (die Detektorkonstanten) überlebte unter der Linse
„Konfiguration" und fiel unter der Linse „Hypothesenklasse". Der Unterschied ist
der Freiheitsgrad: **eine** binäre Entscheidung mit drei vorab benannten Zellen
ist etwas anderes als **35 freie Zahlen**. Genau das trennt den Taktkandidaten
vom Konstantenkandidaten, und nicht das Hypothesenklassen-Argument.

---

## 6. Was ich daraus schliesse

1. **„Erschöpft" ist zu grob.** Elf Achsen sind formal offen. Aber „offen" ist
   nicht „aussichtsreich": sieben haben eine gerechnete Obergrenze unter der
   Anforderung, drei davon unter der Messgrenze.
2. **Zwei Achsen sind überhaupt noch messbar und oberhalb der Grenze:** der
   strukturbewusste Ausstieg (~+0.12 R) und der Haltedeckel (~0,14 R
   Markenbewegung). Beide sind 3- bis 4-fach zu klein, und für den Haltedeckel
   zeigt die Evidenz in die falsche Richtung.
3. **Eine Achse hat eine offene Decke und eine leere Erwartung.** Der
   Balkentakt. Er ist als **Falsifikation** wert gelaufen zu werden, nicht als
   Rettung — und das ist eine zulässige Begründung für einen Lauf.
4. **Eine Achse ist auf dieser Population unentscheidbar.** Die
   Detektorkonstanten. Mehr Märkte würden hier helfen, wo sie bei der
   Anforderung nicht helfen.
5. **Ein Defekt ist gefunden und ist nicht die Lösung.** Setup A handelt seit
   immer einen Ausstieg, den seine Quelle nicht vorschreibt, über 48,1 % der
   Population. Reparieren: ja. Als Rettung erwarten: nein, +0.028 R.

**Die Entscheidung, die daraus folgt, ist nicht meine.** Sie lautet: einen
Falsifikationslauf auf dem Balkentakt, oder aufhören. Beides ist vertretbar, und
die Zahlen für beides stehen oben.
