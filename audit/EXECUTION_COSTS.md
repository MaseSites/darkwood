# Phase 6 — Ausführungskosten, Mindestgrössen, Währung

**Lauf:** 09.10.2026, 08:30–08:40 UTC · Commit `d362652`
**Quellen:** `fapi/v1/exchangeInfo` und `fapi/v1/ticker/price`, live abgefragt,
nur lesend. Journal `data/journal.sqlite` mit 2 751 Trades.

Jede Zeile trennt **gemessen**, **Annahme** und **offen**.

---

## 1. Die Börsenfilter, live abgefragt statt angenommen

924 Symbole in `exchangeInfo`, davon die zwölf gehandelten:

| Markt | Preis | Tick | Schritt | min. Notional |
|---|---|---|---|---|
| BTCUSDT | 82 391,50 | 0,10 | 0,001 | **82,39** |
| ETHUSDT | 2 492,05 | 0,01 | 0,001 | 20,00 |
| SOLUSDT | 109,59 | 0,01 | 0,01 | 5,00 |
| XRPUSDT | 1,3878 | 0,0001 | 0,1 | 5,00 |
| ADAUSDT | 0,2364 | 0,0001 | 1,0 | 5,00 |
| AVAXUSDT | 10,3190 | 0,001 | 1,0 | **10,32** |
| LINKUSDT | 12,7850 | 0,001 | 0,01 | 20,00 |
| DOGEUSDT | 0,0843 | 0,00001 | 1,0 | 5,00 |
| BNBUSDT | 741,52 | 0,01 | 0,01 | 7,42 |
| LTCUSDT | 63,79 | 0,01 | 0,001 | 20,00 |
| DOTUSDT | 1,1602 | 0,0001 | 0,1 | 5,00 |
| ATOMUSDT | 1,9480 | 0,001 | 0,01 | 5,00 |

Das effektive Minimum ist `max(MIN_NOTIONAL, minQty × Preis)` — bei BTC und
AVAX bindet die Stückzahl, nicht der Notional-Filter.

## 2. P38 war falsch: Mindestgrössen sind kein Blocker

Im Problembericht stand: *„1 000 CHF Startkapital kollidiert mit
Mindestgrössen … nach dem ersten Drawdown wird die Luft dünn."* **Gemessen
trifft das nicht.**

Die Positionsgrösse folgt aus `Risiko / Stop-Abstand`. Der gemessene
Median-Stop ist **1,3090 %** des Preises, also ist das Notional bei 1 %
Risiko das **0,76-fache** des Eigenkapitals:

| | |
|---|---|
| Position bei 1 000 Konto, 1 % Risiko | **764 USDT** |
| höchstes effektives Minimum (BTC) | 82,39 USDT |
| **Kontoboden, unter dem ein Markt ausfällt** | **108 USDT** |

Das System kann alle zwölf Märkte bis **108 USDT** Eigenkapital handeln. Der
Boden liegt nicht in der Nähe von 1 000, sondern fast eine Grössenordnung
darunter. **P38 ist damit entkräftet** — und das war meine eigene Behauptung.

## 3. Was dafür wirklich bindet: die Risiko-Körnung

Die Stückzahl muss ein Vielfaches der Schrittweite sein. Bei 1 000 Konto und
1 % Risiko:

| Markt | eine Schrittweite | als Anteil der Position |
|---|---|---|
| **BTCUSDT** | 82,39 USDT | **10,79 %** |
| AVAXUSDT | 10,32 USDT | 1,35 % |
| BNBUSDT | 7,42 USDT | 0,97 % |
| alle anderen | ≤ 2,49 USDT | ≤ 0,33 % |

**Auf BTC ist das angestrebte Risiko nur in Schritten von rund 11 % treffbar.**
Wer 1,00 % will, bekommt 0,89 %, 1,00 %, 1,11 % — nichts dazwischen.

