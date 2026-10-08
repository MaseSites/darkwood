"""E8 -- Alpha oder Beta: traegt die Richtungswahl, oder traegt der Markt?

    python scripts/study_beta_alpha.py

**Warum diese Frage jetzt gestellt wird.** Der Vorwaertslauf steht nach 14
Trades bei +0.8023 R je Trade -- die erste positive Vorwaertszahl des Projekts.
Im selben Fenster fiel LINK 13.4 %, DOGE 12.2 %, ADA 6.0 %, BTC 4.4 %. Und die
Aufteilung nach Seite ist unmissverstaendlich:

    short  n=10   Mittel +1.0598 R   netto  +71.32
    long   n= 4   Mittel +0.1586 R   netto   -0.83

Beide Seiten wurden gehandelt, verdient hat nur die, die zur Marktrichtung
passte. Zwei Erklaerungen passen auf dieselbe Zahl, und sie fuehren zu
entgegengesetzten Entscheidungen:

  1. Das System waehlt die Richtung. Dann ist die Zahl ein Anfang.
  2. Das System war ueberwiegend short in einer Abwaertswoche. Dann ist die
     Zahl eine gehebelte Marktposition und sagt ueber das System nichts.

**Die Zerlegung.** Je Trade, nicht in Eimern nach Regime. Fuer jeden Trade wird
die BTC-Rendite ueber SEIN Haltefenster berechnet, mit dem Vorzeichen der
Trade-Seite versehen und durch die Stop-Weite geteilt -- damit steht sie in
derselben Einheit wie das Ergebnis, naemlich R. Dann:

    r_multiple ~ a + b * (seite * btc_rendite / stop_anteil)

`b` ist das Beta des Trades zum Kryptomarkt. `a` ist, was uebrig bleibt, wenn
die Marktbewegung erklaert ist.

**Warum gegen BTC und nicht gegen das eigene Symbol.** Gegen das eigene Symbol
ist die Frage fast tautologisch: wer short ist und dessen Symbol faellt,
gewinnt. Gegen BTC gerechnet ist der Rest genau die Auswahlleistung -- "dieses
Symbol fiel mehr, als sein Beta zu BTC erwarten liess, und wir waren auf der
richtigen Seite". Die Rechnung gegen das eigene Symbol laeuft trotzdem mit,
als Pruefung der Mechanik: dort MUSS `b` nahe 1 herauskommen, und wenn nicht,
ist das Skript falsch und nicht die Welt.

**Vorab festgelegt** (audit/EXPERIMENTS_NEXT.yaml, Arm E8, angelegt 2026-10-08
vor dem ersten Lauf):

  * Ein positives `b` bei einem Achsenabschnitt, dessen Intervall die Null
    enthaelt, ist ein NEGATIVES Ergebnis fuer diesen Arm.
  * Ein negatives `a` wird genauso berichtet wie ein positives.
  * Die 14 Live-Trades koennen das Tor nicht allein passieren. Bei dieser
    Stichprobe ist ein Intervall auf Niveau 0.05/48 breiter als jeder
    plausible Effekt. Das ist vorher bekannt und kein Grund, das Niveau
    nachher zu senken.
"""

from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import suggested_block

JOURNAL = ROOT / "data" / "journal.sqlite"
OHLCV = ROOT / "data" / "ohlcv"

#: Der Marktindex. Ein einzelnes Symbol und kein gewichteter Korb, weil BTC in
#: diesem Universum die gemeinsame Bewegung dominiert und ein selbstgebauter
#: Index eine Entscheidung mehr waere, die niemand geprueft hat.
BENCHMARK = "BTCUSDT"

#: Zeitebene der Benchmark-Reihe. M15 ist fein genug: der kuerzeste Trade im
#: Journal haelt fuenf Minuten, der Median etwa vierzehn Stunden.
FRAME = "M15"

