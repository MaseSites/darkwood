# Handelsbuch — Plankonto

Automatisch geschrieben aus `data/journal.sqlite`, Stand 20.10.2026 17:30 UTC.
Jede Zeile stammt aus dem gespeicherten Datensatz des Trades. Nichts hier ist geschaetzt.

Neu erzeugen: `python scripts/handelsbuch.py`

## Was die Zahlen bisher sagen

**11 abgeschlossene Trades · +0.3368 R · -99.00 USD**

- Treffer: 5 von 11 (45%)
- In R zusammengerechnet +0.3368, in USD -99.00. **Die beiden Vorzeichen stimmen nicht ueberein** -- das ist kein Rundungsfehler, sondern die Vorwaertsregel: Risiko ist das Ergebnis der Stopweite, nicht ihre Vorgabe.
- Durchschnittliches Risiko: **10.18 USD auf Gewinnern, 26.82 USD auf Verlierern** (2.63x)
- Durchschnittliche Stopweite: 0.491 % auf Gewinnern, 1.223 % auf Verlierern
- 0 Verlierer waren vorher mindestens 1 R im Plus (Rueckgabe-Muster)
- 5 Trades waren nie im Plus
- 3 Stops wurden von einem Docht geholt
- Der 1.5-%-Deckel haette bei 5 von 11 Trades gegriffen

> Das Konto verliert nicht, weil die Einstiege schlecht waeren -- in R ist die Summe positiv. Es verliert, weil die Verlierer groessere Positionen tragen als die Gewinner. Dagegen laeuft seit heute der Risikodeckel.

## Die Trades, aelteste zuerst
### 1. 20.10.2026 11:30 UTC · LTCUSDT · SHORT · VERLOREN

**-1.2028 R · -12.51 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Abwaertstrend; Bewertung 72/100 (gemischt)
- 7 von 7 Familien sprachen, Einigkeit 78%, Widerspruch 22%, aus 196 Ablesungen
- Einstieg 58.5600, Stop 58.8500 (0.495 % entfernt), Ziel 58.1250 - Chance:Risiko 1.50
- Eingesetzt: 35.86 Stueck = 2'100 USD Position auf 1'000 USD Konto; Risiko 10.40 USD = 1.04% des Kontos

**Was die Indikatoren sagten**

- Struktur: abwaerts (dafuer), Beitrag -0.5807, Einigkeit 63%
- Lage: abwaerts (dafuer), Beitrag -0.5309, Einigkeit 56%
- Trend: abwaerts (dafuer), Beitrag -0.3493, Einigkeit 59%
- Liquiditaet: aufwaerts (dagegen), Beitrag +0.2134, Einigkeit 87%
- Volatilitaet: abwaerts (dafuer), Beitrag -0.1661, Einigkeit 56%
- Momentum: abwaerts (dafuer), Beitrag -0.0493, Einigkeit 51%
- Volumen: abwaerts (dafuer), Beitrag -0.0316, Einigkeit 71%

**Was daraus wurde**

- Ausstieg: Stop getroffen bei 58.8677
- 3 Kerzen gehalten; am weitesten im Plus 0.483 R, am weitesten im Minus 1.061 R
- Gebuehren 1.48 USD, Funding 0.00 USD
- Urteil des Systems: Stop von einem Docht geholt (2 Kerzen); die Kerze schloss wieder auf der richtigen Seite. Vorher 0.48 R im Plus.

**Was ich daraus mitnehme**

- Ein Docht holte den Stop, die Kerze schloss wieder richtig -- der Stop lag im Rauschen.

---

### 2. 20.10.2026 12:45 UTC · SOLUSDT · LONG · VERLOREN

