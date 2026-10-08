"""E0 Punkt 3: Überträgt sich ein Signal von der alten auf die neue Venue?

    python scripts/study_cross_venue.py
    python scripts/study_cross_venue.py --markets BTC --grid 1000

**Die Frage, und warum sie die letzte mit positivem Vorzeichen ist.** Die
Taker-Runde auf BTC kostet auf der neuen Venue 0,0005 % -- 22x unter der
Obergrenze des gemessenen Einstiegsvorsprungs, wo die alte Börse 3,8x
darüber lag. Das ist die einzige Grösse in diesem Projekt, die sich
zugunsten des Systems bewegt hat. Sie ist nur dann etwas wert, wenn ein
Signal, das auf Binance-Daten entsteht, dort auch ausführbar ist.

Der Auftrag fragt es in E0 Punkt 3: *„Baue denselben Snapshot separat aus
den Daten der neuen Venue. Teste danach Signale, die auf der bisherigen
Venue entstehen, mit einer zeitlich korrekt empfangenen Ausführung auf der
neuen."*

**Was dieses Skript beantwortet und was nicht.** Es misst die Beziehung der
beiden Preispfade: Niveau-Differenz, Korrelation der Renditen, und ob einer
dem anderen vorausläuft. Es rechnet **keine Signale** -- das wäre der
nächste Schritt und braucht Signale, die im Aufnahmefenster entstehen.

## Drei Dinge, die sonst einen Artefakt messen

**Die Uhr muss die Börsenzeit sein, nicht die Empfangszeit.** Gemessen am
07.10.2026: Empfang minus Börsenzeit liegt im Median bei **2,10 s** auf der
neuen Venue und **23,53 s** auf Binance. Das sind meine Poll-Intervalle
(2,9 s und 30 s), nicht die Latenz der Börsen. Eine Lead-Lag-Rechnung auf
Empfangszeiten würde messen, wie oft ich gefragt habe.

**Ein Versatz der Korrelation ist nicht automatisch ein Vorlauf.** Fällt das
Maximum der Kreuzkorrelation auf einen Versatz ungleich null, kann das ein
echter Vorlauf sein **oder** ein Gangunterschied der beiden
Börsen-Uhren. Diese Daten können die beiden **nicht** trennen, und das
Ergebnis wird so berichtet. Wer das auflösen will, braucht eine
gemeinsame Referenzuhr -- NTP-gestempelte Empfangszeiten aus einem
Streaming-Collector, nicht aus Polling.

**Binance-`aggTrades` aggregiert.** Eine Zeile kann viele Einzeltrades
zusammenfassen, also sind die Zeilenzahlen der beiden Tapes nicht
vergleichbar (28 906 gegen 2 156 im ersten Fenster). Für den Preispfad ist
das gleichgültig; für jede Zählung von Trades ist es es nicht.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import block_bootstrap

VENUE_TAPE = ROOT / "data" / "quarantine" / "venue_tape"
BINANCE_TAPE = ROOT / "data" / "quarantine" / "binance_tape"

#: Welcher Binance-Markt zu welchem Venue-Symbol gehört.
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}

#: Rasterweite in ms. Eine Sekunde: fein genug, dass ein Vorlauf von
#: Sekundenbruchteilen sichtbar wird, grob genug, dass beide Tapes in den
#: meisten Zellen einen Preis haben.
GRID_MS = 1_000

#: Versatzbereich der Kreuzkorrelation, in Rasterschritten.
MAX_LAG = 10

#: Unter so vielen gemeinsamen Zellen wird nichts geschätzt.
MIN_CELLS = 300

#: Unter diesem Anteil belegter Zellen gilt die Spanne als loechrig und
#: wird als solche gemeldet.
HOLE_SHARE = 0.9


@dataclass(frozen=True, slots=True)
class PricePath:
    """Ein Preispfad auf einem festen Raster."""

    label: str
    grid: np.ndarray
    price: np.ndarray


def read_tape(folder: Path, *, ts_field: str, price_field: str) -> tuple[np.ndarray, np.ndarray]:
    stamps: list[int] = []
    prices: list[float] = []
    for path in sorted(folder.glob("trades-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for row in json.loads(line)["trades"]:
                stamps.append(int(row[ts_field]))
                prices.append(float(row[price_field]))
    order = np.argsort(np.array(stamps, dtype="int64"), kind="stable")
    return np.array(stamps, dtype="int64")[order], np.array(prices, dtype=float)[order]


def to_grid(stamps: np.ndarray, prices: np.ndarray, *, grid_ms: int) -> PricePath | None:
    """Letzter Preis je Rasterzelle. Zellen ohne Trade bleiben leer.

    Kein Vorwärtsfüllen: eine leere Zelle heisst "kein Handel", und einen
    Preis hineinzuschreiben wuerde eine Beobachtung erfinden. Der Vergleich
    läuft nur über Zellen, in denen BEIDE Seiten gehandelt haben.
    """
    if stamps.size == 0:
        return None
    cells = stamps // grid_ms
    first, last = int(cells[0]), int(cells[-1])
    grid = np.arange(first, last + 1, dtype="int64")
    price = np.full(grid.size, np.nan)
    price[cells - first] = prices  # letzter Schreiber gewinnt = letzter Preis
    return PricePath(label="", grid=grid, price=price)


def align(a: PricePath, b: PricePath) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Gemeinsame Zellen, in denen beide einen Preis haben."""
    low = max(int(a.grid[0]), int(b.grid[0]))
    high = min(int(a.grid[-1]), int(b.grid[-1]))
    if high <= low:
        return np.array([]), np.array([]), np.array([])
    grid = np.arange(low, high + 1, dtype="int64")
    pa = a.price[grid - int(a.grid[0])]
    pb = b.price[grid - int(b.grid[0])]
    both = ~np.isnan(pa) & ~np.isnan(pb)
    return grid[both], pa[both], pb[both]