Gemessen in der Live-Epoche über 17 Trades: Körnung 0,00 % bis **3,45 %**
(AVAX, 29 Schritte), Median-Risiko 9,990 von 10 angestrebten. Der einzige
BTC-Live-Trade trägt 60 Schritte und damit nur 1,67 % Körnung — **weil er aus
der Epoche mit grösserem Konto stammt.** Bei 1 000 wären es rund 6 Schritte.

**Offen:** die 10,79 % auf BTC sind vorhergesagt, nicht beobachtet. Kein
Live-Trade hat sie bisher ausgelöst.

## 4. Und eine Epochen-Mischung, die jede Geldaussage betrifft

Das Journal mischt **drei** Risiko-Einstellungen:

| Epoche | Belege | Risiko je Trade |
|---|---|---|
| frühes, grosses Konto | SOL 858, XRP 744, ETH 638, BTC 496 Trades | **32–53** USDT |
| erste Live-Trades, 0,5 % | BNB, LINK, ATOM (03.–04.10.) | **4,996–5,000** |
| aktuell, 1 % von 1 000 | die übrigen 14 Live-Trades | **9,77–10,20** |

Median über alle 2 751 Trades: **39,73** — nicht 10.

**Was das betrifft und was nicht.** Jede Aussage in **R** ist davon unberührt,
weil `r_multiple` skalenfrei ist: E8, E3, E10 und die Monte-Carlo-Rechnungen
stehen. Jede Aussage in **Geld** über die Gesamtpopulation ist es nicht. Dass
drei der 17 Live-Trades auf halbem Risiko liefen, muss bei jeder
Netto-Franken-Bilanz der Vorwärtsphase dabeistehen.

## 5. Die Kostenbestandteile, getrennt

Der Auftrag verlangt, keine pauschale „Kosten pro Trade"-Zahl zu verwenden.
Was der Simulator ansetzt und woher:

| Bestandteil | Wert | Quelle | Stand |
|---|---|---|---|
| Maker-Gebühr | 0,0200 % | `DEFAULT_SPEC` | Binance-Raten, **nicht gegen die Kontostufe verifiziert** |
| Taker-Gebühr | 0,0550 % | `DEFAULT_SPEC` | dito |
| Slippage | 3,0 bp, **nur gegen uns** | `settings.yaml` | Annahme, nicht gemessen |
| Funding | echte Raten je Abrechnung | `data/funding/*.parquet`, 7 364 Zeilen je Markt | gemessen; Verzeichnis **mischt zwei Börsen** (P16) |
| Liquidation | Mark-Price, `maintenance_margin_rate` 0,5 % | `DEFAULT_SPEC` | Annahme |
| Füllmodell | Durchhandeln, kein Antritt | `fill_on_touch: false` | **validiert**, E9: 0,6 % Falschfüllung auf 657 647 echten Orders |
| Teilfüllungen | **nicht modelliert** | — | offen |
| Marktimpact | **nicht modelliert** | — | offen |
| Cancel-/Replace-Latenz | **nicht modelliert** | — | offen |
| FX CHF/USDT | **nicht modelliert** | — | offen, siehe §6 |

### Eine Gegenrechnung zur Venue-Wahl

Liquid Co-Invest wäre 0,095 % Taker / 0,065 % Maker — das **1,7- bzw.
3,25-fache** der angesetzten Raten. Eine Maker-Runde dort kostet 0,13 % statt
0,04 %. Gegen einen Einstiegsvorsprung, dessen Obergrenze 0,0106 % ist, wäre
das kein Fortschritt.

## 6. P35, die Währung: strukturell benannt, der Betrag ungemessen

**Gemessen:** im Code gibt es keine Umrechnung. `QUOTE = "USDT"` ist eine
Konstante, die Konten heissen CHF, und keine Zeile wandelt.

**Strukturell**, und das braucht keine Kursreihe:

```
CHF-Rendite  =  (1 + USDT-Rendite) × (1 + FX-Änderung) − 1
```

Der FX-Term ist **additiv und unkorreliert** zum Handel. Für das 20×-Ziel ist
er zweiter Ordnung; für die gemessene Grössenordnung — der Median endet bei
657 von 1 000 — ist er erster Ordnung. Dazu einmalig die Wechselkosten
CHF→USDT bei Einzahlung und zurück bei Auszahlung.