**-1.4169 R · -7.02 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Abwaertstrend; Bewertung 10/100 (Durcheinander)
- 7 von 7 Familien sprachen, Einigkeit 3%, Widerspruch 97%, aus 197 Ablesungen
- Einstieg 104.63, Stop 104.38 (0.239 % entfernt), Ziel 105.00 - Chance:Risiko 1.50
- Eingesetzt: 19.8 Stueck = 2'072 USD Position auf 987 USD Konto; Risiko 4.95 USD = 0.50% des Kontos

**Was die Indikatoren sagten**

- Struktur: aufwaerts (dafuer), Beitrag +0.6028, Einigkeit 37%
- Lage: abwaerts (dagegen), Beitrag -0.2463, Einigkeit 58%
- Liquiditaet: abwaerts (dagegen), Beitrag -0.2258, Einigkeit 76%
- Trend: abwaerts (dagegen), Beitrag -0.1418, Einigkeit 61%
- Volumen: abwaerts (dagegen), Beitrag -0.0196, Einigkeit 77%
- Volatilitaet: abwaerts (dagegen), Beitrag -0.0046, Einigkeit 55%
- Momentum: abwaerts (dagegen), Beitrag -0.0033, Einigkeit 52%

**Was daraus wurde**

- Ausstieg: Stop getroffen bei 104.35
- 0 Kerzen gehalten; am weitesten im Plus 0.000 R, am weitesten im Minus 0.000 R
- Gebuehren 1.45 USD, Funding 0.00 USD
- Urteil des Systems: keine Kursdaten zwischen Ein- und Ausstieg

**Was ich daraus mitnehme**

- War nie im Plus -- der Einstieg war von der ersten Kerze an falsch.
- Die Familien widersprachen sich zu 97% -- das war kein klares Bild.

---

### 3. 20.10.2026 13:00 UTC · ATOMUSDT · SHORT · GEWONNEN

**+1.5521 R · +11.13 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Abwaertstrend; Bewertung 54/100 (gemischt)
- 7 von 7 Familien sprachen, Einigkeit 66%, Widerspruch 34%, aus 192 Ablesungen
- Einstieg 1.7230, Stop 1.7290 (0.348 % entfernt), Ziel 1.7140 - Chance:Risiko 1.50
- Eingesetzt: 1195 Stueck = 2'060 USD Position auf 981 USD Konto; Risiko 7.17 USD = 0.73% des Kontos

**Was die Indikatoren sagten**

- Struktur: abwaerts (dafuer), Beitrag -0.5823, Einigkeit 52%
- Lage: abwaerts (dafuer), Beitrag -0.2700, Einigkeit 70%
- Liquiditaet: aufwaerts (dagegen), Beitrag +0.2143, Einigkeit 100%
- Trend: abwaerts (dafuer), Beitrag -0.1637, Einigkeit 68%
- Volatilitaet: abwaerts (dafuer), Beitrag -0.0590, Einigkeit 78%
- Volumen: abwaerts (dafuer), Beitrag -0.0202, Einigkeit 82%
- Momentum: aufwaerts (dagegen), Beitrag +0.0103, Einigkeit 60%

**Was daraus wurde**

- Ausstieg: Ziel erreicht bei 1.7140
- 2 Kerzen gehalten; am weitesten im Plus 2.000 R, am weitesten im Minus 0.000 R
- Gebuehren 0.82 USD, Funding 0.00 USD
- Urteil des Systems: Ziel erreicht nach 1 Kerzen, zwischenzeitlich 0.00 R gegen uns.

**Was ich daraus mitnehme**

- Lief sauber bis ans Ziel.
- Die Familien widersprachen sich zu 34% -- das war kein klares Bild.

---

### 4. 20.10.2026 14:00 UTC · XRPUSDT · LONG · GEWONNEN

**+1.4215 R · +15.14 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Abwaertstrend; Bewertung 48/100 (unklar)
- 7 von 7 Familien sprachen, Einigkeit 75%, Widerspruch 25%, aus 194 Ablesungen
- Einstieg 1.3096, Stop 1.3029 (0.512 % entfernt), Ziel 1.3197 - Chance:Risiko 1.50
- Eingesetzt: 1590 Stueck = 2'082 USD Position auf 992 USD Konto; Risiko 10.65 USD = 1.07% des Kontos

