# E23 — Verdienen die Market Maker auf Lighter Geld?

**Beobachtet, nicht geschätzt.** 21.10.2026, Fenster 24 h, drei Märkte.
Daten: `data/quarantine/venue_ws/{BTC,ETH,SOL}/` — 974'938 Geschäfte.
Nachrechnen: `python scripts/study_lighter_pnl.py`

---

## Warum diese Frage anders beantwortbar ist als jede andere hier

Lighters Websocket nennt bei jedem Geschäft **beide Konten**
(`ask_account_id`, `bid_account_id`), welche Seite der Maker war
(`is_maker_ask`) und den Bestand beider Seiten **vor** dem Geschäft
(`*_position_size_before`). Damit wird aus „lohnt sich Market Making hier?"
eine Beobachtung: man sieht, ob andere damit Geld verdienen, **bevor** man
einen Rappen einsetzt.

Das ist in diesem Projekt einzigartig. Jede andere Frage brauchte eine eigene
Stichprobe und damit eigenes Risiko.

---

## 1. Das Ergebnis, und es ist je Markt verschieden

Konten mit ≥10 Geschäften und ≥80 % Maker-Anteil, volles P&L über das Fenster
(Geldfluss + Bestandsbewertung):

| Markt | Maker-Konten | P&L zusammen | auf Nominal | Gewinner |
|---|---|---|---|---|
| **BTC** | 197 | **+349'205 USD** | **+4.47 bp** | 118/197 (60 %) |
| **ETH** | 110 | **−357'424 USD** | **−7.34 bp** | 66/110 (60 %) |
| **SOL** | 70 | **+43'176 USD** | **+6.07 bp** | 41/70 (59 %) |

Auf allen drei Märkten ist der **Median-Maker leicht im Plus** (+2 bis +4 USD)
und rund 60 % sind Gewinner. Die Summen entscheiden wenige grosse Konten.

---

## 2. Die Zerlegung, ohne die man Richtung als Handwerk liest

Alle drei Märkte **stiegen** im Fenster. Ein Maker absorbiert Fluss; wer in
einen Anstieg hinein verkauft wird, verliert — unabhängig davon, wie gut er
gestellt hat. Exakte Aufteilung:

```
P&L = Σ qᵢ·(P_ende − pᵢ)  +  pos₀·(P_ende − P_start)
      ──────────────────     ─────────────────────────
      Ausführung             Altbestand reitet die Bewegung
```

