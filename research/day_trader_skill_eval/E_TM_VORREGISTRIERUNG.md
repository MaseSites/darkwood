# E-TM — Time-Machine-Filter auf 56 ungesehenen Märkten

**Vorregistrierung, geschrieben am 22.10.2026, bevor eine einzige Time-Machine-Zahl auf
`data/replay_fills_0311/` existiert.** Danach wird an Regel, Toren und Zahlen nichts geändert.

## Die Behauptung

Auf den 12 gesehenen Märkten (alter Stand `data/replay_fills`, 7 310 Trades) ergab der Filter
„Trades mit Stop-Tendenz weglassen“ −0,0012 R je Trade gegen −0,0111 R ohne Filter; der
Unterschied +0,0099 R [−0,0113, +0,0313] spannte null. Er war der beste von DREI
ausprobierten Filtern, also in-sample ausgewählt.

## Der Arm, unveränderlich

- Time Machine wie in `tm_on_ours.py`: 2 000 Replays, 59 Vortage M15, Tageszeit ±2 Slots,
  72 h Horizont, Stop vor Ziel, Pool endet vor dem Einstieg.
- `lean = p_ziel / (p_ziel + p_stop) − 1 / (1 + CRV)`.
- **Arm E-TM: Trade behalten, wenn `lean ≥ −0,05`.** Basis: alle Trades.
- Kennzahl: `r_multiple` aus dem Journal (netto, Gebühren und Funding enthalten).
- Trades ohne berechenbare Time Machine (zu wenig Vorlauf, `p_ziel + p_stop = 0`) fallen
  aus Arm UND Basis.

## Die Tore — BEIDE müssen halten

Intervalle zweiwegig geclustert nach Markt UND 7-Tage-Block (wie E17), Bonferroni über
**86** Vergleiche (Register `total_comparisons: 83` plus die drei in-sample ausprobierten
Filter), zweiseitig, z = Φ⁻¹(1 − 0,05/172).

1. **Absolut profitabel:** Das Intervall des Arm-Mittels auf den 56 ungesehenen Märkten liegt
   vollständig über null.
2. **Echte Verbesserung:** Das Intervall von (Arm-Mittel − Basis-Mittel) auf den ungesehenen
   Märkten liegt vollständig über null.

Unter 200 Trades im Arm auf den ungesehenen Märkten: UNENTSCHEIDBAR, nicht „gefallen“.

## Immer berichtet

Die 12 gesehenen Märkte auf demselben Stand `replay_fills_0311` (Vergleich, kein Tor),
Anteil behaltener Trades, schlechtester 7-Tage-Block, schlechtester Markt, größter
Rückgang in R, Anteil Märkte mit negativem Mittel.

## Erwartung, vorab gesagt

Eher fallen: Der in-sample-Unterschied spannte schon null, und die Time Machine korrelierte
dort negativ mit dem Ergebnis.
