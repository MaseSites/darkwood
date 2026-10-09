"""E4V -- Vorprüfung von E4 auf dem Überlebenden-Satz. Ein Schirm, kein Ergebnis.

    python scripts/study_relative_value.py

**Was das ist und was es nicht ist.** E4 verlangt ein Punkt-in-Zeit-Universum
mit Kursen. Das fehlt: `data/universe/binance_um_perps.json` sagt, dass zu
jedem Zeitpunkt 232 bis 749 Perps handelbar waren, und auf der Platte liegen
Kurse für **zwölf**. Eine Querschnittsstudie darauf ist eine Studie der heute
liquidesten Überlebenden, nicht des Universums.

Dieses Skript rechnet sie trotzdem -- als **Schirm** mit einer klaren
Asymmetrie, vorab angemeldet als Arm E4V:

* **Negativ ist aussagekräftig.** Der Satz ist der liquideste und am stärksten
  überlebende, den es gibt. Eine Methode, die dort nichts findet, wird durch
  mehr Symbole nicht besser -- dann bleibt E4 blockiert und der grosse
  Kursdownload unterbleibt.
* **Positiv ist kein Befund**, sondern genau die Rechtfertigung für den
  Download. Die Richtung der Survivorship-Verzerrung ist bei Long/Short nicht
  vorab bestimmt, also taugt ein positives Ergebnis hier nicht als Beleg.

**Kausalität.** Der Faktor je Stichtag ist das Querschnittsmittel der
Tagesrenditen **dieses** Tages -- am Schluss bekannt. Das Beta je Markt kommt
aus einem rückwärtigen Fenster, das am Stichtag endet. Gehandelt wird von
Schluss `t` auf Schluss `t+1`. Keine Grösse aus der Zukunft.

**Vorzeichen steht vor dem Lauf fest:** Long das NIEDRIGSTE Residuum
(Reversion), short das höchste, dollar-neutral.
"""

from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import block_bootstrap

#: Bonferroni auf die 52 angemeldeten Vergleiche.
COMPARISONS = 52
LEVEL = 1.0 - 0.05 / COMPARISONS

#: Die zwölf Märkte mit Kursen. **Das ist der Überlebenden-Satz**, nicht ein
#: Universum: es sind die heute aktiven, liquidesten Perps.
MARKETS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOGEUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT",
)

#: Rückwärtiges Fenster für das Beta, in Tagen. Vor dem Lauf gesetzt und nicht
#: variiert -- ein zweiter Wert wäre ein zweiter Vergleich.
BETA_WINDOW = 60

#: Mindestzahl von Märkten an einem Stichtag, sonst kein Querschnitt.
MIN_CROSS = 6

#: Taker-Gebühr je Seite. Eine tägliche Umschichtung zahlt sie auf dem
#: Umschlag, nicht auf dem Bestand.
FEE = 0.00055

# Eine No-Trade-Zone steht in E4s `requirements` und ist hier NICHT
# implementiert -- bewusst, und der Grund gehoert hierher statt in eine tote
# Konstante: sie ueberspringt Tage, an denen das erwartete Brutto die Maut
# nicht deckt. Bei einem Signal, dessen Brutto im Mittel NEGATIV ist, fuehrt
# das gegen Null, nicht ins Positive. Sie kann ein falsches Vorzeichen nicht
# retten, nur seltener bezahlen.

#: Darunter gilt die erste Haelfte als null und das Replikationsverhaeltnis
#: als nicht berechenbar -- sonst teilt man durch Rauschen.
NEAR_ZERO = 1e-12

#: Fenstergrenzen aus `meta.windows`.
DEV_TO = "2026-03-31"
CONFIRM_FROM = "2026-04-01"


@dataclass(frozen=True, slots=True)
class Day:
    date: pd.Timestamp
    gross: float
    net: float
    turnover: float
    funding: float
    names: int


def daily_closes() -> pd.DataFrame:
    """Tagesschlusskurse der zwölf Märkte, eine Spalte je Markt."""
    series: dict[str, pd.Series] = {}
    for market in MARKETS:
        files = sorted(glob.glob(str(ROOT / "data" / "ohlcv" / market / "D1" / "*.parquet")))
        if not files:
            continue
        frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        frame = frame.drop_duplicates(subset="ts").sort_values("ts")
        index = pd.to_datetime(frame.ts, unit="ms", utc=True)
        series[market] = pd.Series(frame.close.to_numpy(dtype=float), index=index)
    return pd.DataFrame(series).sort_index()


