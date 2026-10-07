# E6.1: Funding-Carry, voll durchgerechnet

Reproduktion:

```bash
python scripts/backfill_spot.py          # holt die fehlende Spot-Reihe
python scripts/study_basis.py --hold 180
```

**Ergebnis: kein Kandidat.** Der Carry war ein Ertrag und ist seit etwa
November 2024 keiner mehr. Das ist kein Messfehler und keine Pechsträhne,
sondern folgt aus der Zerlegung.

---

## 1. Warum das überhaupt nachgerechnet wurde

Funding-Carry war die einzige Zahl in diesem Projekt mit positivem
Vorzeichen: **+5,5 % bis +14,8 % p.a. aufs Notional**, 11 von 12 Märkten
mit Intervall über Null, über 3,8 bis 6,7 Jahre. Perp short gegen Spot
long, Preis herausgehedgt, keine Vorhersage nötig.

Das Versuchsregister führte E6 trotzdem als `teilweise_blockiert`, mit
einem benannten Defekt: *„Keine Spot-Reihe auf der Platte, also
Basisrisiko ungemessen."*

Dieser Defekt ist jetzt behoben — `scripts/backfill_spot.py`, acht Märkte,
je 33 013 Stundenkerzen ab 2023-01-01 — und mit ihm fällt die Zahl.

## 2. Die Rechnung

Mit Spot long und Perp short zu je `q` ist der Preis-PnL

```
q*(Spot_aus - Spot_ein) + q*(Perp_ein - Perp_aus)
  = q*((Perp_ein - Spot_ein) - (Perp_aus - Spot_aus))
  = q*(b_ein - b_aus)
```

Alles andere kürzt sich. **Der gehedgte Trade verdient genau die Verengung
der Basis** — die Kursrichtung kommt nicht vor, und das ist der Zweck der
Konstruktion.

Drei Posten fehlten der alten Zahl:

| Posten | Wirkung |
|---|---|
| Basisbewegung | der ganze Preisrisiko-Term |
| Maut auf **beiden** Beinen, **zweimal** | 0,280 % je Runde |
| Gebundenes Kapital statt Notional | Nenner 2× bei Hebel 1 |

Nur acht Märkte, und das ist keine Stichprobenwahl: E6.1 verlangt *eine*
Börse. Gemessen tragen **ADA, ATOM, AVAX, BNB, DOGE, DOT, LINK, LTC**
Binance-Funding, BTC/ETH/SOL/XRP tragen Bybit. Die Perp-Kerzen sind
durchweg Binance. Für die anderen vier wäre es Bybit-Funding gegen
Binance-Preise — kein Same-Venue-Arm, und `backfill_spot.py` verweigert
sie darum ohne ausdrückliches Flag.

## 3. Die Zerlegung, 30-Tage-Haltedauer

| Markt | Basis Median | Funding | Basisbewegung | Maut | = netto |
|---|---|---|---|---|---|
| ADAUSDT | −4,63 bp | +0,425 % | +0,001 % | −0,280 % | **+0,146 %** |
| ATOMUSDT | −6,65 bp | −0,006 % | +0,001 % | −0,280 % | −0,285 % |
| AVAXUSDT | −4,26 bp | +0,309 % | +0,002 % | −0,280 % | +0,030 % |
| BNBUSDT | +1,88 bp | −0,145 % | −0,002 % | −0,280 % | −0,426 % |
| DOGEUSDT | −4,33 bp | +0,482 % | +0,002 % | −0,280 % | **+0,203 %** |
| DOTUSDT | −5,15 bp | +0,203 % | +0,000 % | −0,280 % | −0,076 % |
| LINKUSDT | −4,14 bp | +0,503 % | +0,001 % | −0,280 % | **+0,224 %** |
| LTCUSDT | −4,69 bp | +0,508 % | +0,002 % | −0,280 % | **+0,229 %** |

**Die Basis war nicht das Problem.** Ihre Bewegung über 30 Tage liegt bei
**±0,002 %** — sie kehrt zurück, wie die Theorie sagt, weil Perp und Spot
zum Verfall konvergieren. Die Hypothese „Basisrisiko frisst den Carry"
ist damit geprüft und **widerlegt**.

**Die Maut war das Problem.** 0,280 % je Runde gegen 0,2 bis 0,5 % Funding
in 30 Tagen — sie frisst 56 % bis über 100 % der Einnahme. Dieselbe
Geschichte wie überall sonst in diesem Projekt.

## 4. Die Haltedauer, und was sie vorhersagbar tut

Die Maut fällt **je Runde**, das Funding **je Zeit**. Länger halten
verdünnt also die Maut — das ist eine Vorhersage aus der Zerlegung, keine
Suche nach der besten Zelle, und darum stehen hier alle vier geprüften
Werte. Korrigiert auf die 46 angemeldeten Vergleiche (Niveau 99,8913 %):

