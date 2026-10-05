"""Are the signals the risk rules refuse any good?

    python scripts/study_refused.py --symbols BTCUSDT
    python scripts/study_refused.py                      # the first four markets

The first question in this project that is not about the trades we took.

Six levers were measured on 04.10.2026 and all six failed, and they share a
shape: four re-priced the same signals and two re-selected among them. The
gross expectancy of the taken entries is -0.0102 R with an interval straddling
zero, which means choosing differently among them cannot help -- you cannot
pick a better-than-nothing subset out of nothing, and re-pricing only moves the
toll. The population itself has to change, and the only population available is
the one the five risk rules in `sim/plan.py` refuse.

Those rules have never been checked against outcomes. Not once, and not for
lack of care: until yesterday a refusal was a single increment of a counter, so
there was nothing to check. `scripts/study_cost_floor.py` varied the *threshold*
of one of them across four markets and found the shipped setting dominates,
which is a different question from whether the rule should exist at all.

So: run the pool, keep every signal with the rule that judged it, then label
all of them -- taken and refused alike -- against the same three barriers, and
read the two columns that matter.

**Gross first, then net.** A refused signal's gross R says whether the entry was
any good. Its net R says whether it would have paid after the toll. The
distinction is the whole point for the cost rule in particular: that rule exists
to say "a stop this tight cannot survive the fees", and the honest test is a
population with strongly positive gross and negative net. If that is what comes
back, the rule is right and this study closes the question. If the net is
positive, the rule is costing money.

**What a positive result here is not.** These signals never competed for a slot.
A refused signal arriving while the account was busy would not have traded even
with the rule removed, and the label here does not know that -- `label_signal`
deliberately treats every signal as if it were the only thing in the world,
which is what makes it free of the occupancy confound and also what stops it
answering the portfolio question. So a positive column is a **candidate**: it
earns a backtest arm with the rule relaxed, measured the way the other six
levers were measured. It is not permission to turn a rule off.

**Resumption is the ledger.** The signal store is append-only on disk and keyed
by configuration, so a market already walked is skipped and a killed run loses
nothing. Labelling is cheap and is redone every time.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, FundingRate, SymbolSpec
from traidingbrain.journal.signals import Action, SignalRecord, SignalStore
from traidingbrain.journal.version import run_signature, spread
from traidingbrain.learn.labels import Label, Minutes, Tally, label_signal
from traidingbrain.reporting.intervals import block_bootstrap, two_group_difference
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool

MARKETS = 4
HOUR_MS = 3_600_000

#: How long a label may stay open before it is closed at market.
#:
#: The same number the history engine already uses as its outcome horizon
#: (`history.outcome_horizon_hours`), and deliberately so: the purge and embargo
#: in `learn/splits.py` have to cover the label horizon, and two different
#: numbers for one quantity is how a leak gets in through the back door.
HORIZON_HOURS = 48


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument(
        "--max-bars", type=int, help="Stop after N signal bars. A transport check, not a result."
    )
    parser.add_argument(
        "--shadow",
        action="store_true",
        help=(
            "Also ask the strategy while the slot is busy and record the answer "
            "as OCCUPIED without trading. Roughly triples the run; writes under "
            "its own signature so it cannot collide with a plain collection."
        ),
    )
    return parser.parse_args()




def collect(
    symbol: str,
    config: object,
    store: ParquetStore,
    signals: SignalStore,
    *,
    max_bars: int | None,
    shadow: bool = False,
) -> bool:
    """Walk one market and write every signal it produced. True if anything ran."""
    sig = run_signature(config, max_bars=max_bars, shadow=shadow)
    if signals.count(symbol=symbol, run_signature=sig):
        print(f"{symbol}: Signale liegen vor", flush=True)
        return True

    started = time.perf_counter()
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}  # type: ignore[attr-defined]
    minutes = store.read(symbol, config.engine.timeframes.execution)  # type: ignore[attr-defined]
    if any(f.empty for f in frames.values()) or minutes.empty:
        print(f"{symbol}: keine Daten", flush=True)
        return False

    analysis = MultiFrameAnalysis(frames, config.engine)  # type: ignore[attr-defined]
    engine = BacktestEngine(
        symbol,
        analysis,
        minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config,  # type: ignore[arg-type]
        funding=FundingStore(config.engine.paths.funding_dir).read(symbol),  # type: ignore[attr-defined]
        history=None,
        signals=signals,
        run_signature=sig,
        shadow=shadow,
    )
    result = engine.run(GuidePool.for_config(config), max_bars=max_bars)  # type: ignore[arg-type]
    print(
        f"{symbol}: {result.intents} Signale, {result.intents_rejected_by_risk} abgelehnt, "
        f"{len(result.fills)} Trades in {time.perf_counter() - started:.0f}s",
        flush=True,
    )
    return True


def label_all(
    records: list[SignalRecord],
    minutes: Minutes,
    config: object,
    funding: list[FundingRate],
) -> list[tuple[SignalRecord, Label]]:
    """Every signal against the same three barriers, taken or not.

    Funding is passed in because a 48-hour horizon spans up to six settlements,
    and at a typical 1.5% stop a single one is worth roughly 0.02 R -- against
    an expectancy of -0.09 R, which is not a rounding error.
    """
    spec = SymbolSpec(symbol=records[0].symbol if records else "BTCUSDT", **DEFAULT_SPEC)
    simulation = config.engine.simulation  # type: ignore[attr-defined]
    expiry_ms = simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal  # type: ignore[attr-defined]
    )
    out: list[tuple[SignalRecord, Label]] = []
    for record in records:
        label = label_signal(
            side=record.side,
            entry=record.entry,
            stop=record.stop,
            target=record.target,
            decision_ts=record.decided_ts,
            minutes=minutes,
            spec=spec,
            config=simulation,
            horizon_ms=HORIZON_HOURS * HOUR_MS,
            expiry_ms=expiry_ms,
            funding=funding,
        )
        if label.resolved:
            out.append((record, label))
    return out


def line(name: str, pairs: list[tuple[SignalRecord, Label]]) -> str:
    if not pairs:
        return f"  {name:28s} keine"
    gross = [label.gross_r for _, label in pairs]
    net = [label.net_r for _, label in pairs]
    funding = [label.funding_r for _, label in pairs]
    hits = 100 * sum(1 for value in net if value > 0) / len(net)
    interval = block_bootstrap(gross)
    bounds = interval.labelled() if interval is not None else "zu wenige"
    return (
        f"  {name:28s} n={len(pairs):5d}  brutto {sum(gross) / len(gross):+.4f}  "
        f"netto {sum(net) / len(net):+.4f}  Funding {sum(funding) / len(funding):+.4f}  "
        f"Treffer {hits:3.0f}%  {bounds}"
    )


def report_provenance(records: Iterable[SignalRecord]) -> None:
    """Which code wrote the rows this result rests on.

    Printed rather than enforced. More than one version is not automatically
    wrong -- a refactor that cannot change a decision leaves the numbers
    comparable -- but mixing two of them is never something to discover after
    acting on the result, and the rows themselves look identical.
    """
    versions = spread(record.code_version for record in records)
    if len(versions) == 1:
        print(f"Geschrieben von Code {versions[0]}")
        return
    print(
        f"ACHTUNG: diese Zeilen kommen aus {len(versions)} Code-Versionen "
        f"({', '.join(versions)}).\nEin Vergleich ueber sie hinweg vergleicht "
        "moeglicherweise zwei Systeme, nicht zwei Regeln."
    )


def report_shadow(
    pairs: list[tuple[SignalRecord, Label]], taken: list[tuple[SignalRecord, Label]]
) -> None:
    """The population the ledger never had, and the one comparison it settles.

    These are signals that existed while the single slot was busy. Until the
    shadow pass they produced no row at all -- the strategy was not even asked
    -- so about two thirds of every market's history was unobserved, and no
    bound in either direction could be read from the signals that remained.

    The row that decides whether more concurrency is worth anything is
    `haette genommen`: shadow signals the risk rules would have accepted.
    Compared against what the system actually traded over the same period, it
    says plainly whether a second slot would have bought better trades, worse
    ones, or the same ones. A raw count of skipped signals cannot answer that,
    because most of them are ones the rules already refuse -- and those rules
    are measured and right.
    """
    shadow = [p for p in pairs if p[0].action is Action.OCCUPIED]
    if not shadow:
        return
    would = [p for p in shadow if p[0].refused_by is None]
    print("\n--- im Schatten: Signale, die nie um einen Platz konkurrieren durften ---")
    print(line("im Schatten (alle)", shadow))
    print(line("davon haette genommen", would))
    for rule, group in sorted(_by_rule(shadow).items(), key=lambda kv: -len(kv[1])):
        print(line(f"davon abgelehnt: {rule}", group))

    if would and taken:
        # With an interval, not as a point estimate. A difference of means is
        # exactly what each of the nine rejected hypotheses looked like first,
        # and three times today a point estimate pointed somewhere the interval
        # did not support.
        difference = two_group_difference(
            [label.net_r for _record, label in would],
            [label.net_r for _record, label in taken],
        )
        gap = _mean_net(would) - _mean_net(taken)
        verdict = "besser" if gap > 0 else "schlechter"
        print(
            f"\n  Die verdeckten handelbaren Signale sind {abs(gap):.4f} R pro Trade "
            f"{verdict}\n  als das, was das System tatsaechlich genommen hat."
        )
        if difference is not None:
            carries = "Null ausgeschlossen" if difference.excludes_zero else "enthaelt die Null"
            print(f"  Unterschied {difference.labelled()} -> {carries}")
        print(
            "  Das ist die Zahl, die sagt, ob ein zweiter Platz bessere Trades gekauft\n"
            "  haette -- nicht ihre Anzahl."
        )


def _by_rule(
    pairs: list[tuple[SignalRecord, Label]],
) -> dict[str, list[tuple[SignalRecord, Label]]]:
    groups: dict[str, list[tuple[SignalRecord, Label]]] = defaultdict(list)
    for record, label in pairs:
        if record.refused_by is not None:
            groups[record.refused_by.value].append((record, label))
    return groups


def _mean_net(pairs: list[tuple[SignalRecord, Label]]) -> float:
    return sum(label.net_r for _record, label in pairs) / len(pairs)


def report(pairs: list[tuple[SignalRecord, Label]], tally: Tally) -> None:
    print("\n" + "=" * 78)
    if not pairs:
        print("Keine auswertbaren Signale")
        return

    print(tally.summary())
    report_provenance(record for record, _label in pairs)
    print(
        "\nBrutto zuerst: sagt, ob der Einstieg etwas wert war. Netto sagt, ob er\n"
        "die Maut bezahlt haette. Das Intervall steht auf der Brutto-Zahl.\n"
    )
    taken = [p for p in pairs if p[0].action is Action.TAKEN]
    refused = [p for p in pairs if p[0].action is Action.REFUSED]
    print(line("genommen", taken))
    print(line("abgelehnt (alle)", refused))
    report_shadow(pairs, taken)

    print("\n--- je Regel, und das ist die eigentliche Frage ---")
    by_rule: dict[str, list[tuple[SignalRecord, Label]]] = defaultdict(list)
    for record, label in refused:
        if record.refused_by is not None:
            by_rule[record.refused_by.value].append((record, label))
    for rule, group in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        print(line(rule, group))

    print(
        "\nEine Regel, deren abgelehnte Signale brutto deutlich positiv und netto\n"
        "negativ sind, hat recht -- genau das ist ihre Behauptung. Eine, deren\n"
        "Netto positiv ist und deren Intervall die Null ausschliesst, kostet Geld.\n"
        "\nUnd was das hier NICHT ist: diese Signale haben nie um einen Platz\n"
        "konkurriert. Ein positiver Befund verdient einen Backtest-Arm mit\n"
        "gelockerter Regel, gemessen wie die anderen sechs Hebel. Er ist keine\n"
        "Erlaubnis, eine Regel abzuschalten."
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")
    funding_store = FundingStore(config.engine.paths.funding_dir)
    sig = run_signature(config, max_bars=args.max_bars, shadow=args.shadow)

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:MARKETS])
    )

    pairs: list[tuple[SignalRecord, Label]] = []
    tally = Tally()
    for symbol in symbols:
        if not collect(
            symbol, config, store, signals, max_bars=args.max_bars, shadow=args.shadow
        ):
            continue
        records = signals.all(symbol=symbol, run_signature=sig)
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if minutes.empty or not records:
            continue
        labelled = label_all(records, Minutes.of(minutes), config, funding_store.read(symbol))
        for _, label in labelled:
            tally.add(label)
        # Unfilled signals are dropped by `label_all`, so count them here: a
        # limit that was never reached is not a trade anybody missed.
        tally.unfilled += len(records) - len(labelled)
        pairs.extend(labelled)
        print(f"  {symbol}: {len(labelled)} von {len(records)} Signalen aufgeloest", flush=True)

    report(pairs, tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
