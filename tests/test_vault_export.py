"""Writing trades into a notebook someone also writes in by hand.

The property that matters most here is not what gets written but what survives.
A sync job that overwrites a person's own notes is worse than no sync job: the
notes are the reason to put trades in a vault rather than leaving them in the
database, and losing them once is enough to stop trusting the whole thing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from traidingbrain.domain.enums import ExitReason, ProposalStatus, Side, TradeState
from traidingbrain.domain.proposal import FactorView, TradeProposal
from traidingbrain.reporting.vault import HANDOFF, note_name, write_trade
from traidingbrain.sim.broker import Fill

HOUR = 3_600_000
OPENED = 1_790_000_000_000


def fill(*, r: float = 1.5, side: Side = Side.LONG, reason: ExitReason = ExitReason.TARGET) -> Fill:
    risk = 100.0
    return Fill(
        proposal_id="p-1",
        snapshot_hash="a" * 64,
        side=side,
        state=TradeState.CLOSED_TARGET,
        reason=reason,
        entry_price=86_000.0,
        exit_price=87_000.0,
        qty=0.137,
        leverage=10.0,
        opened_ts=OPENED,
        closed_ts=OPENED + 5 * HOUR,
        gross_pnl=r * risk,
        fees=0.0,
        funding=0.0,
        risk_amount=risk,
    )


def proposal(**overrides: object) -> TradeProposal:
    base = {
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "entry": 86_000.0,
        "stop": 85_000.0,
        "target": 88_000.0,
        "qty": 0.137,
        "leverage": 10.0,
        "notional": 11_782.0,
        "margin": 1_178.2,
        "liquidation_price": 78_000.0,
        "risk_amount": 100.0,
        "risk_pct": 0.01,
        "equity_at_build": 10_000.0,
        "bias": "bullish",
        "confidence": 75.0,
        "risk_level": "medium",
        "snapshot_hash": "a" * 64,
        "status": ProposalStatus.PENDING,
        "reasoning": ["H4 and H1 agree", "sell-side swept and held"],
        "invalidation_note": "a close back below the swept low",
    }
    base.update(overrides)
    return TradeProposal(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# What survives
# --------------------------------------------------------------------------- #


def test_hand_written_notes_survive_a_rewrite(tmp_path: Path) -> None:
    """The one that matters. Losing these once is enough to stop trusting it."""
    write_trade(tmp_path, fill(), proposal())
    path = next((tmp_path / "Business/traidingBrain/Trades").glob("*.md"))

    edited = path.read_text(encoding="utf-8") + "\nIch war zu früh drin. Warten lernen.\n"
    path.write_text(edited, encoding="utf-8")

    write_trade(tmp_path, fill(r=2.0), proposal(confidence=80.0))

    assert "Ich war zu früh drin" in path.read_text(encoding="utf-8")


def test_an_unchanged_trade_is_not_rewritten(tmp_path: Path) -> None:
    """The fingerprint is sha256, not Python's hash().

    hash() is salted per process, so a fingerprint built on it differs on every
    run: the note would be rewritten each time and its modification date would
    stop meaning anything -- which in a notebook is how you lose track of what
    you actually touched.
    """
    first = write_trade(tmp_path, fill(), proposal())
    second = write_trade(tmp_path, fill(), proposal())

    assert first.created is True
    assert second.skipped is True


def test_a_changed_trade_is_rewritten(tmp_path: Path) -> None:
    write_trade(tmp_path, fill(), proposal())
    again = write_trade(tmp_path, fill(), proposal(confidence=90.0))

    assert again.skipped is False
    assert again.created is False


def test_the_marker_is_present_from_the_first_write(tmp_path: Path) -> None:
    """Without it the first hand-written line has nowhere safe to go."""
    result = write_trade(tmp_path, fill(), proposal())

    assert HANDOFF in result.path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# What is written
# --------------------------------------------------------------------------- #


def test_the_filename_shows_the_outcome(tmp_path: Path) -> None:
    """A folder of trades is browsed by name, so the name has to carry the result."""
    name = note_name(fill(r=1.82), "BTCUSDT")

    assert name.startswith("2026-")
    assert "BTCUSDT" in name and "long" in name and "+1.82R" in name


def test_a_loss_is_named_as_one(tmp_path: Path) -> None:
    assert "-0.90R" in note_name(fill(r=-0.9), "ETHUSDT")


def test_frontmatter_carries_typed_fields_dataview_can_query(tmp_path: Path) -> None:
    """Prose cannot be queried. The numbers go in the frontmatter, typed."""
    result = write_trade(tmp_path, fill(r=1.5), proposal())
    text = result.path.read_text(encoding="utf-8")

    assert "typ: trade" in text
    assert "symbol: BTCUSDT" in text
    assert "r_multiple: 1.500" in text
    assert "ergebnis: gewinn" in text


def test_the_argument_is_recorded_not_just_the_numbers(tmp_path: Path) -> None:
    """A note with the result and no reasoning cannot be disagreed with later."""
    result = write_trade(
        tmp_path,
        fill(),
        proposal(
            factors=[
                FactorView(
                    factor="structure",
                    score=0.8,
                    certainty=0.9,
                    weight=0.55,
                    contribution=19.8,
                    reasoning="H4 and H1 both bullish",
                )
            ]
        ),
    )
    text = result.path.read_text(encoding="utf-8")

    assert "H4 and H1 both bullish" in text
    assert "+19.8" in text
    assert "sell-side swept and held" in text
    assert "a close back below the swept low" in text


def test_a_capped_confidence_says_so(tmp_path: Path) -> None:
    """The cap is part of the arithmetic, and a note that hides it does not add up."""
    result = write_trade(
        tmp_path,
        fill(),
        proposal(
            confidence=75.0,
            confidence_raw=78.8,
            confidence_cap_reason="the history index holds too few comparable cases",
        ),
    )

    assert "78.8" in result.path.read_text(encoding="utf-8")


def test_a_fill_without_its_proposal_still_produces_a_note(tmp_path: Path) -> None:
    """A fill can outlive the proposal. Numbers without the argument beat nothing."""
    result = write_trade(tmp_path, fill(), None)

    assert result.path.exists()
    assert "Netto" in result.path.read_text(encoding="utf-8")


@pytest.mark.parametrize("reason", [ExitReason.STOP, ExitReason.TARGET, ExitReason.LIQUIDATION])
def test_every_exit_reason_renders(tmp_path: Path, reason: ExitReason) -> None:
    result = write_trade(tmp_path, fill(reason=reason), proposal())

    assert reason.value in result.path.read_text(encoding="utf-8")


def test_the_note_refuses_to_read_one_trade_as_evidence(tmp_path: Path) -> None:
    """The line that keeps a winning note from being read as a working strategy."""
    result = write_trade(tmp_path, fill(r=3.0), proposal())

    assert "beweist nichts" in result.path.read_text(encoding="utf-8")
