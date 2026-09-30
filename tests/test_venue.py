"""The venue is a configuration choice, and this is what makes that true.

`settings.yaml` carried `exchange.name: bybit` from the first commit, beside a
comment promising that switching venue was a config change rather than a rewrite.
Nothing read it: `ccxt.bybit` was constructed directly in the data source and
again in the executor. The config described a choice the code did not offer, and
the only way to discover that was to change the name and watch nothing happen.

So the test that matters here is not that two venues exist. It is that the name
in the file reaches the client that gets built.
"""

from __future__ import annotations

import pytest

from traidingbrain.config.settings import load_config
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.venue import SUPPORTED, UnsupportedVenueError, venue


def test_the_configured_name_decides_which_client_is_built() -> None:
    """The whole point. Without this the config field is decoration."""
    assert MarketData(venue_name="bybit").exchange.id == "bybit"
    assert MarketData(venue_name="binance").exchange.id == "binanceusdm"


def test_the_shipped_configuration_names_a_venue_that_exists() -> None:
    """A typo here would surface as a crash at the first fetch, not at load."""
    name = load_config().engine.exchange.name

    assert name in SUPPORTED
    assert venue(name).ccxt_id


def test_an_unknown_venue_is_refused_with_the_list() -> None:
    with pytest.raises(UnsupportedVenueError, match="supported"):
        venue("kraken")


# --------------------------------------------------------------------------- #
# The three things ccxt does not unify
# --------------------------------------------------------------------------- #


def test_the_same_instrument_is_spelled_differently_per_venue() -> None:
    """A USDT perpetual is `BTC/USDT:USDT` on one and `BTC/USDT` on the other.

    Not a quirk worth hiding: the two venues model the instrument differently,
    and a single hardcoded spelling silently queries the wrong market on one of
    them rather than failing.
    """
    assert venue("bybit").symbol("BTCUSDT") == "BTC/USDT:USDT"
    assert venue("binance").symbol("BTCUSDT") == "BTC/USDT"


@pytest.mark.parametrize("name", SUPPORTED)
def test_an_already_unified_symbol_passes_through(name: str) -> None:
    assert venue(name).symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"


@pytest.mark.parametrize("name", SUPPORTED)
def test_a_non_usdt_instrument_is_refused_here_rather_than_at_the_venue(name: str) -> None:
    """The venue's own error names a parameter, not the symbol that caused it."""
    with pytest.raises(ValueError, match="USDT"):
        venue(name).symbol("BTCUSD")


def test_only_the_venue_that_reports_key_rights_claims_to() -> None:
    """Reading an API key's permissions is a Bybit endpoint with no Binance twin.

    Flagged rather than guessed. A permissive default would make the executor's
    'this key may not trade' check report success without having run, which is
    worse than not having the check at all -- one is an absent safeguard, the
    other is a safeguard that lies.
    """
    assert venue("bybit").reports_key_rights is True
    assert venue("binance").reports_key_rights is False


@pytest.mark.parametrize("name", SUPPORTED)
def test_credentials_are_only_attached_when_there_are_any(name: str) -> None:
    """Market data touches no account, so the usual case has no key at all."""
    public = venue(name).build(testnet=False, rate_limit_ms=100)
    private = venue(name).build(testnet=False, rate_limit_ms=100, api_key="k", api_secret="s")

    assert not public.apiKey
    assert private.apiKey == "k"


@pytest.mark.parametrize("name", SUPPORTED)
def test_testnet_actually_changes_where_requests_go(name: str) -> None:
    """Both venues run separate sandbox hosts with separate accounts."""
    live = venue(name).build(testnet=False, rate_limit_ms=100)
    sandbox = venue(name).build(testnet=True, rate_limit_ms=100)

    assert live.urls["api"] != sandbox.urls["api"]