**Was die Indikatoren sagten**

- Struktur: abwaerts (dagegen), Beitrag -0.6126, Einigkeit 45%
- Lage: abwaerts (dagegen), Beitrag -0.1328, Einigkeit 50%
- Liquiditaet: aufwaerts (dafuer), Beitrag +0.0634, Einigkeit 68%
- Trend: aufwaerts (dafuer), Beitrag +0.0315, Einigkeit 51%
- Momentum: aufwaerts (dafuer), Beitrag +0.0191, Einigkeit 55%
- Volumen: abwaerts (dagegen), Beitrag -0.0187, Einigkeit 69%
- Volatilitaet: abwaerts (dagegen), Beitrag -0.0162, Einigkeit 45%

**Was daraus wurde**

- Ausstieg: Ziel erreicht bei 1.3197
- 0 Kerzen gehalten; am weitesten im Plus 0.000 R, am weitesten im Minus 0.000 R
- Gebuehren 0.84 USD, Funding 0.00 USD
- Urteil des Systems: keine Kursdaten zwischen Ein- und Ausstieg

**Was ich daraus mitnehme**

- War nie im Plus -- der Einstieg war von der ersten Kerze an falsch.
- Die Familien widersprachen sich zu 25% -- das war kein klares Bild.

---

### 5. 20.10.2026 14:00 UTC · BNBUSDT · LONG · GEWONNEN

**+1.3257 R · +6.12 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf H1, Signal auf M15
- Marktlage: Seitwaerts; Bewertung 61/100 (gemischt)
- 7 von 7 Familien sprachen, Einigkeit 72%, Widerspruch 28%, aus 197 Ablesungen
- Einstieg 733.96, Stop 732.33 (0.222 % entfernt), Ziel 736.40 - Chance:Risiko 1.50
- Eingesetzt: 2.83 Stueck = 2'077 USD Position auf 989 USD Konto; Risiko 4.61 USD = 0.47% des Kontos

**Was die Indikatoren sagten**

- Struktur: aufwaerts (dafuer), Beitrag +0.6124, Einigkeit 49%
- Liquiditaet: abwaerts (dagegen), Beitrag -0.1986, Einigkeit 68%
- Momentum: aufwaerts (dafuer), Beitrag +0.1882, Einigkeit 59%
- Volatilitaet: aufwaerts (dafuer), Beitrag +0.1412, Einigkeit 59%
- Lage: aufwaerts (dafuer), Beitrag +0.1336, Einigkeit 48%
- Trend: aufwaerts (dafuer), Beitrag +0.1175, Einigkeit 54%
- Volumen: aufwaerts (dafuer), Beitrag +0.0213, Einigkeit 71%

**Was daraus wurde**

- Ausstieg: Ziel erreicht bei 736.40
- 0 Kerzen gehalten; am weitesten im Plus 0.000 R, am weitesten im Minus 0.000 R
- Gebuehren 0.83 USD, Funding 0.00 USD
- Urteil des Systems: keine Kursdaten zwischen Ein- und Ausstieg

**Was ich daraus mitnehme**

- War nie im Plus -- der Einstieg war von der ersten Kerze an falsch.
- Die Familien widersprachen sich zu 28% -- das war kein klares Bild.

---

### 6. 20.10.2026 14:00 UTC · DOTUSDT · LONG · GEWONNEN

**+1.4527 R · +25.75 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Manipulation; Bewertung 57/100 (gemischt)
- 6 von 7 Familien sprachen, Einigkeit 100%, Widerspruch 0%, aus 195 Ablesungen
- Einstieg 1.1512, Stop 1.1414 (0.851 % entfernt), Ziel 1.1659 - Chance:Risiko 1.50
- Eingesetzt: 1808.8 Stueck = 2'082 USD Position auf 992 USD Konto; Risiko 17.73 USD = 1.79% des Kontos