def funding_by_day() -> pd.DataFrame:
    """Summierte Funding-Rate je Markt und Tag.

    Eine Position zahlt Funding je Abrechnung, nicht je Tag -- die Summe der
    drei Tagesabrechnungen ist die Tagesbelastung einer durchgehaltenen
    Position.
    """
    frames: dict[str, pd.Series] = {}
    folder = ROOT / "data" / "funding"
    for market in MARKETS:
        path = folder / f"{market}.parquet"
        if not path.is_file():
            continue
        frame = pd.read_parquet(path).drop_duplicates(subset="ts").sort_values("ts")
        index = pd.to_datetime(frame.ts, unit="ms", utc=True)
        series = pd.Series(frame.rate.to_numpy(dtype=float), index=index)
        frames[market] = series.resample("1D").sum()
    return pd.DataFrame(frames).sort_index()


def residuals(returns: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Residualrenditen nach einem kausal geschätzten Marktfaktor.

    Der Faktor ist das Querschnittsmittel der Renditen desselben Tages -- am
    Schluss bekannt, also keine Zukunft. Das Beta je Markt kommt aus einem
    rückwärtigen Fenster, das am Stichtag **endet**: `rolling(window)` auf
    Kovarianz und Varianz, beides bis einschliesslich `t`.

    Ein Beta, das aus dem ganzen Zeitraum geschätzt wird, wäre der klassische
    Fehler an dieser Stelle -- es kennt die Zukunft des Marktes.
    """
    factor = returns.mean(axis=1, skipna=True)
    out: dict[str, pd.Series] = {}
    variance = factor.rolling(window, min_periods=window).var()
    for market in returns.columns:
        covariance = returns[market].rolling(window, min_periods=window).cov(factor)
        beta = covariance / variance
        out[market] = returns[market] - beta * factor
    return pd.DataFrame(out)


def run_arm(
    returns: pd.DataFrame,
    resid: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    equal_weight: bool,
) -> list[Day]:
    """Einen Arm über alle Stichtage laufen lassen.

    `equal_weight=True` ist die Kontrolle: dasselbe Universum einfach gehalten,
    ohne Querschnittsentscheidung. Sie zahlt keine Umschichtung, weil sie
    nichts umschichtet.
    """
    dates = returns.index
    days: list[Day] = []
    previous = pd.Series(0.0, index=returns.columns)

    for i in range(len(dates) - 1):
        today, tomorrow = dates[i], dates[i + 1]
        signal = resid.loc[today].dropna()
        future = returns.loc[tomorrow]
        usable = signal.index.intersection(future.dropna().index)
        if len(usable) < MIN_CROSS:
            continue

        if equal_weight:
            weights = pd.Series(1.0 / len(usable), index=usable)
        else:
            # Long das NIEDRIGSTE Residuum, short das höchste. Dollar-neutral,
            # und das ist ausdrücklich NICHT automatisch beta-neutral -- diese
            # Falle steht in E4s `pitfalls_declared` und bleibt offen.
            ranked = signal.loc[usable].rank()
            middle = (len(usable) + 1) / 2.0
            tilt = -(ranked - middle)
            weights = tilt / tilt.abs().sum()

        gross = float((weights * future.loc[usable]).sum())

        aligned = previous.reindex(weights.index).fillna(0.0)
        turnover = float((weights - aligned).abs().sum())
        if not equal_weight:
            turnover += float(previous.drop(weights.index, errors="ignore").abs().sum())
        toll = turnover * FEE

        if today in funding.index:
            rates = funding.loc[today].reindex(weights.index).fillna(0.0)
            # Ein Long zahlt bei positiver Rate.
            funded = float(-(weights * rates).sum())
        else:
            funded = 0.0

        days.append(
            Day(
                date=tomorrow,
                gross=gross,
                net=gross - toll + funded,
                turnover=turnover,
                funding=funded,
                names=len(usable),
            )
        )
        previous = weights if not equal_weight else previous
    return days


def judge(name: str, days: list[Day], *, level: float) -> float | None:
    if len(days) < 30:  # noqa: PLR2004
        print(f"  {name:46s} nur {len(days)} Tage -- kein Intervall")
        return None
    net = [d.net for d in days]
    gross = [d.gross for d in days]
    interval = block_bootstrap(net, level=level)
    mean = float(np.mean(net))
    print(f"  {name:46s} n={len(days):,}")
    print(f"    brutto {1e4 * float(np.mean(gross)):>+8.2f} bp/Tag   "
          f"Umschlag {np.mean([d.turnover for d in days]):.2f}   "
          f"Funding {1e4 * np.mean([d.funding for d in days]):>+6.2f} bp")
    if interval is None:
        print(f"    netto  {1e4 * mean:>+8.2f} bp/Tag   kein Intervall")
        return mean
    excludes = interval.low > 0 or interval.high < 0
    print(f"    netto  {1e4 * mean:>+8.2f} bp/Tag  "
          f"[{1e4 * interval.low:>+8.2f}, {1e4 * interval.high:>+8.2f}]  "
          f"Null {'AUS' if excludes else 'enthalten'}  (Block {interval.block})")
    return mean


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", type=float, default=LEVEL)
    args = parser.parse_args()

    print("=" * 88)
    print("E4V -- Vorpruefung von E4 auf dem UEBERLEBENDEN-SATZ")
    print("=" * 88)
    print(
        "\n  Das ist KEIN E4. E4 verlangt ein Punkt-in-Zeit-Universum mit Kursen;\n"
        "  zu jedem Zeitpunkt waren 232 bis 749 Perps handelbar und auf der Platte\n"
        "  liegen zwoelf. Ein negatives Ergebnis hier ist aussagekraeftig, ein\n"
        "  positives nur die Rechtfertigung fuer den Kursdownload.\n"
        f"\n  Niveau {100 * args.level:.4f}% (Bonferroni auf {COMPARISONS}), "
        f"Beta-Fenster {BETA_WINDOW} Tage.\n"
    )

    closes = daily_closes()
    if closes.empty:
        raise SystemExit("Keine Tagesdaten gefunden.")
    returns = closes.pct_change().iloc[1:]
    funding = funding_by_day()
    resid = residuals(returns, window=BETA_WINDOW)

    print(f"  {len(returns):,} Tage, {returns.shape[1]} Maerkte, "
          f"{returns.index[0]:%Y-%m-%d} bis {returns.index[-1]:%Y-%m-%d}")
    print(f"  Funding vorhanden fuer {funding.shape[1]} Maerkte\n")
    print("-" * 88)

    arms = {
        "E4V.1 Residual-Reversion, 1 Tag": run_arm(returns, resid, funding, equal_weight=False),
        "E4V.2 Gleichgewichtet halten (Kontrolle)": run_arm(
            returns, resid, funding, equal_weight=True
        ),
    }
    means: dict[str, float | None] = {}
    for name, days in arms.items():
        means[name] = judge(name, days, level=args.level)
        print()

    # Tor 2: Replikation.
    print("-" * 88)
    print("  Replikation (Tor 2)")
    print("-" * 88)
    main_arm = next(iter(arms))
    days = arms[main_arm]
    early = [d for d in days if d.date <= pd.Timestamp(DEV_TO, tz="UTC")]
    late = [d for d in days if d.date >= pd.Timestamp(CONFIRM_FROM, tz="UTC")]
    halves = []
    for label, group in (("frueher", early), ("spaeter", late)):
        value = judge(f"  {main_arm} / {label}", group, level=args.level)
        halves.append(value)
        print()
    if all(h is not None for h in halves) and abs(halves[0]) > NEAR_ZERO:
        ratio = halves[1] / halves[0]
        band = "IM BAND" if 0.5 <= ratio <= 2.0 else "AUSSERHALB"  # noqa: PLR2004
        print(f"  Verhaeltnis {ratio:+.2f}x -- {band} (0.5-2.0)")

    # Haengt es an einem einzelnen Markt? Vorab als zwingend angemeldet.
    print("\n" + "-" * 88)
    print("  Jeden Markt einmal auslassen -- haengt das Ergebnis an einem?")
    print("-" * 88)
    base = means[main_arm]
    if base is not None:
        for dropped in returns.columns:
            kept = returns.drop(columns=[dropped])
            trimmed = run_arm(
                kept, residuals(kept, window=BETA_WINDOW), funding, equal_weight=False
            )
            if len(trimmed) < 30:  # noqa: PLR2004
                continue
            value = float(np.mean([d.net for d in trimmed]))
            shift = 1e4 * (value - base)
            print(f"    ohne {dropped:10s} {1e4 * value:>+8.2f} bp/Tag  "
                  f"({shift:>+7.2f} bp Verschiebung)")

    print("\n" + "=" * 88)
    print(
        "  Lesehilfe, vorab festgelegt: zwoelf korrelierte Maerkte sind nicht\n"
        "  zwoelf unabhaengige Beobachtungen. Das Intervall ist ueber die\n"
        "  Zeitreihe der Portfoliorenditen gerechnet, nicht ueber Markt-Paare."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