#: Ein Kurs, der weiter als das zurueckliegt, gilt als nicht vorhanden. Ohne
#: diese Grenze wuerde ein Loch in der Benchmark-Reihe stillschweigend durch
#: einen alten Kurs gefuellt, und die Rendite waere erfunden.
STALE_MS = 2 * 15 * 60 * 1000

#: Bonferroni auf die 48 angemeldeten Vergleiche.
COMPARISONS = 48
LEVEL = 1.0 - 0.05 / COMPARISONS

#: Ziehungen je Intervall.
DRAWS = 4000

#: Unter so vielen Trades kein Intervall.
MIN_TRADES = 30

#: Fenstergrenzen aus `meta.windows` der Registrierung.
DEV_FROM, DEV_TO = "2025-10-01", "2026-03-31"
CONFIRM_FROM, CONFIRM_TO = "2026-04-01", "2026-10-06"

#: Unter diesem Betrag gilt ein Achsenabschnitt als null und das Verhaeltnis
#: der Replikation als nicht berechenbar -- sonst teilt man durch Rauschen.
NEAR_ZERO = 1e-9

#: Ein Stop-Anteil unter dieser Grenze ist kein Stop, sondern ein Rundungsrest.
#: Er stuende im Nenner und wuerde die Zelle allein bestimmen.
MIN_STOP_FRACTION = 1e-4


@dataclass
class Trade:
    symbol: str
    opened_ts: int
    closed_ts: int
    r_multiple: float
    side: int
    stop_fraction: float
    source: str


def series(symbol: str) -> tuple[np.ndarray, np.ndarray]:
    """Zeitstempel und Schlusskurse eines Symbols, aufsteigend."""
    files = sorted(glob.glob(str(OHLCV / symbol / FRAME / "*.parquet")))
    if not files:
        return np.array([], dtype="int64"), np.array([], dtype=float)
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame = frame.drop_duplicates(subset="ts").sort_values("ts")
    return frame.ts.to_numpy(dtype="int64"), frame.close.to_numpy(dtype=float)


def close_at(stamps: np.ndarray, closes: np.ndarray, ts: int) -> float | None:
    """Der letzte Schlusskurs bei oder vor `ts`, sonst None.

    Kein Vorwaertsfuellen ueber Loecher: liegt der letzte bekannte Kurs weiter
    als `STALE_MS` zurueck, gibt es fuer diesen Zeitpunkt keinen Kurs. Die
    Alternative waere eine Rendite, die zwei Kurse aus verschiedenen Stunden
    vergleicht und wie eine Messung aussieht.
    """
    i = int(np.searchsorted(stamps, ts, side="right")) - 1
    if i < 0:
        return None
    if ts - int(stamps[i]) > STALE_MS:
        return None
    return float(closes[i])


def load_trades() -> list[Trade]:
    """Trades aus dem Journal, mit Seite und Stop-Weite.

    Die Seite steht NICHT im Payload-Kopf, sondern in `reason`. Das ist eine
    Stelle, an der ich mich in dieser Sitzung schon geirrt habe: `payload.get
    ("side")` liefert fuer jeden Trade None, und eine Zaehlung darauf meldet
    stillschweigend "alles short".

    Die Stop-Weite ist ebenfalls nicht gespeichert und wird aus dem Risiko
    zurueckgerechnet: `risk_amount = qty * |entry - stop|`, also ist der
    Stop-Anteil `risk_amount / (qty * entry)`.
    """
    out: list[Trade] = []
    with sqlite3.connect(JOURNAL) as link:
        rows = link.execute(
            "select source, symbol, opened_ts, closed_ts, r_multiple, payload from trades"
        ).fetchall()
    for source, symbol, opened, closed, r, raw in rows:
        payload = json.loads(raw)
        side_word = payload.get("reason", {}).get("side")
        if side_word not in ("long", "short"):
            continue
        qty = float(payload["qty"])
        entry = float(payload["entry_price"])
        risk = float(payload["risk_amount"])
        if qty <= 0 or entry <= 0:
            continue
        fraction = risk / (qty * entry)
        if not np.isfinite(fraction) or fraction < MIN_STOP_FRACTION:
            continue
        out.append(
            Trade(
                symbol=symbol,
                opened_ts=int(opened),
                closed_ts=int(closed),
                r_multiple=float(r),
                side=1 if side_word == "long" else -1,
                stop_fraction=fraction,
                source=source,
            )
        )
    out.sort(key=lambda t: t.closed_ts)
    return out