**Was die Indikatoren sagten**

- Liquiditaet: aufwaerts (dafuer), Beitrag +0.2750, Einigkeit 80%
- Volatilitaet: aufwaerts (dafuer), Beitrag +0.1054, Einigkeit 71%
- Trend: aufwaerts (dafuer), Beitrag +0.0789, Einigkeit 63%
- Momentum: aufwaerts (dafuer), Beitrag +0.0657, Einigkeit 66%
- Lage: aufwaerts (dafuer), Beitrag +0.0583, Einigkeit 65%
- Volumen: aufwaerts (dafuer), Beitrag +0.0257, Einigkeit 77%
- Struktur: schwieg

**Was daraus wurde**

- Ausstieg: Ziel erreicht bei 1.1659
- 0 Kerzen gehalten; am weitesten im Plus 0.000 R, am weitesten im Minus 0.000 R
- Gebuehren 0.84 USD, Funding 0.00 USD
- Urteil des Systems: keine Kursdaten zwischen Ein- und Ausstieg

**Was ich daraus mitnehme**

- Der Risikodeckel von 1.5 % haette hier gegriffen: 17.73 USD Risiko statt erlaubter 14.87 USD. Haette 4.14 USD gekostet.
- War nie im Plus -- der Einstieg war von der ersten Kerze an falsch.

---

### 7. 20.10.2026 14:00 UTC · BTCUSDT · LONG · GEWONNEN

**+1.4232 R · +15.27 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf H1, Signal auf M15
- Marktlage: Seitwaerts; Bewertung 41/100 (unklar)
- 6 von 7 Familien sprachen, Einigkeit 52%, Widerspruch 48%, aus 199 Ablesungen
- Einstieg 82'115.50, Stop 81'686.40 (0.523 % entfernt), Ziel 82'759.15 - Chance:Risiko 1.50
- Eingesetzt: 0.025 Stueck = 2'053 USD Position auf 978 USD Konto; Risiko 10.73 USD = 1.10% des Kontos

**Was die Indikatoren sagten**

- Lage: abwaerts (dagegen), Beitrag -0.2095, Einigkeit 61%
- Liquiditaet: aufwaerts (dafuer), Beitrag +0.1885, Einigkeit 68%
- Volatilitaet: aufwaerts (dafuer), Beitrag +0.1752, Einigkeit 51%
- Volumen: aufwaerts (dafuer), Beitrag +0.1421, Einigkeit 61%
- Momentum: aufwaerts (dafuer), Beitrag +0.1270, Einigkeit 53%
- Trend: aufwaerts (dafuer), Beitrag +0.0257, Einigkeit 60%
- Struktur: schwieg

**Was daraus wurde**

- Ausstieg: Ziel erreicht bei 82'759.15
- 0 Kerzen gehalten; am weitesten im Plus 0.000 R, am weitesten im Minus 0.000 R
- Gebuehren 0.82 USD, Funding 0.00 USD
- Urteil des Systems: keine Kursdaten zwischen Ein- und Ausstieg

**Was ich daraus mitnehme**

- War nie im Plus -- der Einstieg war von der ersten Kerze an falsch.
- Die Familien widersprachen sich zu 48% -- das war kein klares Bild.

---

### 8. 20.10.2026 14:15 UTC · BTCUSDT · LONG · VERLOREN

**-1.0854 R · -27.24 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Seitwaerts; Bewertung 52/100 (gemischt)
- 6 von 7 Familien sprachen, Einigkeit 85%, Widerspruch 15%, aus 198 Ablesungen
- Einstieg 83'204.20, Stop 82'238.90 (1.160 % entfernt), Ziel 84'652.15 - Chance:Risiko 1.50
- Eingesetzt: 0.026 Stueck = 2'163 USD Position auf 1'030 USD Konto; Risiko 25.10 USD = 2.44% des Kontos

