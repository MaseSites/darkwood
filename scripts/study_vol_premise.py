"""E11 — die Prämisse des Volatilitäts-Overlays, bevor jemand eines baut.

    python scripts/study_vol_premise.py

Angemeldet in `audit/EXPERIMENTS_NEXT.yaml` am 11.10.2026, **vor dem ersten
Lauf**. `total_comparisons` dabei von 55 auf 58 erhöht, Niveau also
99,9138 %.

---

## Warum dieser Arm, nachdem acht Familien nichts ergeben haben

Die Literatursuche vom 11.10. hat in acht Ansatzfamilien **keinen einzigen**
Kandidaten gefunden, der die gegnerische Prüfung überlebt. Sie hat aber einen
Grund genannt, warum Volatilität trotzdem anders ist als alles, was dieses
Projekt bisher gezogen hat:

> Alle anderen Hebel — Hebel, Positionsgrösse, Trade-Zahl — sind
> **vorzeichenneutral**. Sie skalieren alles gleich und können die Summe nicht
> umdrehen. Ein volatilitäts-**konditionales** Overlay ist das nicht: es
> gewichtet Trades nach Vola-Zustand um und könnte das Vorzeichen theoretisch
> ändern.

Deshalb ist die sinnvolle Messung **nicht der Backtest des Overlays**, sondern
seine Prämisse. Moreira/Muir funktioniert nur, wenn die erwartete Rendite
*nicht* mit der Volatilität steigt. Das ist an der bereits genommenen
Trade-Population prüfbar — keine neuen Daten, kein neues Instrument, kein
neuer Codepfad, nur eine Gruppierungsvariable.

## Vorab festgelegte Lesart

Drei Zellen, je ein Terzil des Vola-Zustands bei Einstieg, gemessen an der
**Brutto**-Erwartung je Trade (`gross_pnl / risk_amount`, also vor Maut):

| Ausgang | Schluss |
|---|---|
| Erwartung **flach** in der Vola | das Overlay kauft Rand-Kontrolle, keinen Ertrag. Familie zu. |
| Erwartung **steigt** mit der Vola | das Overlay ist aktiv **schaedlich**. Familie zu. |
| Erwartung **fällt** mit der Vola | und nur dann lohnt ein Overlay-Backtest. |

**Und die Erwartungshaltung steht hier, damit sie hinterher nicht nachgebessert
wird:** selbst der dritte Ausgang hebt den Sharpe und dünnt den Rand,
verwandelt aber eine negative Brutto-Erwartung nicht in eine positive. Bei
-0,0906 R Entry-Erwartung und -0,20 R Vorwärts-Residuum neben dem Markt gibt
es nichts zu skalieren. Dieser Arm kann eine Familie **schliessen**, nicht
eine Kante finden.

## Wie der Vola-Zustand gemessen wird, und warum nicht einfacher

**Realisierte Tagesvolatilitaet ueber die 30 Tage vor dem Einstieg**, je Symbol,
aus den D1-Kerzen. Annualisiert, damit die Zahlen lesbar sind.

Die bequeme Alternative wäre `stop_distance_pct` aus dem Journal gewesen — die
steht schon da. Sie taugt nicht: der Stop wird **vom Setup** gesetzt, und ein
H4-Setup setzt ihn breiter als ein M15-Setup am selben Tag. Die Stop-Weite
vermischt also Volatilität mit Setup-Wahl, und genau diese Vermischung würde
das Ergebnis erzeugen, das man sucht.

**Nur gelesen.** Journal und Kerzen schreibgeschützt geöffnet.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.reporting.intervals import block_bootstrap, two_group_difference

#: Ab wann ein Unterschied zwischen den Terzilen nicht mehr "flach" heisst.
#: Vorab gesetzt, damit die Lesart nicht am Ergebnis justiert wird.
FLAT = 0.05

#: Kleinste Zellgroesse, unter der kein Intervall berichtet wird.
MIN_CELL = 30

#: Kleinste Gesamtzahl fuer drei Terzile.
MIN_TOTAL = 90

#: Fenster der realisierten Volatilität, in Tagen.
WINDOW = 30

#: Niveau nach Bonferroni auf die angemeldete Zahl der Vergleiche.
COMPARISONS = 58
LEVEL = 1.0 - 0.05 / COMPARISONS

DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class Trade:
    symbol: str
    opened_ts: int
    closed_ts: int
    gross_r: float
    net_r: float
    vol: float


def load_trades() -> list[tuple[str, int, int, float, float]]:
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'journal.sqlite'}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT symbol, opened_ts, closed_ts, r_multiple, payload FROM trades "
            "WHERE source != 'live' AND closed_ts IS NOT NULL ORDER BY opened_ts"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for symbol, opened, closed, net_r, payload in rows:
        d = json.loads(payload)
        risk = d.get("risk_amount") or 0.0
        gross = d.get("gross_pnl")
        if not risk or gross is None:
            continue
        out.append((symbol, opened, closed, gross / risk, net_r))
    return out


def vol_series(symbol: str, store: ParquetStore) -> tuple[np.ndarray, np.ndarray] | None:
    """Zeitstempel und annualisierte 30-Tage-Volatilität je Tagesbalken."""
    frame = store.read(symbol, Timeframe.D1)
    if frame.empty or len(frame) < WINDOW + 2:
        return None
    close = frame["close"].to_numpy(dtype="float64")
    ts = frame["ts"].to_numpy(dtype="int64")
    returns = np.diff(np.log(close))
    vol = np.full(returns.size, np.nan)
    for i in range(WINDOW, returns.size):
        vol[i] = returns[i - WINDOW : i].std(ddof=1) * np.sqrt(365.0)
    # Der Balken, zu dem die Volatilität gehoert, ist der NACH dem Fenster --
    # also ts[1:], weil diff eine Beobachtung verliert.
    return ts[1:], vol


def attach_vol(rows: list[tuple[str, int, int, float, float]]) -> list[Trade]:
    store = ParquetStore(ROOT / "data" / "ohlcv")
    cache: dict[str, tuple[np.ndarray, np.ndarray] | None] = {}
    out: list[Trade] = []
    for symbol, opened, closed, gross_r, net_r in rows:
        if symbol not in cache:
            cache[symbol] = vol_series(symbol, store)
        series = cache[symbol]
        if series is None:
            continue
        ts, vol = series
        # Der letzte Tagesbalken, der VOR dem Einstieg geschlossen hat.
        # Strikt kleiner, sonst liest die Volatilitaet den Einstiegstag mit.
        idx = int(np.searchsorted(ts, opened - DAY_MS, side="right")) - 1
        if idx < 0 or idx >= vol.size or not np.isfinite(vol[idx]):
            continue
        out.append(Trade(symbol, opened, closed, gross_r, net_r, float(vol[idx])))
    return out


def report_cell(label: str, trades: list[Trade], *, draws: int) -> float | None:
    values = [t.gross_r for t in trades]
    if len(values) < MIN_CELL:
        print(f"  {label:26s} n={len(values):>5}  zu wenige Beobachtungen")
        return None
    mean = statistics.fmean(values)
    interval = block_bootstrap(values, draws=draws, level=LEVEL)
    vols = [t.vol for t in trades]
    span = f"{100 * min(vols):.0f}-{100 * max(vols):.0f} %"
    if interval is None:
        print(f"  {label:26s} n={len(values):>5}  {mean:+.4f} R  (kein Intervall)  Vola {span}")
        return mean
    excludes = interval.low > 0 or interval.high < 0
    mark = "OHNE NULL" if excludes else "ueber die Null"
    print(f"  {label:26s} n={len(values):>5}  {mean:+.4f} R  "
          f"[{interval.low:+.4f}, {interval.high:+.4f}]  {mark:14s}  Vola {span}")
    return mean


def _preamble(draws: int) -> None:
    print("=" * 78)
    print("E11 -- steigt die Brutto-Erwartung mit der Volatilitaet?")
    print("=" * 78)
    print(f"\n  Niveau {100 * LEVEL:.4f} % (Bonferroni auf {COMPARISONS}), "
          f"{draws:,} Ziehungen, Blockbootstrap")
    print(f"  Vola: realisierte Tagesvolatilitaet ueber {WINDOW} Tage VOR dem Einstieg,")
    print("        annualisiert. Nicht die Stop-Weite -- die setzt das Setup.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=20000)
    args = parser.parse_args()
    _preamble(args.draws)

    rows = load_trades()
    trades = attach_vol(rows)
    print(f"  {len(rows):,} Replay-Trades gelesen, {len(trades):,} mit Vola-Zustand\n")
    if len(trades) < MIN_TOTAL:
        print("  Zu wenige Trades fuer drei Terzile.")
        return 1

    ordered = sorted(trades, key=lambda t: t.vol)
    third = len(ordered) // 3
    cells = (
        ("1 niedrigste Vola", ordered[:third]),
        ("2 mittlere Vola", ordered[third : 2 * third]),
        ("3 hoechste Vola", ordered[2 * third :]),
    )

    print("  Brutto-Erwartung je Terzil (vor Maut):\n")
    means = [report_cell(label, cell, draws=args.draws) for label, cell in cells]

    print("\n  Und netto, zur Einordnung:\n")
    for label, cell in cells:
        values = [t.net_r for t in cell]
        print(f"  {label:26s} n={len(values):>5}  {statistics.fmean(values):+.4f} R")

    # Nicht `any(... is None)` und danach weiterrechnen: das weiss der
    # Typpruefer nicht, und ein `type: ignore` an dieser Stelle waere genau
    # die Zusicherung, die er haette pruefen sollen.
    solid = [m for m in means if m is not None]
    if len(solid) != len(means):
        print("\n  Mindestens eine Zelle ist zu duenn. Kein Urteil.")
        return 1

    low, high = solid[0], solid[-1]
    slope = high - low
    print("\n" + "-" * 78)
    print(f"  Unterschied hoechstes minus niedrigstes Terzil: {slope:+.4f} R")

    # Zwei ueberlappende Intervalle zu vergleichen ist KEIN Test. Die Differenz
    # bekommt ihr eigenes Intervall, sonst ist die Lesart unten eine Erzaehlung
    # ueber Punktschaetzungen.
    gap = two_group_difference(
        [t.gross_r for t in cells[2][1]],
        [t.gross_r for t in cells[0][1]],
        level=LEVEL,
        draws=args.draws,
    )
    if gap is None:
        print("  Kein Intervall auf die Differenz -- dann gibt es kein Urteil.")
        return 1
    decided = gap.low > 0 or gap.high < 0
    print(f"  Intervall auf die Differenz: [{gap.low:+.4f}, {gap.high:+.4f}]  "
          f"{'OHNE NULL' if decided else 'ueber die Null'}")

    if not decided:
        print("\n  Vorab festgelegte Lesart, ehrlich angewandt:")
        print("    Die Punktschaetzung faellt, das Intervall auf die Differenz")
        print("    enthaelt aber die Null. Damit ist KEINER der drei Ausgaenge")
        print("    belegt -- weder flach, noch steigend, noch fallend.")
        print("\n  Die Praemisse ist auf diesen Daten NICHT entscheidbar. Ein")
        print("  Overlay-Backtest waere damit nicht begruendet, und die Familie")
        print("  ist nicht geschlossen, sondern unentschieden. Der Unterschied")
        print("  gehoert benannt: 'nichts gefunden' und 'nicht messbar' sind")
        print("  nicht dasselbe.\n")
        return 0

    print("\n  Vorab festgelegte Lesart:")
    if abs(slope) < FLAT:
        print("    FLACH -> das Overlay kauft Rand-Kontrolle, keinen Ertrag. Familie zu.")
    elif slope > 0:
        print("    STEIGT -> das Overlay ist aktiv SCHAEDLICH. Familie zu, Negativbefund.")
    else:
        print("    FAELLT -> und nur dann lohnt ein Overlay-Backtest.")
    print("\n  Und die Erwartungshaltung, die vor dem Lauf feststand: selbst der")
    print("  dritte Ausgang hebt den Sharpe und duennt den Rand, verwandelt aber")
    print("  eine negative Brutto-Erwartung nicht in eine positive.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
