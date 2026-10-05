"""Paper trading: make the trades, keep the journal, and say why each one ended.

    python scripts/paper.py --replay --until 100     # fill the journal from history
    python scripts/paper.py --report                 # read what is in it
    python scripts/paper.py --report --trade 12      # one trade, in full

No exchange, no account, no money. The point is a hundred trades whose reasons
were written down before the outcome was known, so that "what did the losers
have in common" becomes a question with an answer.

**Replay is not forward testing and is labelled as such.** Every decision uses
only bars up to its own -- the no-lookahead tests cover that -- but the choice
of which stretch of history to replay was made by somebody who knows how it
went, and no test covers that. Replay fills the journal now so there is
something to learn from; live trades are the ones that prove anything, and
`--source live` keeps them apart in every report.

**The exits are the simulator's, not a second implementation.** Fees, funding,
liquidation and whether the stop or the target was reached first inside a bar
all come from `sim/`, which the backtests already use. A paper trader with its
own fill logic would be a second answer to the same question.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from traidingbrain.reporting.intervals import block_bootstrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.build import entries_from
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.sim.engine import load_engine
from traidingbrain.strategies.guide import GuidePool

#: Where the journal lives. Beside the other databases, not in the Parquet
#: archive: the archive is market data and this is what we did about it.
JOURNAL_NAME = "journal.sqlite"


#: Resamples behind every interval printed below.
BOOTSTRAP = 2000

#: Fewest trades before a group's mean is worth printing with an interval.
#: Below this the interval is wider than the scale and says so by being absurd,
#: which is less useful than saying the sample is too small.
MIN_GROUP = 8


def interval(values: list[float], seed: int = 11) -> str:
    """A 95% bootstrap interval, or a note that there is not enough to say.

    Printed next to every group mean because this journal's whole purpose is
    comparing groups, and a column of means invites exactly the conclusion the
    sample cannot support. Three times in this project a difference between two
    small groups looked real and was not.

    Block-resampled rather than iid. This was the twelfth hand-rolled
    `rng.choice` bootstrap in the repository and the only one running on the
    forward journal -- the evidence section 9 calls decisive -- where
    pretending trades are independent draws is least affordable. The block
    length is printed with the bounds, because a width that depends on a
    parameter has to state it.
    """
    result = block_bootstrap(values, draws=BOOTSTRAP, seed=seed)
    if result is None:
        return "zu wenige Fälle"
    return result.labelled()


def human(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%d.%m.%Y %H:%M")


def _spec(symbol: str) -> SymbolSpec:
    """The same fees and steps the backtests use.

    Shared rather than restated: a paper run costed differently from the
    backtest would disagree with it for a reason nobody could see, and the fee
    is the number that decides most of these trades.
    """
    return SymbolSpec(symbol=symbol, **DEFAULT_SPEC)


def replay(limit: int, symbols: list[str]) -> list[JournalEntry]:
    """Run the guide's setups over stored history and journal every trade."""
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    out: list[JournalEntry] = []

    for symbol in symbols:
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if any(frame.empty for frame in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten, übersprungen", file=sys.stderr)
            continue

        engine = load_engine(
            symbol,
            frames,
            minute_frame=minutes,
            spec=_spec(symbol),
            config=config,
            funding=FundingStore(config.engine.paths.funding_dir).read(symbol),
            history=None,
        )
        strategy = GuidePool.for_config(config)
        result = engine.run(strategy)
        built = entries_from(
            engine.analysis,
            result.fills,
            symbol=symbol,
            strategy=strategy.name,
            source=Source.REPLAY,
            signal=config.engine.timeframes.signal,
        )
        print(f"{symbol}: {len(result.fills)} Trades, {len(built)} vollständig dokumentiert")
        out.extend(built)

    # Every symbol, always. The first draft stopped once the cap was reached,
    # which meant BTC alone filled it and the journal described one market
    # while the report said "100 Trades". A cap that silently selects the
    # sample is worse than no cap.
    out.sort(key=lambda entry: entry.opened_ts)
    if limit and len(out) > limit:
        print(f"\n{len(out)} Trades gefunden; die Auswertung nutzt alle davon.")
    return out


def _overview(entries: list[JournalEntry]) -> None:
    wins = [e for e in entries if e.won]
    total_r = sum(e.r_multiple for e in entries)
    span = f"{human(entries[0].opened_ts)} bis {human(entries[-1].closed_ts)}"
    print(f"\n{len(entries)} Trades, {span}")
    print(f"  Treffer       {len(wins)}/{len(entries)} ({len(wins) / len(entries):.0%})")
    print(f"  Summe         {total_r:+.2f} R")
    r_values = [e.r_multiple for e in entries]
    print(f"  Erwartung     {total_r / len(entries):+.3f} R pro Trade  {interval(r_values)}")
    print(f"  Gebühren      {sum(e.fees for e in entries):,.2f}")

    print("\n  Warum sie endeten:")
    for reason, count in Counter(str(e.exit_reason) for e in entries).most_common():
        share = count / len(entries)
        print(f"    {reason:14s} {count:4d}  {share:5.0%}")

    wicked = [e for e in entries if e.post_mortem.stopped_by_wick]
    never = [e for e in entries if e.post_mortem.never_in_profit]
    gave_back = [e for e in entries if not e.won and e.post_mortem.max_favourable_r >= 1.0]
    print(f"\n  Vom Docht geholt          {len(wicked):4d}")
    print(f"  Nie im Plus               {len(never):4d}")
    print(f"  1 R im Plus und verloren  {len(gave_back):4d}")

    print("\n  Nach Markt:")
    for symbol in sorted({e.symbol for e in entries}):
        values = [e.r_multiple for e in entries if e.symbol == symbol]
        mean = sum(values) / len(values)
        print(f"    {symbol:10s} n={len(values):5d}  {mean:+.3f} R  {interval(values)}")

    # Fixed order, best band first, so the question "do clearer pictures do
    # better?" is answered by reading down the column rather than by sorting
    # it in your head. Ordering by frequency hid that on the first run.
    print("\n  Nach Bewertung bei Einstieg:")
    for band in ("eindeutig", "deutlich", "gemischt", "unklar", "Durcheinander"):
        values = [e.r_multiple for e in entries if e.reason.rating_band == band]
        if not values:
            continue
        mean = sum(values) / len(values)
        print(f"    {band:14s} n={len(values):5d}  {mean:+.3f} R  {interval(values)}")

    agreed = [e for e in entries if e.reason.rating_agreed_with_setup]
    against = [e for e in entries if not e.reason.rating_agreed_with_setup]
    print("\n  Setup gegen Gesamtbild:")
    for group, label in ((agreed, "Bild stimmt zu"), (against, "Bild dagegen")):
        if group:
            values = [e.r_multiple for e in group]
            mean = sum(values) / len(values)
            print(f"    {label:16s} n={len(values):5d}  {mean:+.3f} R  {interval(values)}")


def _one(entry: JournalEntry, number: int) -> None:
    reason = entry.reason
    print(f"\n{'=' * 72}\nTrade {number}  {entry.symbol}  {entry.trade_id}")
    print(f"  Quelle        {entry.source}")
    print(f"  Eröffnet      {human(entry.opened_ts)}")
    print(f"  Geschlossen   {human(entry.closed_ts)}  ({entry.exit_reason})")
    print("\n  WARUM EINGESTIEGEN")
    print(f"    Setup       {reason.setup_key} {reason.setup_name} [{reason.setup_source}]")
    print(f"    Richtung    {reason.side}")
    print(
        f"    Plan        Entry {reason.entry:.4f} / Stop {reason.stop:.4f} "
        f"/ Ziel {reason.target:.4f}   CRV {reason.reward_risk:.2f}"
    )
    print(f"    Stopweite   {reason.stop_distance_pct:.3f} %")
    print(
        f"    Bewertung   {reason.rating}/100 ({reason.rating_band}), "
        f"Gesamtbild {reason.score_direction}"
    )
    print(
        f"                Deutlichkeit {reason.clarity:.2f} · Einigkeit {reason.agreement:.2f} "
        f"· Mehrheit {reason.consensus:.2f} · Abdeckung {reason.coverage:.2f}"
    )
    print(f"    Regime      {reason.regime}, {reason.readings} Messwerte")
    if not reason.rating_agreed_with_setup:
        print("    ACHTUNG     Das Gesamtbild zeigte in die andere Richtung als das Setup.")
    print("    Familien:")
    for note in sorted(reason.families, key=lambda n: -abs(n.contribution)):
        mark = " (still)" if note.silent else ""
        print(
            f"      {note.family:11s} {note.direction:8s} {note.contribution:+.3f}"
            f"  einig {note.agreement:.2f} / Ebenen {note.timeframe_agreement:.2f}{mark}"
        )

    print("\n  WAS DARAUS WURDE")
    print(f"    Ein {entry.entry_price:.4f}  ->  Aus {entry.exit_price:.4f}")
    print(
        f"    {entry.r_multiple:+.2f} R   netto {entry.net_pnl:+.2f} "
        f"(Gebühren {entry.fees:.2f}, Funding {entry.funding:+.2f})"
    )
    post = entry.post_mortem
    print(
        f"    Bestes {post.max_favourable_r:+.2f} R · Schlechtestes "
        f"-{post.max_adverse_r:.2f} R · {post.bars_held} Kerzen"
    )
    print(f"    {post.verdict}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true", help="fill the journal from history")
    parser.add_argument("--report", action="store_true", help="read the journal")
    parser.add_argument("--until", type=int, default=100, help="how many trades to collect")
    parser.add_argument("--trade", type=int, help="print one trade in full")
    parser.add_argument("--worst", type=int, help="print the N worst trades in full")
    parser.add_argument(
        "--source", choices=[str(s) for s in Source], help="limit the report to one kind"
    )
    parser.add_argument("--symbol", action="append")
    args = parser.parse_args()

    config = load_config()
    store = JournalStore(config.engine.paths.data_dir / JOURNAL_NAME)
    symbols = args.symbol or list(config.engine.symbols.active)

    if args.replay:
        built = replay(args.until, symbols)
        store.record(built)
        print(f"\n{len(built)} Trades ins Journal geschrieben ({store.count()} insgesamt)")

    if not args.report:
        return 0

    source = Source(args.source) if args.source else None
    entries = store.all(source=source)
    if not entries:
        print("Journal ist leer. Erst: python scripts/paper.py --replay", file=sys.stderr)
        return 1

    if args.trade is not None:
        if not 1 <= args.trade <= len(entries):
            print(f"Es gibt nur {len(entries)} Trades.", file=sys.stderr)
            return 1
        _one(entries[args.trade - 1], args.trade)
        return 0

    _overview(entries)
    if args.worst:
        ranked = sorted(entries, key=lambda e: e.r_multiple)[: args.worst]
        for entry in ranked:
            _one(entry, entries.index(entry) + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
