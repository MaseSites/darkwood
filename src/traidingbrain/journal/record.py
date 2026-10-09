"""One paper trade, with the case for it and what became of it.

A fill says what happened: in at this price, out at that one, this much paid in
fees. It cannot say *why* the trade was taken, and without that a hundred
trades are a hundred numbers nobody can learn anything from. The entry reason
and the post-mortem are the halves that make a journal worth keeping.

**Where a trade came from is part of the record, not metadata.** A trade
replayed over bars that had already happened and a trade taken forward in real
time are evidence of different strengths, and the day they are mixed in one
average is the day the average means nothing. `source` is required, it is
stored, and every report splits on it.

**Nothing here is a real order.** Paper only: no exchange, no account, no money.
That is what makes it safe to run a hundred of these and look at the results
honestly instead of hoping.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from traidingbrain.domain.enums import ExitReason, Side


class Source(StrEnum):
    """Where a trade's future came from."""

    REPLAY = "replay"
    """Bars that had already happened when the trade was recorded.

    Honest about what it is. The decision used only data up to its own bar --
    the no-lookahead tests cover that -- but the *selection* of which period to
    replay was made by somebody who knows how that period went, and no test can
    cover that."""

    LIVE = "live"
    """The future arrived after the decision was written down. The only kind
    that cannot have been chosen with hindsight."""


@dataclass(frozen=True)
class FamilyNote:
    """What one information family contributed at the decision bar."""

    family: str
    direction: str
    contribution: float
    agreement: float
    timeframe_agreement: float
    silent: bool


@dataclass(frozen=True)
class TradeReason:
    """The whole case for the trade, as it stood when it was made.

    Captured rather than summarised. "Setup C, rating 71" is a label; the
    family breakdown is the thing that lets a person look at twenty losers and
    notice what they had in common.
    """

    setup_key: str
    setup_name: str
    setup_source: str
    setup_timeframe: str
    """Which chart the setup was found on.

    The question the multi-timeframe search exists to answer: a four-hour
    entry and an hourly one are different trades even under the same setup
    letter, and without this the journal cannot tell which chart is worth
    reading."""

    side: str
    entry: float
    stop: float
    target: float
    reward_risk: float
    stop_distance_pct: float

    rating: int
    rating_band: str
    clarity: float
    agreement: float
    consensus: float
    coverage: float

    score_bullish: float
    score_bearish: float
    score_direction: str
    conflict: float
    breadth: int
    readings: int
    regime: str
    signal_timeframe: str = ""
    """How often the loop was looking when this trade was decided.

    Not the same question as `setup_timeframe`. A four-hour setup found by an
    hourly loop and the same setup found by a fifteen-minute loop are the same
    trade; what differs is how many *other* chances were seen and taken around
    it, which changes how often the account was occupied and therefore which
    trades happened at all.

    Recorded because the cadence changed mid-run, on 04.10.2026, from H1 to
    M15. Without it the journal would hold trades from two different systems in
    one table with nothing to separate them -- and the separation cannot be
    reconstructed afterwards from anything else in the record. Empty on rows
    written before the field existed, which is itself the answer for those:
    they are the hourly ones."""

    families: list[FamilyNote] = field(default_factory=list)

    @property
    def rating_agreed_with_setup(self) -> bool:
        """Did the overall picture point the same way as the setup?

        The single most interesting cross-check in the record. A setup firing
        long while every family leans short is a different trade from one where
        they agree, and nothing in the entry rules currently cares.
        """
        wanted = "aufwärts" if self.side == Side.LONG.value else "abwärts"
        return self.score_direction == wanted


@dataclass(frozen=True)
class PostMortem:
    """What the market did between entry and exit, and the sentence for it."""

    bars_held: int
    max_favourable_r: float
    """How far it ran in our favour before it ended, in units of the risk."""

    max_adverse_r: float
    """How far it ran against us. Positive is against."""

    closest_to_target_r: float
    stopped_by_wick: bool
    """The stop was touched while the bar still closed on the right side of it.

    Worth its own field because it is the one loss a person argues with, and
    counting how often it happens is the only way to tell a real pattern from
    the two cases anybody remembers."""

    never_in_profit: bool
    verdict: str
    """One German sentence. Derived, never written by hand."""


