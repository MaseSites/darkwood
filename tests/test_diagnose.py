"""Exchange rejections, read back as instructions.

These assert something unusual for a test suite: not that the code behaves
correctly, but that a person reading the output learns the right next action.
That is worth pinning, because the failure this module exists to prevent is not a
wrong result -- it is a correct result nobody can act on.

The distinction that matters most is between 10003 and 10005. Both are fatal,
both mention the key, and they have nothing in common: one means the key does not
exist where it was looked for, the other means it exists and may not trade.
"""

from __future__ import annotations

import pytest

from traidingbrain.execution.diagnose import diagnose


def bybit(code: str, message: str = "something") -> Exception:
    """A rejection shaped the way ccxt actually delivers one."""
    return Exception(f'bybit {{"retCode":{code},"retMsg":"{message}","result":{{}}}}')


def test_an_unknown_key_explains_the_three_environments() -> None:
    """The single most likely cause, and the one nothing else hints at.

    Bybit runs testnet, demo and live as separate worlds with separate keys. A
    key from the wrong one is valid, correctly copied, and rejected -- so without
    naming the environments the message sends someone to re-check a key that has
    nothing wrong with it.
    """
    rendered = diagnose(bybit("10003"), testnet=True).render()

    assert "testnet.bybit.com" in rendered
    assert "bybit.com > Demo" in rendered
    assert "TB_BYBIT__TESTNET" in rendered


def test_the_environment_note_follows_the_setting_it_describes() -> None:
    live = diagnose(bybit("10003"), testnet=False).render()

    assert "MAINNET" in live
    assert "pointed at bybit.com" in live


def test_a_bad_signature_points_at_the_secret_not_the_key() -> None:
    """Being found and being rejected are different halves of the credential."""
    rendered = diagnose(bybit("10004")).render()

    assert "TB_BYBIT__API_SECRET" in rendered
    assert "shown only once" in rendered


def test_a_permission_failure_names_the_checkbox() -> None:
    """The Bybit UI has a master Read-Only switch above the per-product grid.

    Leaving it on Read-Only makes every trade permission below it inert, which is
    a mistake worth naming precisely rather than describing as "check your
    permissions".
    """
    rendered = diagnose(bybit("10005")).render()

    assert "Read-Write" in rendered
    assert "Trade" in rendered


def test_a_regulatory_refusal_says_it_is_not_fixable_here() -> None:
    """Sending someone back to re-check .env for this would waste their evening."""
    diagnosis = diagnose(bybit("10024"))

    assert "account" in diagnosis.detail
    assert "no setting here will change it" in diagnosis.detail


@pytest.mark.parametrize("code", ["10006", "10016"])
def test_a_venue_fault_is_marked_as_not_the_user_s_problem(code: str) -> None:
    assert diagnose(bybit(code)).fixable_by_user is False


def test_a_network_failure_states_that_nothing_was_sent() -> None:
    """The first question after a failure mid-order is whether an order exists."""
    diagnosis = diagnose(Exception("Connection to api.bybit.com timed out"))

    assert "Nothing was sent" in diagnosis.detail
    assert diagnosis.fixable_by_user is False


def test_an_unrecognised_failure_quotes_the_exchange_verbatim() -> None:
    """Inventing an explanation for an unknown code would be worse than none."""
    diagnosis = diagnose(bybit("44444", "some brand new thing"))

    assert "some brand new thing" in diagnosis.detail
    assert diagnosis.fixable_by_user is False


def test_every_diagnosis_renders_indented_and_multi_line() -> None:
    """The output lands inside a startup log and has to stay readable there."""
    rendered = diagnose(bybit("10003")).render(indent="    ")

    assert all(line.startswith("    ") for line in rendered.splitlines() if line.strip())
