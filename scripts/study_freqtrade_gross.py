"""Was the +171 USDT of gross profit in the Freqtrade run an edge, or drift?

    python scripts/study_freqtrade_gross.py
    python scripts/study_freqtrade_gross.py --draws 20000

On 05.10.2026 this project ran Freqtrade 2026.9 over Binance spot with a plain
EMA-trend strategy and wrote down: 2,425 trades, gross +171.02 USDT, fees
-969.08, net -798.07, summarised as "a positive gross edge destroyed by a toll
5.7x larger". Three claims hide in that sentence and none had been checked.

**One: how long did it actually trade?** The run was configured for 2025-03-01
to 2026-10-01 and the candles cover all of it, but every trade falls between
2025-03-01 and 2025-06-13. The reason is in the balance: 1,000 USDT down to
201.93, against a stake of 200 and two slots. At that point a second slot can
never be funded. The run did not reach the end of its window, it reached the
end of the money. "2,425 trades over 19 months" was wrong -- it is 2,425 trades
in 15 weeks, and the rest of the window is silence, not measurement.

**Two: is the gross mean separable from zero?** +171.02 over 2,425 trades is
+0.035% per trade against a per-trade spread of 0.56 points. A weekly-block
bootstrap answers it, with weeks as blocks rather than trades because BTC, ETH
and SOL move together -- three trades on one Tuesday are close to one
observation, and resampling rows gives an interval several times too narrow.
With 16 weeks even that is thin, which the report says out loud.

**Three, and this is the one that decides it: zero is the wrong baseline.**
Every trade is long, spot, leverage 1, so the gross return *is* the market's
move over the holding window. The strategy's only contribution is choosing when
that window starts. "Does the entry know anything" therefore has to be measured
against what an uninformed entry faced -- not against zero, which only asks
whether crypto rose.

**And the obvious way to build that baseline is wrong.** Matching each trade's
own holding duration against the drift of that duration looks right and is not:
the duration is chosen by the outcome. A winner runs to its profit target; a
loser is cut when the fast EMA breaks. Measured here, duration and gross return
correlate at **+0.50**. Conditioning the baseline on a quantity the result
determines compares a winner's long window against the drift of a long window,
and the comparison inherits its own answer.

So the horizon is fixed here by this script instead of by the trade: for each
entry, the market's return over H bars from the entry bar, against the mean
return over every H-bar window in the same market and the same period. The
entry time stays the strategy's choice -- that is what is on trial -- while the
horizon stops being evidence about itself. Several H are reported, because an
edge that exists at one arbitrary horizon is a cell in a grid, and this project
counts cells before it believes them.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.domain.market import DEFAULT_SPEC

RESULTS = ROOT / "freqtrade" / "user_data" / "backtest_results"
CANDLES = ROOT / "freqtrade" / "user_data" / "data" / "binance"

#: Resamples for the bootstrap. Enough that the printed bounds are stable
#: across seeds at the shown precision.
DEFAULT_DRAWS = 10_000

#: Fixed, so a quoted interval is the same number every time. The run it reads
#: never changes, so a wandering interval would be pure noise in the report.
SEED = 20261006

#: The timeframe the strategy traded on.
BAR_MINUTES = 5

#: Horizons for the honest test, in bars: 5 and 25 minutes bracket the median
#: holding time of the losers and the winners, 1h and 4h ask whether anything
#: survives past the exit logic. Declared here, before any number was read, so
#: the multiplicity correction below counts the cells actually examined.
HORIZON_BARS = (1, 5, 12, 48)

#: Below this many blocks a percentile bootstrap runs narrow, so the report
#: carries the caveat rather than pretending otherwise.
THIN_BLOCKS = 30

#: How far short of the configured window's end the last trade may fall before
#: the run counts as having stopped early. A week: a strategy can simply have
#: no signal for a few days, and calling that "it stopped" would cry wolf on
#: every quiet tail.
EARLY_STOP_MS = 7 * 24 * 3600 * 1000

WEEK_MS = 7 * 24 * 3600 * 1000


def to_ms(stamps: pd.Series) -> np.ndarray:
    """Milliseconds since the epoch, whatever unit pandas parsed into.

    `.astype("int64")` alone returns the *stored* unit, which pandas 3 picks
    per file -- this project has already been bitten by the microsecond and the
    nanosecond case. An earlier version of this script divided by a million and
    produced kiloseconds, which made every timestamp comparison false, which
    made the baseline slice empty, which made the baseline exactly 0.0000% and
    the entry edge look real. Converting first is the fix; the empty-slice
    guard in `entry_edge` is the second line of defence, because a baseline
    that silently reads nothing is worse than one that fails.
    """
    return stamps.dt.as_unit("ms").astype("int64").to_numpy()


def newest_result(directory: Path) -> Path:
    archives = sorted(directory.glob("backtest-result-*.zip"))
    if not archives:
        raise SystemExit(
            f"Keine Backtest-Ergebnisse in {directory}.\n"
            f"Erst laufen lassen: python scripts/ft.py backtesting ..."
        )
    return archives[-1]


def load_trades(archive: Path) -> tuple[str, dict, list[dict]]:
    with zipfile.ZipFile(archive) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".json") and "_config" not in n)
        payload = json.loads(zf.read(name))
    strategies = payload.get("strategy", {})
    if len(strategies) != 1:
        raise SystemExit(
            f"{archive.name} enthaelt {len(strategies)} Strategien, erwartet war eine."
        )
    strategy = next(iter(strategies))
    return strategy, strategies[strategy], strategies[strategy]["trades"]


def candles(pair: str) -> tuple[np.ndarray, np.ndarray]:
    """Bar open timestamps in ms and bar opens, for one pair."""
    path = CANDLES / f"{pair.replace('/', '_')}-{BAR_MINUTES}m.feather"
    if not path.is_file():
        raise SystemExit(f"Keine Kerzen fuer {pair}: {path} fehlt.")
    frame = pd.read_feather(path)
    return to_ms(frame["date"]), frame["open"].to_numpy(dtype=float)


def forward_returns(opens: np.ndarray, *, bars: int) -> np.ndarray:
    """Return from each bar's open to the open `bars` later."""
    if bars <= 0 or bars >= opens.size:
        raise ValueError(f"Horizont {bars} passt nicht in {opens.size} Kerzen.")
    return opens[bars:] / opens[:-bars] - 1.0