| Halten | netto/Fenster | korrigiertes Intervall | p.a. auf Kapital | unabh. Perioden |
|---|---|---|---|---|
| 7 d | −0,2139 % | [−0,2550; −0,1741] | −5,58 % | 196 je Markt |
| 30 d | +0,0056 % | [−0,1849; +0,2029] | +0,03 % | 46 je Markt |
| 90 d | +0,5912 % | [−0,1037; +1,3863] | +1,20 % | 15 je Markt |
| **180 d** | **+1,5554 %** | **[+0,2405; +3,0046]** | **+1,58 %** | **7,6 je Markt** |

Bei 180 Tagen schliesst das korrigierte Intervall die Null aus. Das ist das
**erste Mal in diesem Projekt**, dass etwas nach voller Kostenrechnung
dieses Tor passiert.

## 5. Und dann fällt es am zweiten Tor

Dieses Projekt verlangt zwei Tore, nicht eines. Das zweite ist die
Replikation im Band 0,5–2,0×, auf der halbierten Zeitachse:

| | netto je 180-Tage-Fenster |
|---|---|
| frühere Hälfte (bis 2024-11-18) | **+2,9374 %** |
| spätere Hälfte (ab 2024-11-18) | **−0,1120 %** |
| Verhältnis | **−0,04×** |

**Durchgefallen, mit Vorzeichenwechsel.** Der gesamte positive Befund
stammt aus der früheren Hälfte.

Und das ist keine Überraschung, sondern der Anschluss an einen Befund, der
schon dastand: **das Funding schrumpft**, in 11 von 12 Märkten, in beiden
Venue-Gruppen getrennt bestätigt. Eine Messung über ein Fenster, das die
Hochfunding-Jahre enthält, überschätzt, was heute zu holen ist.

## 6. Was heute noch da ist

Nur die spätere Hälfte, ab 18.11.2024:

| Halten | netto/Fenster | korrigiertes Intervall | p.a. auf Kapital |
|---|---|---|---|
| 30 d | **−0,2006 %** | **[−0,3323; −0,0762]** | −1,22 % |
| 90 d | −0,1596 % | [−0,6098; +0,2575] | −0,32 % |
| 180 d | −0,1120 % | [−1,1423; +0,7154] | −0,11 % |

Bei keiner Haltedauer positiv. Bei 30 Tagen **zuverlässig negativ** — das
Intervall schliesst die Null aus, auf der falschen Seite.

## 7. Die Liquidation, die nicht weggehedgt wird

Der Auftrag nennt den Fall: *„Liquidation des Short-Beins, während der
Gewinn im Spot-Bein liegt."* Unter isolierter Margin rettet der
Spot-Gewinn das Perp-Bein nicht, und eine Verrechnung über beide Beine ist
ein Produktmerkmal der Börse, das hier nicht unterstellt wird.

Anteil der 30-Tage-Fenster, in denen das Short-Bein liquidiert worden wäre:

| Markt | 1× | 2× | 3× | 5× |
|---|---|---|---|---|
| ADAUSDT | 2,2 % | 10,7 % | 18,9 % | 37,3 % |
| AVAXUSDT | 4,0 % | 11,3 % | 19,0 % | 41,6 % |
| DOGEUSDT | 4,2 % | 8,8 % | 21,8 % | 38,1 % |
| BNBUSDT | 0,0 % | 2,4 % | 6,8 % | 21,6 % |

**Selbst bei Hebel 1** wird das Short-Bein in bis zu 4,2 % der Fenster
liquidiert — der Perp müsste dafür um 99,5 % steigen, und in Krypto tut er
das. Mehr Hebel senkt zwar den Kapitalnenner, holt aber die Liquidation
massiv herein: bei 5× in über einem Drittel der Fenster. Der Hebel ist
hier kein Weg zu besserer Kapitaleffizienz.

## 8. Was auch diese Zahlen noch nicht enthalten

Alle vier ziehen weiter ab, keiner hebt:

* **Der halbe Spread auf beiden Beinen**, rein und raus. Gerechnet ist auf
  Stundenschlusskursen; die echte Eintrittsbasis liegt zwischen Perp-Bid
  und Spot-Ask.
* **Finanzierungskosten des Spot-Beins** und Transferzeit zwischen den
  Konten.
* **Jede Margin-Verrechnung** über beide Beine — ein Produktmerkmal, das
  nicht unterstellt wird.
* **Acht korrelierte Märkte sind eine Beobachtung**, nicht acht. Bei 180
  Tagen sind das 7,6 unabhängige Perioden je Markt.

## 9. Was das für das Ziel bedeutet

Auch die *optimistische* Lesart — die +1,58 % p.a. auf Kapital aus dem
vollen Fenster, bevor die Replikation sie kippt — sind auf 12 000 CHF rund
**190 CHF im Jahr**, also etwa **12 CHF in 23 Tagen**. Gebraucht werden
2 953 CHF.

Der Carry war nie ein Weg zum Ziel; jetzt ist er nicht einmal mehr ein
Ertrag. Was bleibt, ist der Satz, der schon im Zustandsbericht steht: es
gibt in diesem System derzeit keinen belegten Weg, Geld zu verdienen — und
diese Untersuchung hat den letzten Kandidaten geschlossen, der noch ein
positives Vorzeichen trug.
