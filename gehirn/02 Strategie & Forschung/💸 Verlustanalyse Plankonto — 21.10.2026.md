---
typ: forschung
status: entschieden
aktualisiert: 2026-10-21
naechster_schritt: Händler neu starten, sobald das Konto flach ist — dann greift max_same_direction
tags: [verlust, groessenbemessung, risikodeckel, korrelation, plankonto]
---

# 💸 Verlustanalyse Plankonto — 21.10.2026

Das Plankonto steht bei **860,75 USD von 1.000**. Diese Notiz zerlegt den
Verlust in Posten, die sich addieren, und benennt getrennt davon, was eine
Gegenprobe ist und keine Summe.

Nachrechnen: `python scripts/verlustanalyse.py`

## Die Zerlegung

Über 19 geschlossene Trades:

```
Brutto (die Richtung, bei den gelaufenen Grössen)   -116.84 USD
Gebühren                                             -22.22 USD
Funding                                               -0.19 USD
--------------------------------------------------------------
Netto                                               -139.25 USD
```

Geprüft: `netto = brutto − Gebühren + Funding` stimmt auf den Cent, und
`R = netto / Risiko` auf vier Stellen.

## Der grösste Einzelposten: die Grössenasymmetrie

> [!important] 57 % des Verlusts sind Positionsgrösse, nicht Richtung
> Mit **gleichem Risiko je Trade** hätten dieselben R-Werte **−60,54 USD**
> ergeben statt −139,25. Die Asymmetrie allein kostet **78,70 USD**.

Risiko ist hier kein Eingabewert, sondern ein Ergebnis:

```
Nominal = Kapital × Margin-Anteil × Hebel      (fest)
Risiko  = Nominal × Stopweite                  (proportional zur Stopweite)
```

Gemessen:

| | Risiko je Trade | Stopweite |
|---|---|---|
| Gewinner | 8,86 USD | 0,435 % |
| Verlierer | 17,26 USD | 0,835 % |
| Faktor | **1,95×** | **1,92×** |

### Die Lehre, die man hier NICHT ziehen darf

„Weite Stops sind schlechter" wäre die naheliegende Schlussfolgerung und sie
hält nicht. In R gemessen:

```
enge Stops  (n=9, 0.134–0.452 %)   -0.0957 R     -1.83 USD   4/9 Treffer
weite Stops (n=10, 0.495–2.162 %)  -0.3414 R   -137.41 USD   3/10 Treffer
```

Der Unterschied ist **0,25 R bei n=19 und einer Streuung von 1,25 R** — weit
unter jeder Auflösung dieses Apparats. Die 137 USD gegen 1,83 USD waren die
**Positionsgrösse**, nicht die Trefferqualität. Ein Filter auf Stopweite wäre
eine Optimierung auf 19 Zeilen.

## Der Risikodeckel wirkt — gemessen über zwei Epochen

| | Risikospanne | Asymmetrie | Ergebnis |
|---|---|---|---|
| ohne Deckel (`plan30x7`, n=11) | 4,61–47,83 USD | 2,63× | −99,00 USD auf **+0,337 R** |
| mit 1,5 % (`…r15f`, n=8) | 2,55–13,29 USD | 1,39× | −40,24 USD auf **−4,612 R** |

Die zweite Epoche lief in R **viel schlechter** und kostete weniger als die
Hälfte. Das ist der Deckel bei der Arbeit — nicht eine bessere Strategie.

## Die Gleichzeitigkeit: 42 % der Trades aus zwei Kerzen

```
2 Fünfzehn-Minuten-Kerzen  →  8 von 19 Einstiegen  →  -90.61 USD
beide Kerzen gleichgerichtet
```

Am 20.10. starben vier Positionen in derselben Minute, alle vier long, mit
zusammen 145,55 USD Risiko = 13,8 % des Kontos.

`max_open_positions: 5` behandelt zwölf Perps als zwölf Wetten. Sie sind keine:
**E8 hat Beta 1,0 zu BTC gemessen**, mit verlässlich negativer Restrendite.
Fünf gleichgerichtete Positionen sind näherungsweise **eine** in fünffacher
Grösse — bei `margin_share 0.30` und Hebel 7 sind das 10,5× Kapital an Nominal
auf eine Wette.