@dataclass(frozen=True)
class JournalEntry:
    """A paper trade, start to finish."""

    trade_id: str
    source: Source
    symbol: str
    strategy: str
    opened_ts: int
    closed_ts: int
    exit_reason: ExitReason
    entry_price: float
    exit_price: float
    qty: float
    leverage: float
    risk_amount: float
    gross_pnl: float
    fees: float
    funding: float
    net_pnl: float
    r_multiple: float
    reason: TradeReason
    post_mortem: PostMortem
    #: Welche Konfiguration diesen Trade erzeugt hat. Leer fuer alles, was vor
    #: dem 09.10.2026 geschrieben wurde.
    #:
    #: **Warum das Feld noetig wurde.** Am 09.10.2026 war die Frage, ob die 18
    #: Vorwaertstrades EINE Stichprobe sind -- entscheidend, weil eine
    #: Maechtigkeitsrechnung an ihr haengt. Aus dem Journal war das nicht zu
    #: beantworten: der Signaturbegriff existiert (`journal/version.py`, und der
    #: Signalspeicher traegt ihn je Zeile), aber der Journaleintrag nicht.
    #:
    #: Beantworten liess es sich nur ueber die Git-Historie der Konfiguration,
    #: und dort standen vier strategiewirksame Aenderungen innerhalb von zwei
    #: Tagen -- acht Maerkte, zwoelf Maerkte, M15-Kadenz, Setup C aus. Die
    #: homogene Stichprobe waren 14 Trades, nicht 18. Eine Eigenschaft, die man
    #: nur durch Git-Archaeologie findet, ist keine aufgezeichnete Eigenschaft.
    run_signature: str = ""

    @property
    def won(self) -> bool:
        return self.net_pnl > 0

    @property
    def notional(self) -> float:
        """Wie viel Geld in diesem Trade steckte, zum EINSTIEGSPREIS.

        `entry_price`, nicht `exit_price`, und das ist der ganze Punkt: die
        Frage ist, mit wie viel Geld man in den Trade gegangen ist. Mit dem
        Ausstiegspreis gerechnet waere es die Groesse, mit der man
        herauskam -- eine andere Zahl, und bei einem Gewinner eine
        groessere.

        Dieselbe Rechnung wie `sim/broker.py::fill` und
        `OpenPosition.notional`. Als property statt als gespeichertes Feld,
        damit das Journal-Schema unberuehrt bleibt: `asdict()` nimmt nur
        dataclass-Felder, also schreibt `to_json()` hier nichts dazu und
        `from_json()` bekommt kein unerwartetes Argument. Die 2'744
        gespeicherten Zeilen bleiben lesbar.
        """
        return self.qty * self.entry_price

    @property
    def margin(self) -> float:
        """Das tatsaechlich gebundene Kapital: Notional durch Hebel.

        Nicht zu verwechseln mit `risk_amount`. Die Margin ist, was auf dem
        Konto blockiert war; das Risiko ist, was beim Stop verloren geht.
        Bei 10x Hebel und 1% Risiko liegen zwischen den beiden Zahlen
        ungefaehr sieben Mal -- und `config/risk.yaml` erklaert in seinen
        ersten Zeilen, dass genau diese Verwechslung Geld kostet.
        """
        return self.notional / self.leverage if self.leverage else 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> JournalEntry:
        """Rebuild from storage, with the enums restored.

        `StrEnum` members compare equal to their strings, so leaving them as
        text would work until the first `is` comparison or `match` statement --
        which is the kind of bug that passes every test and fails once.
        """
        data: dict[str, Any] = json.loads(raw)
        reason = dict(data.pop("reason"))
        families = [FamilyNote(**note) for note in reason.pop("families", [])]
        post = dict(data.pop("post_mortem"))
        data["source"] = Source(data["source"])
        data["exit_reason"] = ExitReason(data["exit_reason"])
        return cls(
            **data,
            reason=TradeReason(**reason, families=families),
            post_mortem=PostMortem(**post),
        )
