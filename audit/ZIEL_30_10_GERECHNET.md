# Das Ziel 12.000 → 15.000 bis 30.10.2026, gerechnet

**Stand 11.10.2026, 23:10 UTC, korrigiert 23:40.** Alle Zahlen aus
`data/paper.sqlite` und `data/journal.sqlite`, nachrechenbar.

> **Korrektur.** Die erste Fassung rechnete mit **24** Live-Trades. Einer von
> ihnen, `live-BTCUSDT-1790928000000`, gehört nicht zum laufenden Konto: das
> Journal für BTCUSDT summiert auf 936,19 USDT, das Kontobuch sagt 991,24 —
> die Lücke ist auf den Rappen sein Nettoergebnis von −55,0482. Er hat
> `qty 0,06` gegen `qty 0,006` beim zweiten BTC-Trade, also die zehnfache
> Grösse, und **49,84 USDT Risiko auf ein 1.000-USDT-Konto = 4,98 %**, über
> dem harten Deckel von 3 %. Das Tally des Kontos zählt `opened: 1,
> closed: 1`. Er stammt aus einer zerstörten Kontogeneration. Details in
> `audit/RISIKO_AUDIT_NACHPRUEFUNG.md`, Abschnitt 1.
>
> Der Ausschluss macht die Zahl **besser** (+0,0829 statt +0,0335 R), also
> gehört die Begründung ausdrücklich dazu: sie steht auf der
> Buchabstimmung und der Deckelüberschreitung, nicht auf dem Ergebnis, und
> sie stand fest, bevor die Richtung bekannt war. Beide Fassungen sind unten
> aufgeführt.

---

## 1. Was fehlt

| | |
|---|---|
| Konto heute | **12.022,47 USDT** (zwölf Konten à ~1.002) |
| Ziel | 15.000,00 USDT |
| Fehlt | **2.977,53 USDT** = +24,8 % |
| Zeit | **18,1 Tage** |

## 2. Wie viele Trades das sind

**23** Live-Trades über 9,4 Tage = **2,45 Trades pro Tag** über alle zwölf
Konten. Hochgerechnet auf 18,1 Tage: **44 Trades**.

Risiko je Trade: 1 % des *jeweiligen* Kontos, also **10,02 USDT**.

## 3. Was jeder Trade liefern müsste

$$\frac{2.977{,}53}{44 \times 10{,}02} = \mathbf{6{,}75\ R}$$

**Jeder Trade müsste im Mittel das 6,75-fache dessen einbringen, was er
riskiert.** Nicht der beste Trade — der Mittelwert, Verlierer eingerechnet.

Zum Vergleich, was gemessen ist:

| | Mittel | n | korrigiertes Intervall |
|---|---|---|---|
| Live, bereinigt | **+0,0829 R** | 23 | [−1,0423; +1,7785] |
| Live, mit Waise | +0,0335 R | 24 | [−1,0491; +1,6939] |
| Replay (2022–2026) | **−0,0348 R** | 2.734 | |

Das Intervall ist in beiden Fassungen **2,7 R breit und enthält die Null**.
Dass der Ausschluss eines Verlierers den Mittelwert um 0,05 R hebt und das
Intervall unverändert über der Null lässt, ist selbst die Aussage: **23
Trades sagen über die Erwartung praktisch nichts** — weder dass sie positiv
ist noch dass sie negativ ist.

## 4. Die Hochrechnung, in drei Lesarten

| Annahme | je Trade | Konto am 30.10. |
|---|---|---|
| gemessen live, bereinigt | +0,0829 R | **12.059,01** |
| optimistisch | +0,2000 R | 12.110,63 |
| Weltklasse | +0,5000 R | 12.242,88 |

Selbst eine Erwartung, die kein öffentlich dokumentiertes System dauerhaft
hält, endet bei **12.243 USDT**. Das Ziel liegt bei 15.000.

## 5. Umgekehrt gefragt: welches Risiko wäre nötig?

| bei | Risiko je Trade | Anteil des Einzelkontos |
|---|---|---|
| +0,20 R | 338,36 USDT | **33,8 %** |
| +0,50 R | 135,34 USDT | **13,5 %** |

Der harte Deckel in `config/risk.yaml` liegt bei **3 %**. 33,8 % wären eine
Überschreitung um den Faktor 11,3.

Und was der Deckel voll ausgenutzt hergibt — 3 % je Konto, 30,06 USDT je
Trade, bei optimistischen +0,20 R:

$$44 \times 30{,}06 \times 0{,}20 = +264{,}50 \text{ USDT} \;\rightarrow\; \mathbf{12.287\ USDT}$$

## 6. Das Urteil

**Das Ziel 15.000 bis zum 30.10. ist nicht erreichbar** — nicht bei einer
Risikoeinstellung, die der Deckel zulässt, und nicht bei einer Erwartung, die
dieses Projekt gemessen hat oder glaubwürdig behaupten könnte.

Drei Grössen können sich ändern, und nur drei:

1. **Die Frist.** Die Arithmetik geht über einen längeren Zeitraum auf — *wenn*
   die Erwartung wirklich positiv ist. Das ist der Punkt, der offen ist.
2. **Der Deckel.** 33,8 % je Trade. Die gemessene Verlustserie dieses Systems
   war sieben Trades; sieben Verluste à 33,8 % lassen **5,5 %** des Kontos
   übrig. Das ist keine Einstellung, das ist ein Totalverlust mit
   Zwischenschritten.
3. **Die Erwartung.** +6,75 R je Trade existiert in keinem belegten System.

**Was ich nicht tun werde:** den Deckel heben, um die Zahl zu erreichen. Die
Rechnung oben ist genau der Grund, warum der Deckel existiert — er ist nicht
das Hindernis vor dem Ziel, er ist der Grund, dass nach einem Fehlschlag noch
ein Konto da ist.

## 7. Was die 18 Tage stattdessen wert sind

Der Engpass ist nicht die Positionsgrösse. Der Engpass ist, dass **keine
positive Erwartung belegt ist**: das Intervall der Vorwärtsstichprobe spannt
von −1,04 bis +1,78 R.

Daran ändern 18 Tage mit 44 weiteren Trades wenig — 67 Trades haben ein
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