> [!todo] Neu: `max_same_direction: 2`
> Steht **nur** in `config_offen` (Plankonto); in `config/` bleibt sie `None`.
> Senkt die Konzentration auf 4,2× Kapital. **Zwei und nicht drei**, weil die
> Margin ohnehin bei rund drei Positionen bindet — drei wäre fast nie wirksam
> und sähe nur so aus, als täte sie etwas.
>
> **Was sie kostet:** in einem Ausbruch wird der dritte gleichgerichtete Trade
> abgelehnt. Wer mehr handeln will, verliert hier welche.

## Haltedauer — nichts blockiert lange Trades

```
unter 2 h        18 Trades   -125.79 USD   -0.172 R   7/18 Treffer
2 bis 8 h         1 Trade      -13.45 USD   -1.181 R   0/1
8 h und länger    keine

Median 0.52 h (31 Minuten)   ·   längster Trade 4.08 h
```

**Es gibt keinen Zeitausstieg.** `max_hold_hours` ist nirgends gesetzt, steht
auf `None`. Trades laufen kurz, weil Stop und Ziel auf M15 nah beieinander
liegen und eines davon binnen einer halben Stunde getroffen wird — 12 endeten
am Stop, 7 am Ziel.

Der Hebel für längere Haltedauern wäre eine höhere Signalebene. Genau der wurde
gemessen und ist tot: **E17 prüfte Setup A auf D1+H4 auf 56 ungesehenen Märkten
und fiel** (+0,0341 R, Intervall über null). Siehe [[🧪 Experimentregister]].

## Woran die Trades endeten

```
stop      12x   -227.78 USD
target     7x    +88.53 USD

nie im Plus              10 von 19
vom Docht gestoppt        6 von 19
war +1 R und gab alles    1 von 19
```

## Je Setup — und warum daraus nichts folgt

```
Setup A   15x   -100.48 USD   +0.050 R   7/15
Setup G    3x    -24.03 USD   -1.308 R   0/3
Setup B    1x    -14.73 USD   -1.108 R   0/1
```

> [!warning] Keine dieser Zeilen rechtfertigt, ein Setup abzuschalten
> Setup F trug einmal 54 % des Gesamtverlusts über **68** Trades — das dafür
> aufgesetzte Experiment **E16 fiel trotzdem** (+0,0061 R, Intervall über
> null). F läuft weiter. Drei Verluste in Folge sind bei einer Münze jeder
> achte Fall.

## Die Kosten, und ein offener Punkt

22,22 USD Gebühren = 16 % des Verlusts. Dazu: **20 von 47 genommenen
Live-Signalen (43 %) liegen über dem alten Kostentor.** Seit die Tore auf
Wunsch offen sind, nimmt das System Trades, die die Replay-Regel abgelehnt
hätte.

Das ist kein Fehler, sondern die gemessene Folge einer getroffenen
Entscheidung — aber es steht gegen einen Befund aus 7.335 Trades: **billige
Trades haben die bessere BRUTTO-Erwartung** (+0,0561 R, Intervall schliesst
null aus), nicht bloss weniger Abgabe. Das Kostentor war also nicht nur eine
Kostenbremse.

**Offene Produktentscheidung:** Kostentor wieder schliessen (weniger Trades,
Befund aus 7.335 Zeilen im Rücken) oder offen lassen (mehr Trades, wie
gewünscht). Nicht einseitig entschieden.

## Was das alles nicht ändert

Die Erwartung je Trade ist über 7.335 Trades gemessen und liegt zwischen
**−0,087 und +0,059 R**. Keiner der Posten oben verschiebt diese Zahl; was die
Analyse zeigt, ist, wie viel von diesem Verlust **nicht** aus der Richtung kam.

## Verwandt

[[📊 Evidenzstand]] · [[🧪 Experimentregister]] · [[⚖ Risiko, Hebel & Kapital]] ·
[[🖥 Darkwood Terminal — Oberfläche & Bewertungsschicht]] · [[📌 Aktueller Stand]]
