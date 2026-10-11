# Das Ziel 12.000 → 15.000 bis 30.10.2026, gerechnet

**Stand 11.10.2026, 23:10 UTC.** Alle Zahlen aus `data/paper.sqlite` und
`data/journal.sqlite`, nachrechenbar.

---

## 1. Was fehlt

| | |
|---|---|
| Konto heute | **12.022,47 USDT** (zwölf Konten à ~1.002) |
| Ziel | 15.000,00 USDT |
| Fehlt | **2.977,53 USDT** = +24,8 % |
| Zeit | **18,1 Tage** |

## 2. Wie viele Trades das sind

24 Live-Trades über 9,4 Tage = **2,54 Trades pro Tag** über alle zwölf Konten.
Hochgerechnet auf 18,1 Tage: **46 Trades**.

Risiko je Trade: 1 % des *jeweiligen* Kontos, also **10,02 USDT**.

## 3. Was jeder Trade liefern müsste

$$\frac{2.977{,}53}{46 \times 10{,}02} = \mathbf{6{,}46\ R}$$

**Jeder Trade müsste im Mittel das 6,5-fache dessen einbringen, was er
riskiert.** Nicht der beste Trade — der Mittelwert, Verlierer eingerechnet.

Zum Vergleich, was gemessen ist:

| | Mittel | n |
|---|---|---|
| Live (Vorwärts) | **+0,0335 R** | 24 |
| Replay (2022–2026) | **−0,0348 R** | 2.734 |

Das korrigierte Intervall der 24 Live-Trades: **[−1,0491; +1,6939]**. Es ist
2,74 R breit und enthält die Null. **24 Trades sagen über die Erwartung
praktisch nichts** — weder dass sie positiv ist noch dass sie negativ ist.

## 4. Die Hochrechnung, in drei Lesarten

| Annahme | je Trade | Konto am 30.10. |
|---|---|---|
| gemessen live | +0,0335 R | **12.037,90** |
| optimistisch | +0,2000 R | 12.114,65 |
| Weltklasse | +0,5000 R | 12.252,93 |

Selbst eine Erwartung, die kein öffentlich dokumentiertes System dauerhaft
hält, endet bei **12.253 USDT**. Das Ziel liegt bei 15.000.

## 5. Umgekehrt gefragt: welches Risiko wäre nötig?

| bei | Risiko je Trade | Anteil des Einzelkontos |
|---|---|---|
| +0,20 R | 323,64 USDT | **32,3 %** |
| +0,50 R | 129,46 USDT | **12,9 %** |

Der harte Deckel in `config/risk.yaml` liegt bei **3 %**. 32,3 % wären eine
Überschreitung um den Faktor 10,8.

Und was der Deckel voll ausgenutzt hergibt — 3 % je Konto, 30,06 USDT je
Trade, bei optimistischen +0,20 R:

$$46 \times 30{,}06 \times 0{,}20 = +276{,}52 \text{ USDT} \;\rightarrow\; \mathbf{12.299\ USDT}$$

## 6. Das Urteil

**Das Ziel 15.000 bis zum 30.10. ist nicht erreichbar** — nicht bei einer
Risikoeinstellung, die der Deckel zulässt, und nicht bei einer Erwartung, die
dieses Projekt gemessen hat oder glaubwürdig behaupten könnte.

Drei Grössen können sich ändern, und nur drei:

1. **Die Frist.** Die Arithmetik geht über einen längeren Zeitraum auf — *wenn*
   die Erwartung wirklich positiv ist. Das ist der Punkt, der offen ist.
2. **Der Deckel.** 32,3 % je Trade. Die gemessene Verlustserie dieses Systems
   war sieben Trades; sieben Verluste à 32,3 % lassen **6,5 %** des Kontos
   übrig. Das ist keine Einstellung, das ist ein Totalverlust mit
   Zwischenschritten.
3. **Die Erwartung.** +6,46 R je Trade existiert in keinem belegten System.

**Was ich nicht tun werde:** den Deckel heben, um die Zahl zu erreichen. Die
Rechnung oben ist genau der Grund, warum der Deckel existiert — er ist nicht
das Hindernis vor dem Ziel, er ist der Grund, dass nach einem Fehlschlag noch
ein Konto da ist.

## 7. Was die 18 Tage stattdessen wert sind

Der Engpass ist nicht die Positionsgrösse. Der Engpass ist, dass **keine
positive Erwartung belegt ist**: das Intervall der Vorwärtsstichprobe spannt
von −1,05 bis +1,69 R.

Daran ändern 18 Tage mit 46 weiteren Trades wenig — 70 Trades haben ein
Intervall, das kaum schmaler ist. Was es ändert:

* **Die Datenbasis.** 124 Registereinträge sind auf zwölf Märkten gelaufen,
  die nach dem Versuchsbudget etwa 45 unabhängige Versuche tragen. 71 weitere
  Märkte nach einer vorab festgelegten Regel sind unterwegs
  (`scripts/universe_for_backfill.py`). Das ist der einzige Hebel, der die
  Statistik wirklich bewegt.
* **Die Risikomechanik.** Drei von sechs Sicherungen können in keinem Prozess
  auslösen (`audit/EVIDENZ_UND_RISIKO_AUDIT.md`, 3.1), und
  `max_open_positions` wird nirgends durchgesetzt — gerade sind drei
  Positionen offen, wo zwei konfiguriert sind. Wenn irgendwann grösser
  gehandelt wird, müssen diese Bremsen vorher echt sein.

Ein Datum zu halten, indem man das Risiko hebt, verschiebt nur, wann man es
merkt.