**Was die Indikatoren sagten**

- Volatilitaet: aufwaerts (dafuer), Beitrag +0.1752, Einigkeit 51%
- Liquiditaet: aufwaerts (dafuer), Beitrag +0.1752, Einigkeit 65%
- Volumen: aufwaerts (dafuer), Beitrag +0.1421, Einigkeit 58%
- Momentum: aufwaerts (dafuer), Beitrag +0.1270, Einigkeit 49%
- Lage: abwaerts (dagegen), Beitrag -0.0510, Einigkeit 49%
- Trend: aufwaerts (dafuer), Beitrag +0.0257, Einigkeit 56%
- Struktur: schwieg

**Was daraus wurde**

- Ausstieg: Stop getroffen bei 82'214.23
- 4 Kerzen gehalten; am weitesten im Plus 0.224 R, am weitesten im Minus 1.062 R
- Gebuehren 1.50 USD, Funding 0.00 USD
- Urteil des Systems: Stop von einem Docht geholt (3 Kerzen); die Kerze schloss wieder auf der richtigen Seite. Vorher 0.22 R im Plus.

**Was ich daraus mitnehme**

- Der Risikodeckel von 1.5 % haette hier gegriffen: 25.10 USD Risiko statt erlaubter 15.45 USD. Haette 10.47 USD gespart.
- Ein Docht holte den Stop, die Kerze schloss wieder richtig -- der Stop lag im Rauschen.

---

### 9. 20.10.2026 14:15 UTC · SOLUSDT · LONG · VERLOREN

**-1.0411 R · -49.80 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Seitwaerts; Bewertung 57/100 (gemischt)
- 7 von 7 Familien sprachen, Einigkeit 79%, Widerspruch 21%, aus 197 Ablesungen
- Einstieg 107.76, Stop 105.43 (2.162 % entfernt), Ziel 111.25 - Chance:Risiko 1.50
- Eingesetzt: 20.53 Stueck = 2'212 USD Position auf 1'053 USD Konto; Risiko 47.83 USD = 4.54% des Kontos

**Was die Indikatoren sagten**

- Struktur: aufwaerts (dafuer), Beitrag +0.6290, Einigkeit 37%
- Momentum: aufwaerts (dafuer), Beitrag +0.1402, Einigkeit 53%
- Volatilitaet: aufwaerts (dafuer), Beitrag +0.1068, Einigkeit 59%
- Trend: aufwaerts (dafuer), Beitrag +0.0981, Einigkeit 50%
- Liquiditaet: abwaerts (dagegen), Beitrag -0.0621, Einigkeit 73%
- Lage: abwaerts (dagegen), Beitrag -0.0572, Einigkeit 43%
- Volumen: aufwaerts (dafuer), Beitrag +0.0378, Einigkeit 69%

**Was daraus wurde**

- Ausstieg: Stop getroffen bei 105.40
- 4 Kerzen gehalten; am weitesten im Plus 0.103 R, am weitesten im Minus 1.155 R
- Gebuehren 1.52 USD, Funding 0.00 USD
- Urteil des Systems: Stop von einem Docht geholt (3 Kerzen); die Kerze schloss wieder auf der richtigen Seite. Vorher 0.10 R im Plus.

**Was ich daraus mitnehme**

- Der Risikodeckel von 1.5 % haette hier gegriffen: 47.83 USD Risiko statt erlaubter 15.80 USD. Haette 33.35 USD gespart.
- Ein Docht holte den Stop, die Kerze schloss wieder richtig -- der Stop lag im Rauschen.

---

### 10. 20.10.2026 14:15 UTC · XRPUSDT · LONG · VERLOREN

