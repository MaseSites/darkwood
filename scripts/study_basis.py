"""Was der Carry nach Basisrisiko, Gebühren und Margin wirklich übrig lässt.

    python scripts/study_basis.py
    python scripts/study_basis.py --symbols BNBUSDT,LINKUSDT --hold 30

**Die Rechnung, die vorher fehlte.** Funding-Carry ist der einzige gemessene
Ertrag dieses Projekts ohne Richtungswette: +5,5 % bis +14,8 % p.a. aufs
Notional, 11 von 12 Märkten mit Intervall über Null. Diese Zahl ist die
Einnahme. Sie ist nicht der Ertrag.

Drei Dinge fehlen ihr, und alle drei ziehen ab:

**1. Die Basis ist das ganze Preisrisiko.** Mit Spot long und Perp short zu
je `q` ist der Preis-PnL

    q*(Spot_aus - Spot_ein) + q*(Perp_ein - Perp_aus)
      = q*((Perp_ein - Spot_ein) - (Perp_aus - Spot_aus))
      = q*(b_ein - b_aus)

Alles andere kürzt sich. Der gehedgte Trade verdient also **genau die
Verengung der Basis** und verliert ihre Ausweitung — die Kursrichtung
kommt nicht vor, und das ist der Punkt der Konstruktion. Wer den Carry ohne
diesen Term rechnet, hat die Einnahme gemessen und die Gefahr weggelassen.

**2. Die Maut fällt auf beiden Beinen und zweimal.** Rein und raus, Spot
und Perp. Bei den unterstellten Sätzen sind das 0,28 % je Runde — gegen
einen Jahresertrag von 5 bis 15 % ist das kein Rundungsfehler, sondern
zwei bis drei Wochen Carry.

**3. Gebundenes Kapital ist nicht das Notional.** Der Auftrag verlangt
ausdrücklich: *„Margin-Puffer gehört in den Nenner der Kapitalrendite."*
Das Spot-Bein bindet volles Kapital. Das Perp-Bein bindet Margin. Bei
Hebel 1 auf dem Short sind das zusammen **2x Notional**, und die Rendite
halbiert sich. Mehr Hebel senkt den Nenner und holt die Liquidation herein.

**Und die Liquidation wird NICHT weggehedgt.** Der Auftrag nennt den Fall
beim Namen: *„Liquidation des Short-Beins, während der Gewinn im
Spot-Bein liegt."* Unter isolierter Margin rettet der Spot-Gewinn das
Perp-Bein nicht — er liegt auf einem anderen Konto. Eine Verrechnung über
beide Beine ist ein Produktmerkmal der Börse und wird hier **nicht
unterstellt**; der Auftrag verbietet das ausdrücklich.

Gemessen wird darum der maximale Perp-ANSTIEG im Haltefenster, nicht die
Basis: liquidiert wird am Preis des Short-Beins.

**Grenzen, die jede Zahl unten trägt.** Nur die acht Märkte mit
Binance-Funding — Spot, Perp und Funding von einer Börse. Stündliche
Schlusskurse, keine Quotes: die echte Basis beim Eintritt ist die zwischen
Perp-Bid und Spot-Ask, und die ist um den halben Spread schlechter als
hier. Die Zahlen sind damit **optimistisch**, und um wie viel, sagt erst
der Orderbuch-Collector.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.reporting.intervals import block_bootstrap

SPOT_DIR = ROOT / "data" / "spot"
FUNDING_DIR = ROOT / "data" / "funding"

#: Die acht mit Binance-Funding. Dieselbe Liste wie in backfill_spot.py,
#: und aus demselben Grund: nur hier sind alle drei Reihen eine Börse.
MARKETS = (
    "ADAUSDT",
    "ATOMUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "LTCUSDT",
)

#: Binance-Taker, veröffentlichte Basisstufe. ANNAHME, keine Messung --
#: die eigene Stufe kann abweichen, und Maker würde beide Beine billiger
#: machen. Taker ist die konservative Wahl: eine Maker-Absicht ist keine
#: Maker-Ausführung, siehe audit/VENUE_KOSTEN_REPORT.md Abschnitt 6b.
FEE_SPOT = 0.001
FEE_PERP = 0.0004

#: Eine volle Runde: rein und raus, beide Beine.
ROUND_TRIP = 2 * (FEE_SPOT + FEE_PERP)

#: Erhaltungsmarge auf dem Short-Bein, konservativ gerundet. Liquidiert
#: wird, wenn der Perp um (1/Hebel - diese Rate) steigt.
MAINTENANCE = 0.005

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
YEAR_DAYS = 365.25


@dataclass(frozen=True, slots=True)
class Pair:
    """Eine Marktreihe mit Basis und Funding auf einem Raster."""

    symbol: str
    ts: np.ndarray
    spot: np.ndarray
    perp: np.ndarray
    #: Funding, das in DIESER Stunde anfällt (0 ausserhalb der Settlements).
    funding: np.ndarray

    @property
    def basis(self) -> np.ndarray:
        """(Perp - Spot) / Spot, als Anteil."""
        return (self.perp - self.spot) / self.spot


def load_pair(symbol: str, perp_store: ParquetStore) -> Pair | None:
    spot_store = ParquetStore(SPOT_DIR)
    spot = spot_store.read(symbol, Timeframe.H1)
    perp = perp_store.read(symbol, Timeframe.H1)
    if spot.empty or perp.empty:
        return None

    merged = spot[["ts", "close"]].merge(
        perp[["ts", "close"]], on="ts", how="inner", suffixes=("_spot", "_perp")
    )
    if merged.empty:
        return None

    path = FUNDING_DIR / f"{symbol}.parquet"
    rates = pd.read_parquet(path) if path.is_file() else pd.DataFrame(columns=["ts", "rate"])
    # Die Rate faellt zu ihrem Zeitstempel an; dazwischen ist sie null. Ein
    # Vorwaertsfuellen wuerde sie achtmal zaehlen.
    merged = merged.merge(rates[["ts", "rate"]], on="ts", how="left")
    merged["rate"] = merged["rate"].fillna(0.0)
    merged = merged.sort_values("ts").reset_index(drop=True)

    return Pair(
        symbol=symbol,
        ts=merged["ts"].to_numpy(dtype="int64"),
        spot=merged["close_spot"].to_numpy(dtype=float),
        perp=merged["close_perp"].to_numpy(dtype=float),
        funding=merged["rate"].to_numpy(dtype=float),
    )


@dataclass(frozen=True, slots=True)
class Holding:
    """Was ein Haltefenster einbringt, aufgeschlüsselt."""

    starts: int
    funding: np.ndarray
    basis_move: np.ndarray
    net_notional: np.ndarray
    worst_perp_rise: np.ndarray

    def net_on_capital(self, *, leverage: float) -> np.ndarray:
        """Rendite auf das GESAMT gebundene Kapital, nicht aufs Notional.

        Spot bindet 1 (voll bezahlt), der Short bindet 1/Hebel als Margin.
        Bei Hebel 1 ist der Nenner 2 und die Rendite halbiert sich -- das
        ist die Zeile, die in der alten Carry-Zahl fehlte.
        """
        return self.net_notional / (1.0 + 1.0 / leverage)

    def liquidated(self, *, leverage: float) -> float:
        """Anteil der Fenster, in denen das Short-Bein liquidiert worden waere."""
        distance = 1.0 / leverage - MAINTENANCE
        return float((self.worst_perp_rise >= distance).mean())


def walk(pair: Pair, *, hold_days: int, step_hours: int = 24) -> Holding | None:
    """Jedes Haltefenster dieser Länge, überlappend, mit Schrittweite.

    Überlappende Fenster sind stark abhängig; das Intervall kommt deshalb
    aus einem Blockbootstrap und nicht aus der Zahl der Fenster.
    """
    span = hold_days * 24
    if pair.ts.size <= span + 1:
        return None

    starts = np.arange(0, pair.ts.size - span, step_hours)
    if starts.size == 0:
        return None

    basis = pair.basis
    # Kumuliertes Funding, damit jedes Fenster eine Differenz zweier Zahlen ist.
    cumulative = np.concatenate([[0.0], np.cumsum(pair.funding)])

    collected = cumulative[starts + span] - cumulative[starts]
    # Der Short kassiert bei positiver Rate; das Vorzeichen ist bereits richtig.
    move = basis[starts + span] - basis[starts]
    net = collected - move - ROUND_TRIP

    worst = np.empty(starts.size)
    for i, start in enumerate(starts):
        window = pair.perp[start : start + span + 1]
        worst[i] = float(window.max() / window[0] - 1.0)

    return Holding(
        starts=int(starts.size),
        funding=collected,
        basis_move=move,
        net_notional=net,
        worst_perp_rise=worst,
    )


def annualise(value: float, *, hold_days: int) -> float:
    return value * YEAR_DAYS / hold_days


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(MARKETS))
    parser.add_argument("--hold", type=int, default=30, help="Haltedauer in Tagen")
    args = parser.parse_args()

    config = load_config()
    perp_store = ParquetStore(config.engine.paths.parquet_dir)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("=" * 104)
    print(f"E6.1 -- Carry nach Basis, Maut und Margin.  Haltedauer {args.hold} Tage")
    print("=" * 104)
    print(
        f"\n  Maut je Runde {100 * ROUND_TRIP:.3f}% (Spot {100 * FEE_SPOT:.2f}% + "
        f"Perp {100 * FEE_PERP:.2f}%, beide Beine, rein und raus) -- ANNAHME\n"
        f"  Preis-PnL des Paars = Verengung der Basis. Die Kursrichtung kuerzt sich.\n"
    )

    pairs: list[tuple[Pair, Holding]] = []
    for symbol in symbols:
        pair = load_pair(symbol, perp_store)
        if pair is None:
            print(f"  {symbol:10s} keine Spot- oder Perp-Reihe")
            continue
        held = walk(pair, hold_days=args.hold)
        if held is None:
            print(f"  {symbol:10s} zu kurz fuer {args.hold} Tage")
            continue
        pairs.append((pair, held))

    if not pairs:
        raise SystemExit("Kein Markt hatte beide Reihen. Zuerst scripts/backfill_spot.py.")

    print(f"  {'Markt':10s} {'Stunden':>8s} {'Basis Median':>13s} {'p5':>9s} {'p95':>9s} "
          f"{'| Funding':>11s} {'Basis-Bew.':>11s} {'Maut':>8s} {'= netto':>9s}")
    print("  " + "-" * 98)
    for pair, held in pairs:
        basis_bp = 10_000 * pair.basis
        print(
            f"  {pair.symbol:10s} {pair.ts.size:>8,} "
            f"{np.median(basis_bp):>12.2f}bp {np.percentile(basis_bp, 5):>8.1f} "
            f"{np.percentile(basis_bp, 95):>8.1f} "
            f"{100 * held.funding.mean():>10.3f}% {-100 * held.basis_move.mean():>10.3f}% "
            f"{-100 * ROUND_TRIP:>7.3f}% {100 * held.net_notional.mean():>8.3f}%"
        )

    print(f"\n  Netto je {args.hold}-Tage-Fenster, aufs Notional, mit Intervall:")
    print(f"  {'Markt':10s} {'Fenster':>8s} {'netto':>9s} {'Intervall':>22s} "
          f"{'p.a.':>9s} {'Verlustanteil':>14s}")
    print("  " + "-" * 80)
    survivors = 0
    for pair, held in pairs:
        interval = block_bootstrap(held.net_notional.tolist(), level=0.95)
        low = interval.low if interval else float("nan")
        high = interval.high if interval else float("nan")
        good = low > 0
        survivors += int(good)
        mark = " *" if good else ""
        print(
            f"  {pair.symbol:10s} {held.starts:>8,} {100 * held.net_notional.mean():>8.3f}% "
            f"[{100 * low:>+7.3f}, {100 * high:>+7.3f}] "
            f"{100 * annualise(float(held.net_notional.mean()), hold_days=args.hold):>8.2f}% "
            f"{100 * float((held.net_notional < 0).mean()):>13.1f}%{mark}"
        )

    print("\n  Und jetzt der Nenner. Rendite p.a. auf GEBUNDENES Kapital, je Hebel")
    print("  des Short-Beins -- daneben, wie oft es liquidiert worden waere:")
    print(f"  {'Markt':10s} " + "".join(f"{f'{lev:g}x':>22s}" for lev in (1, 2, 3, 5)))
    print("  " + "-" * 98)
    for pair, held in pairs:
        cells = []
        for lev in (1.0, 2.0, 3.0, 5.0):
            annual = annualise(float(held.net_on_capital(leverage=lev).mean()), hold_days=args.hold)
            liq = held.liquidated(leverage=lev)
            cells.append(f"{100 * annual:>9.2f}% /{100 * liq:>6.1f}% liq")
        print(f"  {pair.symbol:10s} " + "".join(f"{c:>22s}" for c in cells))

    conclude(pairs, hold_days=args.hold, survivors=survivors)
    return 0


def conclude(pairs: list[tuple[Pair, Holding]], *, hold_days: int, survivors: int) -> None:
    """Die Einordnung, aus `main` ausgelagert.

    Nicht nur wegen der Anweisungsgrenze: die Tabellen sind Messung, dieser
    Block ist Lesart. Die beiden auseinanderzuhalten macht es schwerer,
    beim Anpassen des Textes versehentlich eine Zahl zu verschieben.
    """
    print("\n" + "=" * 104)
    print("  Was daraus folgt")
    print("=" * 104)

    best = max(pairs, key=lambda p: p[1].net_notional.mean())
    pooled = np.concatenate([h.net_notional for _, h in pairs])
    pooled_interval = block_bootstrap(pooled.tolist(), level=0.95)

    print(
        f"\n  Ueber alle {len(pairs)} Maerkte, {pooled.size:,} ueberlappende Fenster:\n"
        f"    netto je Fenster {100 * pooled.mean():+.4f}%  "
        f"[{100 * pooled_interval.low:+.4f}, {100 * pooled_interval.high:+.4f}]"
        if pooled_interval
        else f"\n  Ueber alle {len(pairs)} Maerkte: netto {100 * pooled.mean():+.4f}%"
    )
    print(
        f"    = {100 * annualise(float(pooled.mean()), hold_days=hold_days):+.2f}% p.a. aufs "
        f"Notional, {100 * annualise(float(pooled.mean()), hold_days=hold_days) / 2:+.2f}% "
        f"p.a. auf Kapital bei Hebel 1\n"
        f"    {100 * float((pooled < 0).mean()):.1f}% der Fenster sind negativ\n"
        f"    Maerkte mit Intervall ueber Null: {survivors} von {len(pairs)}"
    )
    print(
        f"\n  Bester Markt: {best[0].symbol} mit "
        f"{100 * best[1].net_notional.mean():+.3f}% je Fenster.\n"
        f"  Die Maut allein ist {100 * ROUND_TRIP:.3f}% -- bei dieser Haltedauer also\n"
        f"  {ROUND_TRIP / max(1e-9, abs(float(pooled.mean()))):.1f}x der mittlere Nettoertrag.\n"
        f"  Laenger halten verduennt die Maut und verlaengert die Zeit, in der die\n"
        f"  Basis gegen einen laufen kann. Das ist der Kompromiss, nicht ein Parameter\n"
        f"  zum Optimieren: --hold variieren und die Richtung lesen."
    )
    print(
        "\n  Und was hier NICHT drin ist: der halbe Spread auf beiden Beinen beim\n"
        "  Ein- und Austritt (Stundenschlusskurse, keine Quotes), Finanzierungskosten\n"
        "  des Spot-Beins, Transferzeit zwischen den Konten, und jede Verrechnung\n"
        "  der Margin ueber beide Beine -- die waere ein Produktmerkmal der Boerse\n"
        "  und wird nicht unterstellt. Alle vier ziehen ab. Die Zahlen oben sind\n"
        "  die optimistische Seite."
    )


if __name__ == "__main__":
    raise SystemExit(main())
