"""What the target needs, in numbers rather than in encouragement.

    python scripts/goal.py
    python scripts/goal.py --target 15000 --deadline 2026-10-30

Severin's target is 12,000 CHF of paper trading turned into 15,000 by
30.10.2026. This script reads the real account balances, the measured forward
cadence and the real planned reward-to-risk out of the journal, and says what
expectancy that target implies. It is here because "is it reachable" was asked
several times and answered with judgement, and judgement is the wrong tool for
a question that is arithmetic.

**The three numbers it exists to put side by side.**

* What the target needs, per trade, at the risk the rules currently allow.
* What a single trade can possibly return -- the mean *planned* reward-to-risk
  over the journal, which is the ceiling if every trade hits its target and
  none hits its stop.
* What risk per trade the target would need at a given expectancy.

The first two settle whether the target is reachable at today's risk. The third
is the honest escape hatch, and it comes with a constraint that is easy to miss:
`uncalibrated_cap_risk_pct` holds every confidence tier at 1% until a couple of
hundred historical cases show the upper bands earn it. So raising risk is not an
alternative to finding an edge -- the cap only lifts on evidence of one. Those
two requirements are coupled, and a plan that meets only the second is a plan to
lose money faster.

**Why the cadence comes from the forward journal only.** Replay can be run as
fast as the CPU allows, so its trades per day is a property of the machine. The
forward rate is a property of the rules and the market, and it is the one that
decides how many chances remain before a deadline.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.journal.record import Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.learn.target import (
    Payout,
    growth_at,
    required_hit_rate,
    required_mean_r,
    shortfall_from_variance,
)
from traidingbrain.live.paperstate import PaperStateStore

#: Expectancies worth asking about, as multiples of risk.
#:
#: Measured on 05.10.2026 over **four** markets and 3,300 taken signals
#: (`scripts/study_fees.py`), at four fee schedules. The last row is what a
#: genuinely good system of this kind would do, so the table has an optimistic
#: row that is not a fantasy.
#:
#: These replaced BTC-only figures of -0.0016, +0.0037 and +0.0116, which were
#: wrong in the way that matters: they put break-even within a 3% fee discount
#: when four markets put it at 69%. BTC was the best of four and quoting it as
#: the system's number was selection among four candidates. Note that even the
#: zero-fee row is still short of what the target needs.
SCENARIOS: tuple[tuple[str, float], ...] = (
    ("heute gemessen (4 Maerkte)", -0.0340),
    ("mit 10% Gebuehrenrabatt", -0.0291),
    ("mit 25% Gebuehrenrabatt", -0.0217),
    ("ganz ohne Gebuehr", 0.0151),
    ("ein sehr gutes System", 0.15),
)

#: Fewest forward trades before a cadence can be measured at all.
MIN_FORWARD = 2

#: Fewest journal trades before a payout is worth deriving. Below this the
#: mean winner is one or two trades and the required hit rate it implies is
#: noise wearing a decimal point.
MIN_FOR_PAYOUT = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=float, default=15_000.0, help="In CHF.")
    parser.add_argument("--deadline", default="2026-10-30", help="YYYY-MM-DD.")
    parser.add_argument("--today", help="YYYY-MM-DD. Default: the system date.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    deadline = date.fromisoformat(args.deadline)
    today = date.fromisoformat(args.today) if args.today else datetime.now(tz=UTC).date()
    days = (deadline - today).days

    states = PaperStateStore(config.engine.paths.data_dir / "paper.sqlite")
    symbols = list(config.engine.symbols.active)
    equity = 0.0
    for symbol in symbols:
        state = states.load(symbol)
        if state is not None:
            equity += state.equity
    start = len(symbols) * config.engine.simulation.initial_equity
    if equity <= 0:
        print("Keine Konten gefunden -- scripts/papertrade.py hat noch nicht gelaufen")
        return 0

    journal = JournalStore(config.engine.paths.data_dir / "journal.sqlite")
    forward = sorted(journal.all(source=Source.LIVE), key=lambda e: e.opened_ts)
    replay = journal.all(source=Source.REPLAY)

    print(f"\nZiel        {args.target:,.0f} CHF bis {deadline.strftime('%d.%m.%Y')}")
    print(f"Start       {start:,.2f} CHF")
    print(
        f"Stand       {equity:,.2f} CHF   -> fehlen {args.target - equity:,.2f} CHF "
        f"({100 * (args.target / equity - 1):+.1f}%)"
    )
    if days <= 0:
        print(f"\nDie Frist ist am {deadline.strftime('%d.%m.%Y')} abgelaufen.")
        return 0
    print(f"Tage        {days}")

    if len(forward) < MIN_FORWARD:
        print("\nZu wenige Vorwaerts-Trades, um den Takt zu messen. Rest nicht rechenbar.")
        return 0
    span_days = (forward[-1].closed_ts - forward[0].opened_ts) / 86_400_000
    if span_days <= 0:
        print("\nVorwaerts-Trades liegen alle im gleichen Moment -- kein Takt messbar.")
        return 0
    per_day = len(forward) / span_days
    trades = per_day * days

    risk_chf = (
        config.engine.simulation.initial_equity * config.risk.sizing.uncalibrated_cap_risk_pct
    )
    risk_fraction = risk_chf / equity
    growth = args.target / equity
    needed = (growth ** (1.0 / trades) - 1.0) / risk_fraction

    planned = [entry.reason.reward_risk for entry in replay]
    ceiling = float(np.mean(planned)) if planned else 0.0

    print(
        f"Takt        {per_day:.2f} Trades/Tag, vorwaerts gemessen "
        f"-> {trades:.0f} Chancen bis zur Frist"
    )
    print(
        f"Risiko      {risk_chf:.2f} CHF pro Trade "
        f"= {100 * risk_fraction:.4f}% des Portfolios "
        f"(Deckel {config.risk.sizing.uncalibrated_cap_risk_pct:.1%}, "
        f"hart {config.risk.sizing.absolute_max_risk_pct:.1%})"
    )

    print(f"\nNOETIG      {needed:+.2f} R pro Trade, bei diesem Risiko und diesem Takt")
    if ceiling > 0:
        print(
            f"MAXIMUM     {ceiling:+.2f} R pro Trade -- das mittlere geplante "
            f"Chance-Risiko\n            aus {len(planned)} Trades, also was herauskaeme, "
            f"wenn JEDER Trade\n            sein Ziel trifft und keiner seinen Stop."
        )
        if needed > ceiling:
            print(
                f"\n            Das Ziel verlangt {needed / ceiling:.1f}x das physikalisch "
                f"Moegliche.\n            Bei diesem Risiko ist es auch mit einem perfekten "
                f"System nicht\n            erreichbar, und das ist keine Meinung."
            )

    reachable(equity, args.target, trades, risk_fraction, ceiling)
    required(equity, args.target, trades, config)
    measured_requirement(equity, args.target, trades, config)
    return 0


def measured_requirement(
    equity: float, target: float, trades: float, config: AppConfig
) -> None:
    """The required hit rate, with the payout read off the journal and printed.

    This function exists because of a specific failure. On 05.10.2026 this
    project reported that the target needed "56.6% weekly accuracy", computed
    as an expression in a terminal and never committed. It silently assumed
    winners of +1.371 R. Under a symmetric payout the same target needs
    66.75%, and 56.6% reaches 2.99x -- a third of the way.

    So the payout is no longer an assumption anywhere. It is measured from the
    trades the broker actually booked, printed next to every percentage it
    produces, and `learn/target.py` refuses to compute a required hit rate
    without one.

    **Which population.** The journal, not the labelled signals. Those two sit
    0.058 R apart (-0.0918 R against -0.0340 R) and the journal is the one
    that includes slot competition and liquidation -- the better number was
    reported once and should not be again.
    """
    journal = JournalStore(config.engine.paths.data_dir / "journal.sqlite")
    records = journal.all(source=Source.REPLAY)
    if len(records) < MIN_FOR_PAYOUT:
        print(f"\nZu wenige Journal-Trades ({len(records)}) fuer eine gemessene Auszahlung.")
        return

    values = np.array([t.r_multiple for t in records], dtype="float64")
    wins = values[values > 0]
    losses = values[values <= 0]
    if wins.size == 0 or losses.size == 0:
        print("\nJournal hat nur Gewinner oder nur Verlierer -- keine Auszahlung ableitbar.")
        return

    payout = Payout(win=float(wins.mean()), loss=float(abs(losses.mean())))
    hit = float(wins.size / values.size)
    growth = target / equity

    print("\n" + "=" * 78)
    print("Was das Ziel verlangt, mit der GEMESSENEN Auszahlung daneben")
    print(f"  Auszahlung: {payout.describe()}  ({values.size:,} Journal-Trades)")
    print(f"  Trefferquote gemessen: {100 * hit:.2f}%   Erwartung {values.mean():+.4f} R")
    print(f"\n  {'Risiko':>8s} {'noetig R':>10s} {'noetige Treffer':>17s} {'Luecke':>12s}")

    cap = config.risk.sizing.absolute_max_risk_pct
    for risk in (0.005, 0.01, 0.02, 0.03):
        need_r = required_mean_r(growth=growth, trades=trades, risk=risk)
        try:
            need_p = required_hit_rate(
                growth=growth, trades=trades, risk=risk, payout=payout
            )
        except ValueError:
            print(f"  {100 * risk:>7.1f}% {need_r:>+10.4f} {'Ruin':>17s} {'-':>12s}")
            continue
        over = "  (ueber dem Deckel)" if risk > cap else ""
        shown = f"{100 * need_p:.2f}%" if need_p <= 1.0 else "unerreichbar"
        gap = f"{100 * (need_p - hit):+.1f} Pp" if need_p <= 1.0 else "-"
        print(f"  {100 * risk:>7.1f}% {need_r:>+10.4f} {shown:>17s} {gap:>12s}{over}")

    # And the forward direction: what the measured rate actually reaches. The
    # closed form assumes every trade returns the payout exactly, so the
    # realised R sequence is compounded beside it -- it is always the lower of
    # the two, by Jensen, and that gap is the optimism in every row above.
    reached = growth_at(hit_rate=hit, trades=trades, risk=0.01, payout=payout)
    actual, modelled = shortfall_from_variance(r_values=values, risk=0.01, trades=trades)
    print(
        f"\n  Bei 1% Risiko und gemessener Trefferquote: {equity * reached:>10,.0f} CHF"
        f"\n  Mit der echten R-Streuung derselben Trades:  {equity * actual:>10,.0f} CHF"
        f"\n  (Das konstante-R-Modell sagt {equity * modelled:,.0f} -- es ist optimistisch,"
        f"\n   weil E[ln(1+fR)] < ln(1+f*E[R]), sobald R streut.)"
    )
    print(
        "\n  Keine Prozentzahl hier ohne die Auszahlungszeile darueber. Genau diese\n"
        "  fehlende Zeile machte die 56,6% falsch: sie setzte +1,371 R voraus, ohne\n"
        "  es zu sagen. learn/target.py kann eine Trefferquote nicht mehr ohne\n"
        "  Payout berechnen, und payout_implied_by holt eine verschwiegene Annahme\n"
        "  aus jeder gemeldeten Quote heraus."
    )


def reachable(
    equity: float, target: float, trades: float, risk_fraction: float, ceiling: float
) -> None:
    """Where each expectancy lands by the deadline, at the risk allowed today."""
    print("\nWohin es bei diesem Risiko reicht:")
    rows = [*SCENARIOS, ("jeder Trade trifft sein Ziel", ceiling)] if ceiling > 0 else SCENARIOS
    for label, expectancy in rows:
        final = equity * (1 + risk_fraction * expectancy) ** trades
        reached = "  <- Ziel erreicht" if final >= target else ""
        print(
            f"  {label:30s} {expectancy:+.4f} R -> {final:>10,.2f} CHF  "
            f"({100 * (final / equity - 1):+.2f}%){reached}"
        )


def required(equity: float, target: float, trades: float, config: AppConfig) -> None:
    """What risk per trade each expectancy would need, and whether it is allowed."""
    growth = target / equity
    sizing = config.risk.sizing
    print("\nWelches Risiko pro Trade das Ziel braeuchte:")
    for label, expectancy in [("bei +0.15 R", 0.15), ("bei +0.30 R", 0.30), ("bei +1.00 R", 1.0)]:
        fraction = (growth ** (1.0 / trades) - 1.0) / expectancy
        note = "ueber der harten Grenze" if fraction > sizing.absolute_max_risk_pct else "erlaubt"
        print(
            f"  {label:14s} {100 * fraction:6.2f}% des Portfolios "
            f"= {fraction * equity:8,.0f} CHF pro Trade   ({note})"
        )

    print(
        "\nUnd der Haken an der letzten Tabelle: der Deckel von "
        f"{sizing.uncalibrated_cap_risk_pct:.1%} haelt jede\n"
        "Zuversichtsstufe dort, solange keine Messung zeigt, dass die hoeheren\n"
        f"Stufen es verdienen -- und dann zusaetzlich erst ab "
        f"{sizing.min_samples_for_uncap} Faellen.\n"
        "Mehr Risiko ist also kein Ersatz dafuer, einen Vorteil zu finden --\n"
        "der Deckel geht nur auf, wenn der Vorteil belegt ist. Beides zusammen,\n"
        "oder keines von beidem."
    )
    if not sizing.calibration_proven:
        print(
            "\n            Belegt ist er nicht: `calibration_proven` steht auf false.\n"
            "            Bis 05.10.2026 war das kein Beschluss, sondern ein Rechenunfall "
            "--\n            der Deckel verglich die Nachbarn EINER Kerze (hoechstens "
            f"{config.engine.history.k_neighbours})\n            mit "
            f"{sizing.min_samples_for_uncap}, konnte also nie aufgehen. Richtig gedeckelt, "
            "falscher Grund."
        )


if __name__ == "__main__":
    raise SystemExit(main())