**-1.0625 R · -34.33 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Seitwaerts; Bewertung 46/100 (unklar)
- 7 von 7 Familien sprachen, Einigkeit 68%, Widerspruch 32%, aus 194 Ablesungen
- Einstieg 1.3355, Stop 1.3160 (1.460 % entfernt), Ziel 1.3647 - Chance:Risiko 1.50
- Eingesetzt: 1657.1 Stueck = 2'213 USD Position auf 1'054 USD Konto; Risiko 32.31 USD = 3.07% des Kontos

**Was die Indikatoren sagten**

- Struktur: abwaerts (dagegen), Beitrag -0.6102, Einigkeit 45%
- Lage: abwaerts (dagegen), Beitrag -0.1593, Einigkeit 43%
- Momentum: aufwaerts (dafuer), Beitrag +0.0763, Einigkeit 52%
- Liquiditaet: aufwaerts (dafuer), Beitrag +0.0633, Einigkeit 68%
- Volumen: abwaerts (dagegen), Beitrag -0.0187, Einigkeit 69%
- Volatilitaet: abwaerts (dagegen), Beitrag -0.0162, Einigkeit 45%
- Trend: aufwaerts (dafuer), Beitrag +0.0126, Einigkeit 48%

**Was daraus wurde**

- Ausstieg: Stop getroffen bei 1.3156
- 4 Kerzen gehalten; am weitesten im Plus 0.552 R, am weitesten im Minus 1.381 R
- Gebuehren 1.53 USD, Funding 0.00 USD
- Urteil des Systems: Erst 0.55 R im Plus, dann gedreht und ausgestoppt (3 Kerzen).

**Was ich daraus mitnehme**

- Der Risikodeckel von 1.5 % haette hier gegriffen: 32.31 USD Risiko statt erlaubter 15.81 USD. Haette 17.54 USD gespart.
- War 0.55 R im Plus, bevor es drehte.
- Die Familien widersprachen sich zu 32% -- das war kein klares Bild.

---

### 11. 20.10.2026 14:15 UTC · ADAUSDT · LONG · VERLOREN

**-1.0297 R · -41.50 USD** · Regel: 30 % x 7, ohne Deckel

**Warum ich reingegangen bin**

- Setup A Momentum-Breakout (V08) auf M15, Signal auf M15
- Marktlage: Seitwaerts; Bewertung 10/100 (Durcheinander)
- 6 von 7 Familien sprachen, Einigkeit 6%, Widerspruch 94%, aus 197 Ablesungen
- Einstieg 0.225100, Stop 0.221000 (1.821 % entfernt), Ziel 0.231250 - Chance:Risiko 1.50
- Eingesetzt: 9831 Stueck = 2'212 USD Position auf 1'053 USD Konto; Risiko 40.31 USD = 3.83% des Kontos

**Was die Indikatoren sagten**

- Lage: abwaerts (dagegen), Beitrag -0.3171, Einigkeit 42%
- Liquiditaet: aufwaerts (dafuer), Beitrag +0.2069, Einigkeit 92%
- Momentum: aufwaerts (dafuer), Beitrag +0.1097, Einigkeit 51%
- Trend: abwaerts (dagegen), Beitrag -0.0697, Einigkeit 43%
- Volatilitaet: aufwaerts (dafuer), Beitrag +0.0445, Einigkeit 40%
- Volumen: abwaerts (dagegen), Beitrag -0.0231, Einigkeit 67%
- Struktur: schwieg

**Was daraus wurde**

- Ausstieg: Stop getroffen bei 0.220934
- 4 Kerzen gehalten; am weitesten im Plus 0.400 R, am weitesten im Minus 1.350 R
- Gebuehren 1.53 USD, Funding 0.00 USD
- Urteil des Systems: Erst 0.40 R im Plus, dann gedreht und ausgestoppt (3 Kerzen).

**Was ich daraus mitnehme**

- Der Risikodeckel von 1.5 % haette hier gegriffen: 40.31 USD Risiko statt erlaubter 15.80 USD. Haette 25.24 USD gespart.
- Die Familien widersprachen sich zu 94% -- das war kein klares Bild.