**Offen, und ich habe es versucht:** eine freie öffentliche USD/CHF-Reihe war
nicht erreichbar (`api.frankfurter.app` 403 und 522, `exchangerate.host`
verlangt einen Schlüssel). Die Volatilität und damit die Streuung über 182
Tage ist deshalb **nicht gemessen**, und ich setze keine erinnerte Zahl ein.
Was fehlt, ist eine abrufbare Kursquelle — nicht eine Rechnung.

## 7. Die Zielarithmetik, aus dem bestehenden Skript reproduziert

`scripts/study_target_20x.py`, 413 Trades je Pfad, Quelle Replay:

| Szenario | Ziel am Ende | < Start | Median | CVaR 5 % | Liquidationen |
|---|---|---|---|---|---|
| gemessen, 0,5 % Risiko | 0,00 % | 88,6 % | 819 | 594 | 0,0 % |
| **gemessen, 1 % Risiko** | **0,00 %** | **89,7 %** | **657** | **347** | 0,0 % |
| gemessen, 2 % | 0,00 % | 91,7 % | 399 | 113 | 0,0 % |
| gemessen, 3 % (Deckel) | 0,01 % | 93,4 % | 224 | 35 | 0,0 % |
| 5 % (nur Stress) | 0,04 % | 96,0 % | 56 | 3 | 0,0 % |

**Die abgeleitete Hebelpolitik bestätigt sich.** Im gemessenen Szenario
**0,0 % Liquidationen** — weil der Hebel so gesetzt wird, dass die
Liquidation ≥ 2,5 Stop-Abstände hinter dem Stop liegt. Mit *festem* Hebel:

| fester Hebel | Liquidationen |
|---|---|
| 5× | **37,1 %** |
| 10× | **98,3 %** |
| 15× | **100 %** |

### Und die Zeile, die alles entscheidet

Das Skript rechnet auch **hypothetische** Vorteile durch:

| Vorteil je Trade | Endkapital nach 413 Trades |
|---|---|
| +0,05 R | 1 229 CHF |
| +0,10 R | 1 511 CHF |
| +0,20 R | 2 282 CHF |
| **+0,40 R** | **5 200 CHF** |
| **+0,73 R** | **20 000 CHF** ← das Ziel |

**Das Ziel verlangt +0,7280 R je Trade, 413 Trades hintereinander.** Gemessen:
−0,0906 R. Bester je gefundener Arm: −0,0340 R.

**Die Lücke ist 0,762 R je Trade.** Und das ist nicht eine Frage von „ein
bisschen besser werden": selbst ein Vorteil von **+0,40 R** — fünf- bis
zehnmal mehr, als gute Systeme in der Literatur ausweisen — endet bei 5 200
und damit bei einem Viertel des Ziels.

**Hebel hilft dabei nicht.** Der Deckel von 3 % hebt die Zielchance von
0,00 % auf 0,01 % und senkt den Median von 657 auf 224.

## 8. Befund von Phase 6

**Abgenommen:** die Börsenfilter sind live verifiziert; P38 ist entkräftet;
das Füllmodell ist gegen echte Fills validiert; die abgeleitete Hebelpolitik
verhindert Liquidationen, wo ein fester Hebel sie fast garantiert.

**Nicht abgenommen:** Teilfüllungen, Marktimpact, Cancel-/Replace-Latenz und
FX sind nicht modelliert. Die Gebührenraten sind nicht gegen die konkrete
Kontostufe verifiziert. Die Slippage-Annahme von 3 bp ist nicht gemessen.

**Das Abnahmekriterium von Phase 6** lautet: *„Wenn eine kleine Änderung der
Kosten das Vorzeichen kippt, ist der Edge nicht robust genug."* Es ist derzeit
**nicht anwendbar** — es gibt keinen Kandidaten mit positivem Vorzeichen, den
eine Kostenänderung kippen könnte.