def block_bootstrap(
    values: np.ndarray, blocks: np.ndarray, *, draws: int, seed: int = SEED
) -> tuple[float, float]:
    """A 95% interval for the mean, resampling whole blocks with replacement.

    Blocks are drawn until the resample holds at least as many observations as
    the original and then truncated, so every resample carries the same weight
    regardless of how busy the weeks it happened to draw were.
    """
    rng = np.random.default_rng(seed)
    unique = np.unique(blocks)
    index = {b: np.flatnonzero(blocks == b) for b in unique}
    target = values.size
    per_draw = int(np.ceil(target / np.mean([index[b].size for b in unique]))) + 2

    means = np.empty(draws)
    for d in range(draws):
        taken = np.concatenate(
            [index[b] for b in rng.choice(unique, size=per_draw, replace=True)]
        )
        while taken.size < target:
            extra = rng.choice(unique, size=per_draw, replace=True)
            taken = np.concatenate([taken, *(index[b] for b in extra)])
        means[d] = values[taken[:target]].mean()
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


def entry_edge(
    trades: list[dict], *, bars: int, draws: int
) -> tuple[float, float, float, float, int]:
    """Paired edge of the strategy's entry timing at a horizon this script fixes.

    Returns the mean edge, its interval bounds, the uninformed baseline, and
    how many trades could be measured. An entry that is not on the bar grid, or
    that has no full horizon after it, is skipped -- and the count is reported
    rather than quietly folded into the mean.
    """
    opened = np.array([t["open_timestamp"] for t in trades], dtype=np.int64)
    window = (opened.min(), opened.max())

    edges: list[float] = []
    weeks: list[int] = []
    baselines: list[float] = []
    off_grid = 0
    for pair in sorted({t["pair"] for t in trades}):
        stamps, opens = candles(pair)
        inside = np.flatnonzero((stamps >= window[0]) & (stamps <= window[1]))
        if inside.size <= bars:
            raise SystemExit(
                f"{pair}: nur {inside.size} Kerzen im gehandelten Fenster, Horizont "
                f"{bars} passt nicht hinein.\nFenster {window} gegen Kerzen "
                f"{stamps.min()}..{stamps.max()} -- das ist ein Einheitenfehler, "
                f"kein leerer Markt."
            )
        base = float(forward_returns(opens[inside], bars=bars).mean())

        for trade in (t for t in trades if t["pair"] == pair):
            at = int(np.searchsorted(stamps, trade["open_timestamp"]))
            if at >= stamps.size or stamps[at] != trade["open_timestamp"]:
                off_grid += 1
                continue
            if at + bars >= opens.size:
                continue
            # The whole measurement rests on the entry landing on this bar's
            # open, because that is the price the horizon is measured from.
            # Checked against 15,624 trades on 06.10.2026 and exact for every
            # one; asserted so that a Freqtrade version with different fill
            # logic fails loudly instead of shifting every number by an
            # invisible fraction of a bar.
            if not np.isclose(trade["open_rate"], opens[at], rtol=1e-9):
                raise SystemExit(
                    f"{pair}: Einstieg zu {trade['open_rate']} liegt nicht auf der "
                    f"Kerzeneroeffnung {opens[at]} bei {trade['open_date']}.\n"
                    f"Dann misst dieses Skript einen Horizont ab einem Preis, den der "
                    f"Trade nie bezahlt hat."
                )
            edges.append((opens[at + bars] / opens[at] - 1.0) - base)
            baselines.append(base)
            weeks.append(int(trade["open_timestamp"] // WEEK_MS))

    if off_grid:
        # Not fatal, but it must never be invisible: trades dropped silently
        # would quietly change which population the figure describes.
        print(f"  (Hinweis: {off_grid} Einstiege lagen nicht auf dem Kerzenraster)")
    values = np.array(edges)
    low, high = block_bootstrap(values, np.array(weeks), draws=draws)
    return float(values.mean()), low, high, float(np.mean(baselines)), values.size


def report_window(
    summary: dict, trades: list[dict], *, span_days: float, blocks: int
) -> None:
    """What the run actually traded, and whether it reached the end of its window.

    Derived rather than narrated. The first version of this block hard-coded
    the sentence about the account running dry: true of the run it was written
    against, false of the very next one. A report that asserts something untrue
    about the run it is describing is the exact failure this whole script
    exists to catch, so the three cases are decided from the data.
    """
    print("\nWas der Lauf wirklich gehandelt hat")
    print(f"  angefordertes Fenster   {summary['backtest_start']}  bis  {summary['backtest_end']}")
    print(f"  tatsaechlich gehandelt  {trades[0]['open_date']}  bis  {trades[-1]['close_date']}")
    print(f"  Spanne                  {span_days:.0f} Tage ({blocks} Wochenbloecke)")
    start, final = summary["starting_balance"], summary["final_balance"]
    print(f"  Kontostand              {start:.0f} -> {final:.2f}")

    stake = float(summary.get("stake_amount") or 0.0)
    slots = int(summary.get("max_open_trades") or 1)
    window_end = pd.Timestamp(summary["backtest_end"], tz="UTC").value // 1_000_000
    idle_days = (window_end - trades[-1]["close_timestamp"]) / 86_400_000

    if idle_days * 86_400_000 <= EARLY_STOP_MS:
        print(
            "  Der Lauf reicht bis ans Fensterende, und das Konto haelt durch: die\n"
            "  Zahlen unten gelten fuer den ganzen angeforderten Zeitraum."
        )
    elif final < stake * slots:
        print(
            f"  Er endete nicht am Fensterende, sondern am Geld: mit {final:.0f} USDT\n"
            f"  laesst sich bei {stake:.0f} Einsatz und {slots} Plaetzen kein voller Satz\n"
            f"  mehr finanzieren. Der Rest des Fensters ist Stille, keine Messung --\n"
            f"  jede Zahl unten gilt fuer die Strecke bis zum Ruin, nicht fuer das\n"
            f"  Fenster, das angefordert war."
        )
    else:
        print(
            f"  Der letzte Trade liegt {idle_days:.0f} Tage vor dem Fensterende, und das\n"
            f"  Konto war nicht leer. Es lag also an den Signalen, nicht am Geld."
        )


#: Fees read from the venues' own documentation on 07.10.2026, as fractions.
#: Kept here so the scope note below cannot drift from what was verified.
OTHER_VENUES: tuple[tuple[str, float, float], ...] = (
    ("Lighter Standard", 0.0, 0.0),
    ("Lighter Premium, 0 LIT", 0.000040, 0.000280),
    ("Extended, Orderbuch", 0.0, 0.000250),
)


def scope_note(proven_high: float) -> None:
    """Where the floor above applies, and where it does not.

    Until 07.10.2026 this script concluded "no fee reduction can ever help",
    which is a claim about every venue made from a measurement on one. The
    numbers below were read from the venues' own documentation, and the
    cheapest maker/maker among them sits *below* the upper bound of the one
    cell here that is evidence. The conclusion is therefore scoped, not
    withdrawn -- and what it turns into is E0.
    """
    print("")
    print("  Auf DIESER Boersenfamilie ist 'lohnt es, die Maut zu jagen?' damit")
    print("  beantwortet: nein. Eine Gebuehrensenkung INNERHALB dieser Struktur kann")
    print("  nur einholen, was an Vorsprung da ist.")
    print("")
    print("  Was daraus NICHT folgt: dass keine Gebuehrensenkung je helfen koenne.")
    print("  Am 07.10.2026 an den Primaerquellen der Venues abgerufen:")
    print("")
    cheapest, cheapest_name = float("inf"), ""
    for name, maker, taker in OTHER_VENUES:
        both_maker = 2 * maker
        if both_maker < cheapest:
            cheapest, cheapest_name = both_maker, name
        print(
            f"    {name:24s} maker {100 * maker:.4f}%  taker {100 * taker:.4f}%"
            f"  maker/maker {100 * both_maker:.4f}%"
        )
    print("")
    if cheapest < proven_high:
        print(f"  {cheapest_name} liegt mit {100 * cheapest:.4f}% maker/maker UNTER der")
        print(f"  Obergrenze der belegten Zelle ({100 * proven_high:.4f}%). Der Boden oben")
        print("  ist der Boden DIESER Venue, nicht des Marktes.")
    print("")
    print("  Das macht die Frage nicht zu einer Gebuehrenfrage, sondern verschiebt sie:")
    print("  bei 0% Gebuehr entscheiden Spread, Latenz und adverse Selektion ueber das")
    print("  Vorzeichen -- drei Groessen, die dieses Projekt nie gemessen hat. Und ein")
    print("  auf Binance gemessenes Signal wird nicht dadurch zu einem auf Lighter")
    print("  belegten, dass man eine Gebuehrenzahl austauscht. Das ist E0.")


def verdict(cells: list[tuple[str, float, float, float]], *, toll_paid: float) -> None:
    """Does any horizon that is actually evidence pay the cheapest possible toll?

    `cells` carries (label, mean, high, low) per horizon. Two rules decide what
    may be held against the toll, and both exist because it is easy to cheat
    here without noticing:

    * Only a cell whose interval excludes zero counts. The largest *mean* in
      this run belongs to a cell consistent with nothing at all, and holding
      that number against the fee schedule would be reading the noise as the
      result -- the same mistake this project caught in `study_panel.py`, where
      a point estimate was compared against an interval on another quantity.
    * Of those, the comparison uses the UPPER bound, not the mean. That is a
      deliberate gift to the hypothesis: if even the optimistic end cannot pay
      the floor, the generous reading has been tried and has failed.

    The fees come from the project's own spec, so changing the spec moves this
    verdict with it instead of leaving a stale number behind in a report.
    """
    floor = 2 * DEFAULT_SPEC["maker_fee"]
    realistic = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"]
    proven = [c for c in cells if c[3] > 0.0]
    loudest = max(cells, key=lambda c: c[1])

    print("\nDeckt ein BELEGTER Vorsprung die billigste denkbare Maut?")
    if proven:
        label, mean, high, _ = max(proven, key=lambda c: c[1])
        print(
            f"  bester belegter Horizont   {label}: {100 * mean:+.4f}%, "
            f"Obergrenze {100 * high:+.4f}%"
        )
    else:
        label, mean, high = "", 0.0, 0.0
        print("  bester belegter Horizont   keiner -- kein Intervall schliesst die Null aus")
    if loudest[3] <= 0.0:
        print(
            f"  groesster Mittelwert       {loudest[0]}: {100 * loudest[1]:+.4f}% -- "
            f"aber mit Null im Intervall,\n"
            f"                             also keine Evidenz und hier nicht verwendet"
        )
    print(f"  Maut maker/maker (Boden)   {100 * floor:.4f}%")
    print(f"  Maut maker/taker (real)    {100 * realistic:.4f}%")
    print(f"  Maut dieses Spot-Laufs     {100 * toll_paid:.4f}%")

    print("\n" + "-" * 78)
    if not proven:
        print("  Kein Horizont trennt den Einstieg vom ahnungslosen Einstieg.")
        print("  Das Brutto ist damit nicht als Koennen belegt -- und das ist die")
        print("  haertere Aussage, nicht die mildere: eine Null laesst sich durch keine")
        print("  niedrigere Gebuehr ins Positive heben.")
    elif high < floor:
        print(f"  Die einzige Zelle, die ueberhaupt Evidenz ist ({label}), traegt oben")
        print(f"  {100 * high:.4f}%. Die Maut, die entstuende, wenn BEIDE Seiten als Maker")
        print(f"  ausgefuehrt wuerden, ist {100 * floor:.4f}% -- der Boden dieser Boersen-")
        print("  familie, nicht ihr Normaltarif.")
        short = floor / max(high, 1e-12)
        print(f"  Es fehlt der Faktor {short:.1f}, und zwar nach drei Zugestaendnissen:")
        print("  guenstigste belegte Zelle, keine Mehrfachkorrektur, oberer Rand ihres")
        print("  Intervalls. Alle drei zusammen reichen nicht.")
        scope_note(high)
    else:
        need = 0.05 / len(cells)
        print(f"  Eine belegte Zelle ({label}) deckt oben die Maut von {100 * floor:.4f}%.")
        print(f"  Vor einem Urteil fehlt dann aber beides: die Schwelle ist {need:.4f}")
        print(f"  und nicht 0.05 bei {len(cells)} angesehenen Zellen, und die Wiederholung in")
        print("  einem Fenster, das nicht mitgesucht hat.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=None, help="Bestimmtes Ergebnis-Zip")
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args()

    archive = args.archive or newest_result(RESULTS)
    strategy, summary, trades = load_trades(archive)

    opened = np.array([t["open_timestamp"] for t in trades], dtype=np.int64)
    gross = np.array(
        [
            (-1.0 if t.get("is_short") else 1.0) * (t["close_rate"] / t["open_rate"] - 1.0)
            for t in trades
        ]
    )
    net = np.array([t["profit_ratio"] for t in trades])
    duration = np.array([t["trade_duration"] for t in trades], dtype=float)
    week = opened // WEEK_MS
    toll = gross - net
    blocks = int(np.unique(week).size)

    print("=" * 78)
    print(f"Freqtrade-Lauf: {archive.name}")
    print(f"Strategie: {strategy}   Trades: {len(trades)}")
    print("=" * 78)

    report_window(
        summary,
        trades,
        span_days=(opened.max() - opened.min()) / 1000 / 86400,
        blocks=blocks,
    )

    print("\nJe Trade, in Prozent des Einsatzes")
    g_low, g_high = block_bootstrap(gross, week, draws=args.draws)
    n_low, n_high = block_bootstrap(net, week, draws=args.draws)
    print(
        f"  brutto (Preisbewegung)  {100 * gross.mean():+7.4f}%"
        f"  [{100 * g_low:+.4f}, {100 * g_high:+.4f}]"
    )
    print(f"  Maut   (Gebuehren)      {100 * toll.mean():+7.4f}%")
    print(
        f"  netto  (gebucht)        {100 * net.mean():+7.4f}%"
        f"  [{100 * n_low:+.4f}, {100 * n_high:+.4f}]"
    )
    correlation = float(np.corrcoef(duration, gross)[0, 1])
    print("\nWarum die naheliegende Vergleichsgroesse nicht geht")
    print(f"  Korrelation Haltedauer <-> Brutto   {correlation:+.3f}")
    print(
        "  Die Dauer ist vom Ausgang gewaehlt: Gewinner laufen bis zum Ziel,\n"
        "  Verlierer werden am EMA-Bruch gekappt. Eine Vergleichsgroesse auf die\n"
        "  realisierte Dauer zu stuetzen heisst, auf das Ergebnis zu bedingen."
    )

    print("\nFester Horizont, von diesem Skript vorgegeben")
    print("  Vorsprung = Rendite ab Einstiegskerze minus mittlere Rendite jedes")
    print("  gleich langen Fensters im selben Markt und Zeitraum (gepaart).\n")
    print(f"  {'Horizont':>10s}  {'Basis':>9s}  {'Vorsprung':>10s}  {'95%-Intervall':>22s}   n")

    cells: list[tuple[str, float, float, float]] = []
    for bars in HORIZON_BARS:
        mean, low, high, base, n = entry_edge(trades, bars=bars, draws=args.draws)
        excludes = low > 0.0
        label = f"{bars * BAR_MINUTES} min"
        cells.append((label, mean, high, low))
        print(
            f"  {label:>10s}  {100 * base:+8.4f}%  {100 * mean:+9.4f}%  "
            f"[{100 * low:+.4f}, {100 * high:+.4f}]{' *' if excludes else ''}  {n}"
        )

    verdict(cells, toll_paid=float(toll.mean()))

    if blocks < THIN_BLOCKS:
        print(
            f"\n  Vorbehalt: {blocks} Wochenbloecke. Ein Perzentil-Bootstrap laeuft bei so\n"
            f"  wenigen Bloecken zu eng; das Intervall ist eher optimistisch als\n"
            f"  vorsichtig. Es ist die beste Schaetzung aus diesem Lauf und kein\n"
            f"  belastbares Urteil -- dafuer braeuchte es ein Fenster, das die\n"
            f"  Strategie finanziell ueberlebt."
        )
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