| Markt | Kursbewegung | Ausführung | Altbestand | Maker gingen |
|---|---|---|---|---|
| BTC | +2.52 % | **+275'696** | +73'509 | LONG (+72 BTC) |
| ETH | +3.14 % | **−60'044** | −297'380 | SHORT (−10'593 ETH) |
| SOL | +4.33 % | **−21'186** | +64'362 | LONG |

**BTC gewinnt am Handwerk** (79 % des Ergebnisses). **ETH verliert an beidem**,
und 83 % davon ist Richtung. **SOL verliert am Handwerk** und wird von der
Richtung gerettet — ein positives Ergebnis, das nichts über Market Making sagt.

---

## 3. Der realisierte Spread — die eigentliche Messung

Was ein Maker-Geschäft nach N Sekunden wert war, über **alle** Maker-Geschäfte,
in bp auf das gehandelte Nominal. „Bereinigt" zieht `Seitenungleichgewicht ×
Drift` ab, weil die Drift genau über dieses Ungleichgewicht ins Ergebnis wirkt.

| Horizont | BTC | ETH | SOL |
|---|---|---|---|
| sofort | **+0.320** | **+0.555** | **+0.333** |
| +10 s | +0.058 | **−0.223** | **−0.280** |
| +60 s | +0.236 | **−0.362** | −0.092 |
| +300 s | +0.283 | −0.190 | −0.094 |

> [!important] Der Befund
> **BTC-Maker behalten ihren Spread. ETH- und SOL-Maker geben ihn innerhalb
> von zehn Sekunden vollständig zurück** — und mehr.

Auf ETH werden +0.555 bp gestellt und nach 10 s stehen −0.223 bp: **0.78 bp
Rückgabe gegen 0.56 bp Einnahme.** Das ist adverse Selektion, und sie ist das
8- bis 28-fache der Gebühr (0.028–0.050 bp nach E20).

**Nicht die Gebühr ist der Preis des Market Making, sondern diese Differenz.**

---

## 4. Das widerlegt E20 — und der Grund ist lehrreich

E20 schloss: *„BTC ist tot, ETH und SOL sind es nicht."* Grundlage war der
**gestellte Touch-Spread**: BTC 0.0244 bp gegen ETH 0.4585 und SOL 0.4807 bp.

Hier gemessen ist es **umgekehrt**. Der Unterschied ist der zwischen

- was man **stellt** (Touch-Spread) und
- was man **behält** (realisierter Spread).

Ein weiter Spread auf einem Markt, auf dem informierter Fluss ihn sofort
abholt, ist kein Verdienst, sondern eine Einladung. Ein enger Spread auf einem
Markt, auf dem er stehen bleibt, ist einer.

E20 ist damit nicht falsch gerechnet — es hat die falsche Grösse gemessen. Die
Zeile „BTC ist tot" steht dort weiter, und sie ist ab heute überholt.

---

## 5. Was diese Messung nicht trägt

- **Der Vergleichsmassstab ist der nächste Abschluss, nicht die Mitte.** Wer
  gegen die Mitte misst, bekommt rund die Hälfte dieser Zahlen. Vorzeichen und
  Horizontprofil ändern sich dadurch nicht, und auf die kommt es an.
- **Ein Fenster von 24 h.** Die Drift ist bereinigt, aber ein einziger Tag
  entscheidet nicht über ein Geschäftsmodell. Dasselbe Programm über eine
  Woche wäre die nächste Stufe.
- **Drei Märkte.** 1'064 Konten handelten auf mehr als einem; wer ausserhalb
  hedgt, wird hier falsch gelesen.
- **Die Einheit von `maker_fee` ist nicht bestimmbar.** Unter jeder plausiblen
  Lesart liegt sie zwischen 0.0001 und 0.1 bp. Alle Zahlen oben sind **vor**
  Gebühr; bei dieser Grössenordnung ändert sie das Vorzeichen nirgends.
- **Gefüllt zu werden ist die eigentliche Hürde.** Nach E20 handeln nur
  **2.880 %** [2.396, 3.444] des am Touch angebotenen Nominals. Ein positives
  Maker-Ergebnis heisst nicht, dass wir es wiederholen könnten.

---

## 6. Urteil

**Die Frage ist beantwortet, und die Antwort ist marktabhängig.**

Market Making auf **BTC** verdient auf dieser Börse messbar Geld — +4.47 bp
auf Nominal, davon 79 % aus dem Handwerk, und der realisierte Spread bleibt
auf jedem Horizont positiv.

Auf **ETH** und **SOL** nicht: der gestellte Spread wird binnen zehn Sekunden
zurückgegeben. Was dort positiv aussieht (SOL), ist Richtung.

**Was NICHT folgt:** dass wir es tun sollten. Zwischen „andere verdienen hier"
und „wir können es" steht die Füllquote von 2.88 %, und die ist nicht gemessen
worden für jemanden, der neu dazukommt und keine Latenzvorteile hat.

**Nächster Schritt, falls das verfolgt wird:** dasselbe Programm über eine
Woche statt einen Tag, und dabei die Konten verfolgen statt nur zu aggregieren
— ob dieselben Konten durchgehend verdienen oder ob die Gewinner wechseln,
unterscheidet ein Geschäftsmodell von Glück.

---

# E23b — Verdienen dieselben Konten durchgehend?

Nachgereicht am 21.10.2026, nachdem E23 die Frage offen gelassen hatte.
Nachrechnen: `python scripts/study_lighter_persistenz.py`

## Warum das die entscheidende Frage ist

E23 fand: rund **60 % der Maker-Konten sind im Plus**. Das kann zweierlei
heissen, und die beiden sehen im Querschnitt **identisch** aus:

```
ein Geschäftsmodell   dieselben Konten verdienen, Fenster für Fenster
Glück                 jedes Fenster hat andere Gewinner, und 60 % ist
                      nur die Schiefe einer Verteilung
```

Unterscheiden kann sie nur, wer **dasselbe Konto über zwei Fenster verfolgt**.

Gemessen wird der **realisierte Spread**, nicht das P&L: ein Konto-P&L über
Stunden ist überwiegend die Kursbewegung auf seinem Bestand (auf ETH 83 %).
Wer darauf Beständigkeit misst, misst, ob dasselbe Konto zweimal in dieselbe
Richtung stand.

## Das Ergebnis

Zwei Hälften desselben Tages, realisierter Spread bei +60 s:

| | Konten | Rangkorrelation | auflösbar ab | über Median blieben |
|---|---|---|---|---|
| BTC | 111 | **+0.065** ± 0.191 | \|ρ\| > 0.19 | 56 % ± 13 % |
| ETH | 66 | **+0.098** ± 0.248 | \|ρ\| > 0.25 | 55 % ± 17 % |
| SOL | 36 | **−0.143** ± 0.338 | \|ρ\| > 0.34 | 44 % ± 24 % |

Mischprobe (dieselben Zahlen, Zuordnung zerstört): +0.002 / −0.062 / −0.017.

> [!important] Auf keinem der drei Märkte ist die Beständigkeit von null zu
> unterscheiden. Auch die Übergangsquoten liegen innerhalb ihres Fehlers.

**Und was der Test nicht ausschliesst:** er löst erst ab |ρ| > 0.19 auf (BTC,
der günstigste Fall). Eine echte, aber schwache Beständigkeit darunter bliebe
unsichtbar. „Nicht nachweisbar" ist nicht „existiert nicht".

## Warum das der wohlwollendste mögliche Test war

Zwei Hälften **desselben Tages** teilen sich Marktbedingungen, Teilnehmer und
Volatilitätsregime. Jede längere Trennung — Woche gegen Woche, Monat gegen
Monat — hat *weniger* gemeinsame Ursachen und damit *weniger* zu erwartende
Korrelation. Was hier schon nicht besteht, besteht dort erst recht nicht.

## Was daraus für uns folgt

E23 zeigte: auf BTC verdienen Maker messbar Geld (+4.47 bp auf Nominal, 79 %
davon aus dem Handwerk). E23b zeigt: **wir könnten nicht sagen, welche.**

Dazwischen stehen jetzt zwei Hürden, nicht eine:

1. **Füllquote 2.880 %** [2.396, 3.444] des am Touch angebotenen Nominals (E20)
2. **Keine nachweisbare Beständigkeit** — mitzumachen wäre ein Zug aus der
   Verteilung, keine Nachbildung eines Modells

> [!warning] Urteil
> Market Making auf dieser Börse ist für uns **kein Kandidat**, solange nicht
> eine der beiden Hürden fällt. Das Urteil kostete einen Tag Rechnen und
> **keinen Rappen Risiko** — was der ganze Grund war, die Frage über fremde
> Konten zu stellen statt über eigene.

**Was es wert wäre:** dieselbe Messung über eine Woche. Wenn die Zahl der
Konten mit 30+ Geschäften je Hälfte von 111 auf mehrere hundert steigt, sinkt
die Auflösungsgrenze unter 0.1 — und dann ist auch eine schwache Beständigkeit
sichtbar. Der Sammler läuft; das kostet nur Zeit.
