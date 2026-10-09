"""The paper journal: what was done, why, and what became of it.

Two properties carry this file. The first is that a trade's reasoning is
recovered from its own decision bar and not from a later one -- the whole
journal is worthless if the "why" is contaminated by what happened next, and
the recovery goes through the proposal id, which nothing else in the system
treats as a parseable thing.

The second is that replay and live trades never share an average. A stretch of
history chosen by somebody who knows how it went is weaker evidence than a week
of forward trades, and the day the two are summed together the number describes
neither.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from traidingbrain.data.grid import timeframe_ms
from traidingbrain.domain.enums import ExitReason, OrderType, Side, Timeframe
from traidingbrain.journal.build import decision_index
from traidingbrain.journal.postmortem import examine
from traidingbrain.journal.record import (
    FamilyNote,
    JournalEntry,
    PostMortem,
    Source,
    TradeReason,
)
from traidingbrain.journal.store import JournalStore
from traidingbrain.sim.broker import OpenPosition, PendingEntry

H1_MS = timeframe_ms(Timeframe.H1)


def bars(count: int, *, high: float, low: float, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": np.arange(count, dtype="int64") * H1_MS,
            "open": np.full(count, 100.0),
            "high": np.full(count, high),
            "low": np.full(count, low),
            "close": np.full(count, close),
            "volume": np.full(count, 1.0),
        }
    )


def reason(**overrides: object) -> TradeReason:
    base: dict[str, object] = {
        "setup_key": "A",
        "setup_name": "Momentum-Ausbruch",
        "setup_source": "V08",
        "setup_timeframe": "H1",
        "side": "long",
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "reward_risk": 2.0,
        "stop_distance_pct": 2.0,
        "rating": 71,
        "rating_band": "gemischt",
        "clarity": 0.4,
        "agreement": 0.8,
        "consensus": 0.7,
        "coverage": 0.7,
        "score_bullish": 1.2,
        "score_bearish": 0.3,
        "score_direction": "aufwärts",
        "conflict": 0.4,
        "breadth": 6,
        "readings": 190,
        "regime": "trend_up",
    }
    base.update(overrides)
    return TradeReason(**base, families=[])  # type: ignore[arg-type]


def entry(trade_id: str = "BTCUSDT-1000", **overrides: object) -> JournalEntry:
    base: dict[str, object] = {
        "trade_id": trade_id,
        "source": Source.REPLAY,
        "symbol": "BTCUSDT",
        "strategy": "guide",
        "opened_ts": 0,
        "closed_ts": H1_MS * 5,
        "exit_reason": ExitReason.STOP,
        "entry_price": 100.0,
        "exit_price": 98.0,
        "qty": 1.0,
        "leverage": 5.0,
        "risk_amount": 100.0,
        "gross_pnl": -100.0,
        "fees": 1.0,
        "funding": 0.0,
        "net_pnl": -101.0,
        "r_multiple": -1.01,
        "reason": reason(),
        "post_mortem": PostMortem(5, 0.0, 1.0, 0.0, False, True, "Sofort gegen uns."),
    }
    base.update(overrides)
    return JournalEntry(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The record survives storage
# --------------------------------------------------------------------------- #


def test_a_trade_round_trips_through_json() -> None:
    """Every field, including the nested reason and post-mortem. A journal that
    lost its families on the way to disk would still print a tidy report."""
    original = entry()
    original.reason.families.append(FamilyNote("structure", "bullish", 0.57, 0.67, 0.65, False))

    restored = JournalEntry.from_json(original.to_json())

    assert restored == original
    assert restored.reason.families[0].family == "structure"


def test_the_enums_come_back_as_enums() -> None:
    """`StrEnum` members compare equal to their strings, so leaving them as
    text works until the first `is` comparison -- which passes every test and
    then fails once, in a report nobody re-reads."""
    restored = JournalEntry.from_json(entry().to_json())

    assert restored.source is Source.REPLAY
    assert restored.exit_reason is ExitReason.STOP


def test_storing_the_same_trade_twice_does_not_double_it(tmp_path: Path) -> None:
    """Re-running a replay over a period already recorded must correct it, not
    append it. A journal that grew on every re-run would inflate every count in
    every report built from it."""
    store = JournalStore(tmp_path / "journal.sqlite")

    store.record([entry()])
    store.record([entry(r_multiple=2.0)])

    held = store.all()
    assert len(held) == 1
    assert held[0].r_multiple == 2.0


def test_replay_and_live_can_be_read_apart(tmp_path: Path) -> None:
    """The split that stops a chosen stretch of history from being averaged
    with trades whose future had not happened yet."""
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record(
        [
            entry("a", source=Source.REPLAY),
            entry("b", source=Source.LIVE),
            entry("c", source=Source.LIVE),
        ]
    )

    assert store.count(source=Source.LIVE) == 2
    assert store.count(source=Source.REPLAY) == 1
    assert {e.trade_id for e in store.all(source=Source.LIVE)} == {"b", "c"}


def test_trades_come_back_oldest_first(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([entry("late", opened_ts=5000), entry("early", opened_ts=10)])

    assert [e.trade_id for e in store.all()] == ["early", "late"]


# --------------------------------------------------------------------------- #
# Why it ended that way
# --------------------------------------------------------------------------- #


def test_a_stop_taken_by_a_wick_is_recognised() -> None:
    """The loss people argue with, counted instead of remembered.

    The low reaches the stop and the bar closes back above it. Whether that
    happens twice or two hundred times is a question about where the stops sit,
    and it cannot be asked unless something records it.
    """
    frame = bars(5, high=103.0, low=97.0, close=101.0)

    post = examine(
        frame,
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=0,
        closed_ts=H1_MS * 4,
        exit_price=98.0,
        exit_reason=ExitReason.STOP,
        r_multiple=-1.0,
    )

    assert post.stopped_by_wick
    assert "Docht" in post.verdict


def test_a_stop_the_price_closed_through_is_not_a_wick() -> None:
    frame = bars(5, high=101.0, low=97.0, close=97.5)

    post = examine(
        frame,
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=0,
        closed_ts=H1_MS * 4,
        exit_price=98.0,
        exit_reason=ExitReason.STOP,
        r_multiple=-1.0,
    )

    assert not post.stopped_by_wick


def test_a_trade_that_was_never_in_profit_says_so() -> None:
    """A different fault from one that ran a point in your favour and turned.
    The first is a question about the entry, the second about the exit, and
    "ausgestoppt" answers neither."""
    frame = bars(4, high=100.0, low=96.0, close=97.0)

    post = examine(
        frame,
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=0,
        closed_ts=H1_MS * 3,
        exit_price=98.0,
        exit_reason=ExitReason.STOP,
        r_multiple=-1.0,
    )

    assert post.never_in_profit
    assert "nie im plus" in post.verdict.lower()


def test_how_far_it_ran_each_way_is_measured_in_risk() -> None:
    """R rather than price, so a BTC trade and an XRP trade can be compared --
    which is the only reason to keep two hundred of them in one table."""
    frame = bars(4, high=104.0, low=99.0, close=103.0)

    post = examine(
        frame,
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=0,
        closed_ts=H1_MS * 3,
        exit_price=104.0,
        exit_reason=ExitReason.TARGET,
        r_multiple=2.0,
    )

    assert post.max_favourable_r == pytest.approx(2.0)
    assert post.max_adverse_r == pytest.approx(0.5)


def test_a_short_reads_its_extremes_the_other_way_round() -> None:
    """The sign flip is the whole arithmetic, and getting it backwards would
    report every winning short as a disaster."""
    frame = bars(4, high=102.0, low=96.0, close=97.0)

    post = examine(
        frame,
        side=Side.SHORT,
        entry=100.0,
        stop=102.0,
        opened_ts=0,
        closed_ts=H1_MS * 3,
        exit_price=96.0,
        exit_reason=ExitReason.TARGET,
        r_multiple=2.0,
    )

    assert post.max_favourable_r == pytest.approx(2.0)
    assert post.max_adverse_r == pytest.approx(1.0)


def test_no_bars_between_entry_and_exit_is_said_rather_than_guessed() -> None:
    post = examine(
        bars(3, high=101.0, low=99.0, close=100.0),
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=H1_MS * 50,
        closed_ts=H1_MS * 60,
        exit_price=98.0,
        exit_reason=ExitReason.STOP,
        r_multiple=-1.0,
    )

    assert post.bars_held == 0
    assert "keine Kursdaten" in post.verdict


def test_the_closing_bar_cannot_report_movement_after_the_exit() -> None:
    """Der Defekt, der 25,3 % der ausgestoppten Trades betraf.

    Am 07.10.2026 im gespeicherten Journal gefunden: `max_adverse_r` erreichte
    **147,88** auf einem Trade, der nach `bars_held = 1` bei -0,036 R
    ausgestoppt wurde. Ein bei etwa -1 R geschlossener Trade kann das nicht
    erlebt haben -- es war das Tief der ganzen Abschlusskerze, also Bewegung
    *nach* dem Ausstieg.

    Hier nachgebaut: zwei Kerzen, die zweite stürzt auf 50 ab, der Trade wird
    aber bei 98 ausgestoppt. Die alte Fassung hätte
    (100 - 50) / 2 = **25 R** gemeldet.
    """
    frame = pd.DataFrame(
        {
            "ts": np.array([0, H1_MS], dtype="int64"),
            "open": [100.0, 99.0],
            "high": [101.0, 99.0],
            "low": [99.0, 50.0],  # der Absturz liegt NACH dem Ausstieg
            "close": [100.0, 50.0],
            "volume": [1.0, 1.0],
        }
    )

    post = examine(
        frame,
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=0,
        closed_ts=H1_MS,
        exit_price=98.0,
        exit_reason=ExitReason.STOP,
        r_multiple=-1.0,
    )

    assert post.max_adverse_r == pytest.approx(1.0), (
        "Der Trade endete am Stop, also ist 1 R das Aeusserste, was er gesehen hat"
    )
    assert post.bars_held == 2, "Die Dauer bleibt die Spanne, auch ohne innere Kerze"


def test_the_opening_bar_cannot_report_movement_before_the_entry() -> None:
    """Dieselbe Verunreinigung am anderen Rand, und sie fällt seltener auf.

    Die Eröffnungskerze enthält alles, was vor dem Einstieg passierte. Ein
    Hoch, das eine Stunde vor dem Einstieg lag, ist kein Gewinn, den der Trade
    im Plus war.
    """
    frame = pd.DataFrame(
        {
            "ts": np.array([0, H1_MS, 2 * H1_MS], dtype="int64"),
            "open": [100.0, 100.0, 100.0],
            "high": [140.0, 101.0, 101.0],  # der Spike liegt VOR dem Einstieg
            "low": [99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 100.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )

    post = examine(
        frame,
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        opened_ts=0,
        closed_ts=2 * H1_MS,
        exit_price=100.5,
        exit_reason=ExitReason.TARGET,
        r_multiple=0.25,
    )

    assert post.max_favourable_r == pytest.approx(0.5), (
        "Das Hoch von 140 lag vor dem Einstieg; der Trade sah 100.5"
    )


def test_a_stop_at_the_entry_price_cannot_be_divided_by() -> None:
    """Risk of zero is a bad record, not a crash. It reaches here from a setup
    whose stop and entry rounded to the same tick."""
    post = examine(
        bars(3, high=101.0, low=99.0, close=100.0),
        side=Side.LONG,
        entry=100.0,
        stop=100.0,
        opened_ts=0,
        closed_ts=H1_MS * 2,
        exit_price=100.0,
        exit_reason=ExitReason.STOP,
        r_multiple=0.0,
    )

    assert post.max_favourable_r == 0.0


# --------------------------------------------------------------------------- #
# Where the reasoning is recovered from
# --------------------------------------------------------------------------- #


def test_the_decision_bar_is_recovered_from_the_proposal_id() -> None:
    """The one place in the system that parses an id rather than storing the
    link. The engine builds `{symbol}-{close_of_decision_bar}`; if that format
    changes, every journal row silently loses its reasoning and the report
    still prints. This test is what makes that loud."""

    class FakeMulti:
        class signal:  # noqa: N801 - a stand-in, not a type
            @staticmethod
            def column(_name: str) -> np.ndarray:
                return np.arange(10, dtype="int64") * H1_MS

    found = decision_index(FakeMulti, "BTCUSDT-" + str(3 * H1_MS + H1_MS), Timeframe.H1)  # type: ignore[arg-type]

    assert found == 3


def test_an_id_without_a_timestamp_yields_nothing_rather_than_a_wrong_bar() -> None:
    class FakeMulti:
        class signal:  # noqa: N801
            @staticmethod
            def column(_name: str) -> np.ndarray:
                return np.arange(10, dtype="int64") * H1_MS

    assert decision_index(FakeMulti, "no-timestamp-here", Timeframe.H1) is None  # type: ignore[arg-type]


def test_a_row_written_before_the_cadence_was_recorded_still_opens() -> None:
    """The field was added on 04.10.2026, when the loop moved from hourly to
    fifteen-minute decisions. Rows already in the journal have no such key, and
    a journal that could not read its own history would have thrown away the
    only forward trades the project has.

    Empty is the right answer for those rows rather than a guess: they are the
    hourly ones, and the emptiness says when they were written.
    """
    built = entry()
    payload = json.loads(built.to_json())
    del payload["reason"]["signal_timeframe"]

    restored = JournalEntry.from_json(json.dumps(payload))

    assert restored.reason.signal_timeframe == ""
    assert restored.reason.setup_key == built.reason.setup_key


# --------------------------------------------------------------------------- #
# Wie viel Geld ging in den Trade, und mit welchem Hebel
#
# Der Nutzer verlangt das bei jedem Papertrade protokolliert. Die Zahlen lagen
# immer im Journal und waren nirgends zu sehen; diese Tests halten die
# Arithmetik fest, damit die Anzeige nicht vom Konto abdriftet. Jeder Wert
# unten ist von Hand gerechnet, nicht aus der Implementierung abgelesen.
# --------------------------------------------------------------------------- #


def test_the_notional_is_quantity_times_the_entry_price() -> None:
    """2,5 Einheiten zu 400 sind 1000. Nachgerechnet, nicht nachgeschlagen."""
    assert entry(qty=2.5, entry_price=400.0).notional == pytest.approx(1000.0)


def test_the_notional_uses_the_entry_price_and_not_the_exit() -> None:
    """Die Frage ist, womit man REIN ging.

    Mit dem Ausstiegspreis gerechnet waere es die Groesse, mit der man
    herauskam -- bei einem Gewinner eine groessere Zahl und eine andere
    Frage. Hier verdoppelt sich der Preis, und das Notional darf sich nicht
    bewegen.
    """
    opened_at_100 = entry(qty=3.0, entry_price=100.0, exit_price=200.0)
    assert opened_at_100.notional == pytest.approx(300.0)


def test_the_margin_is_the_notional_divided_by_the_leverage() -> None:
    """1000 Notional bei 10x sind 100 gebunden; bei 1x die ganzen 1000."""
    assert entry(qty=10.0, entry_price=100.0, leverage=10.0).margin == pytest.approx(100.0)
    assert entry(qty=10.0, entry_price=100.0, leverage=1.0).margin == pytest.approx(1000.0)


def test_margin_times_leverage_returns_the_notional() -> None:
    """Die Identitaet, die beide Zahlen aneinander bindet."""
    for leverage in (1.0, 2.0, 5.0, 10.0, 25.0):
        trade = entry(qty=7.0, entry_price=13.5, leverage=leverage)
        assert trade.margin * leverage == pytest.approx(trade.notional)


def test_the_margin_matches_what_the_broker_actually_reserves() -> None:
    """Dieselbe Rechnung wie `sim/broker.py::fill`, nicht eine zweite.

    Dort steht `notional = qty * price` und `margin = notional / leverage`.
    Drifteten die beiden auseinander, wuerde die Anzeige einen Betrag
    behaupten, den das Konto nie gebunden hat -- und das waere genau die
    Art Zahl, die man glaubt.
    """
    position = OpenPosition(
        side=Side.LONG,
        entry_price=13.923,
        qty=50.95,
        leverage=10.0,
        stop=13.72,
        target=14.4,
        liq_price=12.6,
        opened_ts=0,
        margin=50.95 * 13.923 / 10.0,
        risk_amount=10.09,
    )
    journalled = entry(qty=50.95, entry_price=13.923, leverage=10.0)
    assert journalled.notional == pytest.approx(position.notional)
    assert journalled.margin == pytest.approx(position.margin)


def test_a_missing_leverage_does_not_divide_by_zero() -> None:
    """Null Hebel ist kein gueltiger Trade, aber ein Absturz in der Anzeige
    waere die schlechtere Antwort als eine Null."""
    assert entry(qty=1.0, entry_price=100.0, leverage=0.0).margin == 0.0


def test_the_margin_is_not_the_risk() -> None:
    """Die Verwechslung, die `config/risk.yaml` in seinen ersten Zeilen warnt.

    Eine Position von 1000 mit einem Stop 3% entfernt riskiert 30, nicht
    1000 -- und bindet bei 10x Hebel 100. Drei Zahlen, die alle
    verschieden sind, und keine davon darf fuer eine andere stehen.
    """
    trade = entry(qty=10.0, entry_price=100.0, leverage=10.0, risk_amount=30.0)
    assert trade.notional == pytest.approx(1000.0)
    assert trade.margin == pytest.approx(100.0)
    assert trade.risk_amount == pytest.approx(30.0)
    assert trade.margin != trade.risk_amount


def test_the_computed_amounts_stay_out_of_the_stored_record() -> None:
    """Sonst waeren 2'744 gespeicherte Zeilen nicht mehr lesbar.

    `notional` und `margin` sind properties und keine dataclass-Felder, also
    nimmt `asdict()` sie nicht mit. Waeren sie Felder, bekaeme `from_json()`
    unerwartete Argumente und jede vorhandene Zeile wuerde beim Laden
    scheitern. Das ist kein theoretisches Risiko -- es ist der Grund fuer
    die Wahl.
    """
    stored = json.loads(entry().to_json())
    assert "notional" not in stored
    assert "margin" not in stored
    # Und der Beweis, dass es trotzdem zurueckkommt:
    assert JournalEntry.from_json(entry().to_json()).notional == pytest.approx(100.0)


def test_the_planned_amounts_of_an_unfilled_order_are_named_apart() -> None:
    """Eine Order fuellt nicht zwingend zum Limit, und vielleicht nie.

    Darum `planned_notional` statt `notional`: wer die Absicht als Tatsache
    berichtet, hat beim ersten abweichenden Fill eine falsche Zahl
    aufgeschrieben.
    """
    pending = PendingEntry(
        side=Side.LONG,
        order_type=OrderType.LIMIT,
        limit_price=50.0,
        stop=49.0,
        target=52.0,
        qty=4.0,
        leverage=4.0,
        created_ts=0,
        expires_ts=H1_MS,
        risk_amount=4.0,
    )
    assert pending.planned_notional == pytest.approx(200.0)
    assert pending.planned_margin == pytest.approx(50.0)
    assert not hasattr(pending, "notional"), "die Absicht darf nicht wie ein Fill heissen"


def test_the_entry_records_which_configuration_made_it() -> None:
    """Eine Eigenschaft, die man nur durch Git-Archaeologie findet, ist keine.

    Am 09.10.2026 war die Frage, ob die 18 Vorwaertstrades EINE Stichprobe
    sind -- entscheidend, weil eine Maechtigkeitsrechnung daran haengt. Aus dem
    Journal war das nicht zu beantworten: der Signaturbegriff existiert und der
    Signalspeicher traegt ihn je Zeile, der Journaleintrag aber nicht.
    Beantworten liess es sich nur ueber vier strategiewirksame
    Konfigurationsaenderungen in der Git-Historie, und die homogene Stichprobe
    waren 14 Trades statt 18.
    """
    made = entry(run_signature="1000.0|['A','B']|0.08|M15|refused-v1")
    assert made.run_signature == "1000.0|['A','B']|0.08|M15|refused-v1"
    # Und im gespeicherten Schema, sonst nuetzt das Feld im Objekt nichts.
    assert asdict(made)["run_signature"] == made.run_signature


def test_an_old_entry_without_a_signature_still_loads() -> None:
    """Alles vor dem 09.10.2026 traegt keine. Das darf nichts brechen."""
    assert entry().run_signature == ""


def test_the_signature_survives_the_store(tmp_path) -> None:
    """Ein neues Feld kann im Speicher still verschwinden.

    `JournalEntry` gewann `run_signature` am 09.10.2026, damit die Frage "sind
    diese Vorwaertstrades EINE Stichprobe" aus den Daten beantwortbar ist statt
    aus der Git-Historie. Ein Feld im Objekt nuetzt dafuer nichts, wenn der
    Speicher es beim Schreiben oder Lesen fallen laesst -- und genau das
    passiert, wenn irgendwo eine feste Spaltenliste steht.
    """
    signature = "1000.0|['A','B']|0.08|M15|refused-v1"
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([entry("BTCUSDT-1", run_signature=signature)])

    back = store.all()
    assert len(back) == 1
    assert back[0].run_signature == signature


def test_the_entry_records_the_commit_too(tmp_path) -> None:
    """Signatur UND Commit, weil keines allein die Frage entscheidet.

    Die Signatur deckt Konfiguration und verpasst Verhalten, das im Code
    wohnt -- am 09.10.2026 waren das eine geaenderte Ziel-Regel und eine
    zweite Strategiefamilie, und die homogene Stichprobe war 11 statt 14. Der
    Commit deckt den Code exakt, aendert sich aber auch, wenn nur ein Bericht
    geschrieben wird. Darum beide.
    """
    made = entry("BTCUSDT-1", run_signature="sig", code_version="abc1234")
    assert made.run_signature == "sig"
    assert made.code_version == "abc1234"

    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([made])
    back = store.all()[0]
    assert back.run_signature == "sig"
    assert back.code_version == "abc1234"