def market_in_r(trades: list[Trade], *, against: str | None) -> tuple[np.ndarray, np.ndarray, int]:
    """Marktbewegung je Trade in R, und das Ergebnis daneben.

    `against=None` rechnet gegen das eigene Symbol des Trades, sonst gegen die
    genannte Benchmark. Trades ohne Kurs an einem der beiden Enden fallen aus
    und werden gezaehlt, nicht verschwiegen.
    """
    cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    xs: list[float] = []
    ys: list[float] = []
    dropped = 0
    for trade in trades:
        symbol = against or trade.symbol
        if symbol not in cache:
            cache[symbol] = series(symbol)
        stamps, closes = cache[symbol]
        if stamps.size == 0:
            dropped += 1
            continue
        start = close_at(stamps, closes, trade.opened_ts)
        end = close_at(stamps, closes, trade.closed_ts)
        if start is None or end is None or start <= 0:
            dropped += 1
            continue
        move = end / start - 1.0
        xs.append(trade.side * move / trade.stop_fraction)
        ys.append(trade.r_multiple)
    return np.array(xs, dtype=float), np.array(ys, dtype=float), dropped


def fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Achsenabschnitt und Steigung, kleinste Quadrate."""
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(coefficients[0]), float(coefficients[1])


def fit_bounds(
    x: np.ndarray, y: np.ndarray, *, level: float, seed: int = 11
) -> tuple[tuple[float, float], tuple[float, float], int]:
    """Block-Bootstrap-Intervalle fuer Achsenabschnitt und Steigung.

    Dieselbe Blockregel wie ueberall sonst im Projekt, auf dem Ergebnis
    gerechnet: Trades, die sich zeitlich ueberlappen, teilen ihre
    Marktbewegung, und ein iid-Bootstrap wuerde diese gemeinsame Bewegung als
    unabhaengige Evidenz zaehlen.
    """
    n = x.size
    length = max(1, min(suggested_block(y), n))
    starts_needed = int(np.ceil(n / length))
    generator = np.random.default_rng(seed)
    a_draws = np.empty(DRAWS, dtype=float)
    b_draws = np.empty(DRAWS, dtype=float)
    base = np.arange(length)
    for draw in range(DRAWS):
        starts = generator.integers(0, n, size=starts_needed)
        index = ((starts[:, None] + base[None, :]) % n).ravel()[:n]
        a_draws[draw], b_draws[draw] = fit(x[index], y[index])
    half = (1.0 - level) / 2.0
    a_low, a_high = np.percentile(a_draws, [100 * half, 100 * (1 - half)])
    b_low, b_high = np.percentile(b_draws, [100 * half, 100 * (1 - half)])
    return (float(a_low), float(a_high)), (float(b_low), float(b_high)), length


def cell(
    name: str, trades: list[Trade], *, against: str | None, level: float
) -> tuple[float, float] | None:
    """Eine Zelle rechnen und drucken. Gibt (a, b) zurueck, oder None."""
    x, y, dropped = market_in_r(trades, against=against)
    label = against or "eigenes Symbol"
    if x.size < MIN_TRADES:
        print(
            f"  {name:34s} n={x.size:<5} gegen {label:9s} -- unter {MIN_TRADES}, "
            f"kein Intervall"
        )
        if x.size >= 2:  # noqa: PLR2004
            a, b = fit(x, y)
            print(f"  {'':34s} nur die Punktschaetzung: a={a:+.4f} R, b={b:+.3f}")
        return None
    a, b = fit(x, y)
    (a_low, a_high), (b_low, b_high), block = fit_bounds(x, y, level=level)
    excludes = "JA " if (a_low > 0 or a_high < 0) else "nein"
    print(
        f"  {name:34s} n={x.size:<5} gegen {label:9s} (Block {block}, "
        f"{dropped} ohne Kurs)"
    )
    print(f"  {'':34s}   a = {a:+.4f} R  [{a_low:+.4f}, {a_high:+.4f}]  Null aus: {excludes}")
    print(f"  {'':34s}   b = {b:+.3f}    [{b_low:+.3f}, {b_high:+.3f}]")
    return a, b


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", type=float, default=LEVEL)
    args = parser.parse_args()

    trades = load_trades()
    if not trades:
        raise SystemExit("Keine Trades mit Seite und Stop-Weite im Journal.")

    live = [t for t in trades if t.source == "live"]
    replay = [t for t in trades if t.source != "live"]

    def between(group: list[Trade], start: str, stop: str) -> list[Trade]:
        lo = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        hi = int(pd.Timestamp(stop + " 23:59:59", tz="UTC").timestamp() * 1000)
        return [t for t in group if lo <= t.closed_ts <= hi]

    print("=" * 86)
    print("E8 -- Alpha oder Beta")
    print("=" * 86)
    print(
        f"\n  {len(trades):,} Trades mit Seite und Stop-Weite "
        f"({len(replay):,} Replay, {len(live):,} Live)\n"
        f"  Benchmark {BENCHMARK} auf {FRAME}, Niveau {100 * args.level:.4f}% "
        f"(Bonferroni auf {COMPARISONS})\n"
        f"\n  a = was uebrig bleibt, wenn die Marktbewegung erklaert ist, in R.\n"
        f"  b = Beta des Trades zum Markt.\n"
    )

    print("-" * 86)
    print("  Pruefung der Mechanik: gegen das EIGENE Symbol muss b nahe 1 liegen.")
    print("-" * 86)
    cell("alle Trades", trades, against=None, level=args.level)

    print()
    print("-" * 86)
    print("  Die beiden angemeldeten Zellen")
    print("-" * 86)
    cell("E8.1  alle Journal-Trades", trades, against=BENCHMARK, level=args.level)
    print()
    cell("E8.2  nur Live (vorwaerts)", live, against=BENCHMARK, level=args.level)

    print()
    print("-" * 86)
    print("  Replikation (Tor 2): Entwicklungs- gegen Bestaetigungsfenster")
    print("-" * 86)
    dev = cell(
        f"Entwicklung {DEV_FROM}..{DEV_TO[-5:]}",
        between(replay, DEV_FROM, DEV_TO),
        against=BENCHMARK,
        level=args.level,
    )
    print()
    confirm = cell(
        f"Bestaetigung {CONFIRM_FROM}..{CONFIRM_TO[-5:]}",
        between(replay, CONFIRM_FROM, CONFIRM_TO),
        against=BENCHMARK,
        level=args.level,
    )
    if dev and confirm and abs(dev[0]) > NEAR_ZERO:
        ratio = confirm[0] / dev[0]
        band = "IM BAND" if 0.5 <= ratio <= 2.0 else "AUSSERHALB"  # noqa: PLR2004
        print(f"\n  Verhaeltnis der Achsenabschnitte: {ratio:+.2f}x  -- {band} (0.5-2.0x)")
        if ratio < 0:
            print("    Ein negatives Verhaeltnis ist ein Vorzeichenwechsel, kein kleines Mass.")

    print()
    print("=" * 86)
    print(
        "  Lesehilfe, vorab festgelegt: ein positives b mit einem a, dessen\n"
        "  Intervall die Null enthaelt, heisst *gehebelte Marktposition ohne\n"
        "  eigenen Beitrag* -- und ist fuer diesen Arm ein negatives Ergebnis."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