def cross_correlate(ra: np.ndarray, rb: np.ndarray, *, max_lag: int) -> list[tuple[int, float]]:
    """Korrelation von `ra` gegen ein verschobenes `rb`, je Versatz.

    Positiver Versatz heisst: `rb` wird nach VORNE geschoben, also passt
    `rb` von später zu `ra` von jetzt -- `ra` läuft dann voraus.
    """
    out: list[tuple[int, float]] = []
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = ra[-lag:], rb[: rb.size + lag]
        elif lag > 0:
            x, y = ra[: ra.size - lag], rb[lag:]
        else:
            x, y = ra, rb
        if x.size < MIN_CELLS or np.std(x) == 0 or np.std(y) == 0:
            out.append((lag, float("nan")))
            continue
        out.append((lag, float(np.corrcoef(x, y)[0, 1])))
    return out


def one_pair(symbol: str, binance: str, *, grid_ms: int) -> None:
    v_stamps, v_prices = read_tape(
        VENUE_TAPE / symbol, ts_field="timestamp", price_field="price"
    )
    b_stamps, b_prices = read_tape(BINANCE_TAPE / binance, ts_field="T", price_field="p")
    if v_stamps.size == 0 or b_stamps.size == 0:
        print(f"  {symbol:5s} ein Tape ist leer ({v_stamps.size} / {b_stamps.size})")
        return

    venue = to_grid(v_stamps, v_prices, grid_ms=grid_ms)
    other = to_grid(b_stamps, b_prices, grid_ms=grid_ms)
    if venue is None or other is None:
        return
    grid, pv, pb = align(venue, other)
    if grid.size < MIN_CELLS:
        print(f"  {symbol:5s} nur {grid.size} gemeinsame Zellen -- unter {MIN_CELLS}")
        return

    # Spanne UND Abdeckung, nie nur die Spanne.
    #
    # Die Aufnahme lief in der Nacht vom 07./08.10. eine Stunde, fiel aus und
    # wurde am Morgen neu gestartet. Beide Fenster liegen in denselben
    # Verzeichnissen, also haette "ueber 13.9h" dagestanden, wo 1.7h Daten
    # sind. Eine Spanne ohne ihre Abdeckung ist eine Einladung, ein Loch fuer
    # eine Messung zu halten.
    span = (grid[-1] - grid[0]) * grid_ms / 3_600_000
    covered = grid.size * grid_ms / 3_600_000
    print(f"\n{symbol} gegen {binance}  --  {grid.size:,} gemeinsame "
          f"{grid_ms / 1000:.0f}s-Zellen")
    print(f"  Spanne {span:.2f}h, davon belegt {covered:.2f}h "
          f"({100 * covered / max(1e-9, span):.1f} %)")
    if covered < HOLE_SHARE * span:
        blocks = int(np.sum(np.diff(grid) > 1)) + 1
        print(
            f"  ! Die Zellen liegen in {blocks} getrennten Bloecken. Alles unten\n"
            f"    rechnet nur ueber belegte Zellen, aber die Spanne oben ist\n"
            f"    KEINE Aufnahmedauer."
        )
    print(f"  Trades: Venue {v_stamps.size:,}  Binance {b_stamps.size:,} "
          f"(aggregiert, nicht vergleichbar)")

    # Niveau: handelt die neue Venue systematisch darueber oder darunter?
    basis_bp = 10_000 * (pv - pb) / pb
    interval = block_bootstrap(basis_bp.tolist(), level=0.95)
    lo = interval.low if interval else float("nan")
    hi = interval.high if interval else float("nan")
    print(
        f"  Niveau-Differenz (Venue minus Binance): {np.mean(basis_bp):+.3f} bp "
        f"[{lo:+.3f}, {hi:+.3f}]"
    )
    print(f"    Median {np.median(basis_bp):+.3f} bp   "
          f"p5 {np.percentile(basis_bp, 5):+.3f}   p95 {np.percentile(basis_bp, 95):+.3f}")

    # Renditen auf dem gemeinsamen Raster. Nur aufeinanderfolgende Zellen,
    # sonst ist die "Rendite" eine Luecke unbekannter Laenge.
    step = np.diff(grid) == 1
    rv = np.diff(np.log(pv))[step]
    rb = np.diff(np.log(pb))[step]
    print(f"  Aufeinanderfolgende Zellenpaare: {rv.size:,}")
    if rv.size < MIN_CELLS:
        print("    zu wenige fuer die Kreuzkorrelation")
        return

    print(f"  Korrelation der Renditen, Versatz 0: {np.corrcoef(rv, rb)[0, 1]:+.4f}")
    lags = cross_correlate(rv, rb, max_lag=MAX_LAG)
    usable = [(lag, c) for lag, c in lags if not np.isnan(c)]
    if not usable:
        print("    kein Versatz hatte genug Zellen")
        return
    best_lag, best = max(usable, key=lambda kv: abs(kv[1]))
    print("  Kreuzkorrelation je Versatz (in Zellen):")
    line = "    " + "  ".join(
        f"{lag:+d}:{c:+.3f}" for lag, c in usable if abs(lag) <= 5  # noqa: PLR2004
    )
    print(line)
    direction = (
        "gleichzeitig"
        if best_lag == 0
        else (f"die neue Venue laeuft {best_lag} Zelle(n) VORAUS" if best_lag > 0
              else f"Binance laeuft {-best_lag} Zelle(n) VORAUS")
    )
    print(f"  Maximum bei Versatz {best_lag:+d} ({best:+.4f}) -- {direction}")
    if best_lag != 0:
        print(
            "    ! Ein Versatz ungleich null ist NICHT automatisch ein Vorlauf.\n"
            "      Er kann auch ein Gangunterschied der beiden Boersen-Uhren sein,\n"
            "      und diese Daten trennen die beiden nicht. Dafuer braucht es eine\n"
            "      gemeinsame Referenzuhr aus einem Streaming-Collector."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", default="BTC,ETH")
    parser.add_argument("--grid", type=int, default=GRID_MS)
    args = parser.parse_args()

    print("=" * 84)
    print("E0 Punkt 3 -- die beiden Preispfade auf einem Raster")
    print("=" * 84)
    print(
        f"\n  Raster {args.grid / 1000:.0f}s, Uhr = BOERSENZEIT.\n"
        f"  Die Empfangszeiten sind hier nutzlos: Empfang minus Boersenzeit liegt\n"
        f"  bei 2.10s (neue Venue) und 23.53s (Binance) -- das sind MEINE\n"
        f"  Poll-Intervalle und nicht die Latenz der Boersen.\n"
    )

    for symbol in [s.strip().upper() for s in args.markets.split(",") if s.strip()]:
        binance = PAIRS.get(symbol)
        if binance is None:
            print(f"  {symbol}: kein Binance-Gegenstueck angemeldet")
            continue
        one_pair(symbol, binance, grid_ms=args.grid)

    print(
        "\n" + "=" * 84 + "\n"
        "  Was das noch nicht ist\n" + "=" * 84 + "\n"
        "\n  Keine Signalrechnung. Hier stehen die beiden Preispfade und ihre\n"
        "  Beziehung; E0 Punkt 3 verlangt daruhinaus, Signale, die im\n"
        "  Aufnahmefenster auf Binance-Daten ENTSTEHEN, auf der neuen Venue\n"
        "  auszufuehren. Dafuer braucht es Signale aus genau diesem Fenster --\n"
        "  der Papierhaendler erzeugt sie, aber mit ~1.9 Trades am Tag sind es\n"
        "  ueber eine Nacht eine Handvoll. Die Methode liesse sich daran\n"
        "  zeigen, ein Ergebnis nicht."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
