"""Which exchange, decided in one place.

`config/settings.yaml` has carried `exchange.name: bybit` since the first commit,
next to a comment promising that switching venue is a config change rather than a
rewrite. Nothing read it. `ccxt.bybit` was constructed directly in the data source
and again in the executor, so the config said one thing and the code did another
-- and the only way to find out was to change the name and watch nothing happen.

This module makes the promise true. It is also the only place that knows a venue's
quirks, and there are exactly three that matter:

**The symbol spelling.** A USDT perpetual is `BTC/USDT:USDT` on Bybit and
`BTC/USDT` on Binance USD-M. ccxt unifies almost everything else; it does not
unify this, because the two venues genuinely model the instrument differently.

**Where sandbox lives.** Both support `set_sandbox_mode`, but Binance's futures
testnet is a separate host with separate accounts, and a mainnet key there fails
in a way that looks like a typo.

**What the account endpoints are called.** Reading a key's permissions is a raw
venue call on Bybit and does not exist in the same form on Binance. That check is
worth having where it exists and must not become a startup failure where it does
not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import ccxt

#: Venues this has been checked against. Adding one means filling in a Venue
#: below and running the conformance test, not editing a string here.
SUPPORTED = ("bybit", "binance")


class UnsupportedVenueError(ValueError):
    """A venue name nothing here knows how to build."""


@dataclass(frozen=True)
class Venue:
    """One exchange's answers to the questions ccxt does not unify."""

    name: str
    ccxt_id: str
    #: ccxt options that select USDT-margined perpetuals on this venue.
    market_options: dict[str, Any]
    #: How a bare `BTCUSDT` is spelled for this venue's unified methods.
    symbol_suffix: str
    #: True when the venue exposes a way to read an API key's own permissions.
    reports_key_rights: bool
    #: Which ccxt call puts the client into play money.
    #:
    #: Not the same on both, and getting it wrong is not a small difference. ccxt
    #: has deprecated `set_sandbox_mode` for Binance futures -- it now raises with
    #: a link to the announcement rather than switching hosts -- while
    #: `enable_demo_trading` routes to demo-dapi.binance.com and works. Bybit
    #: still uses sandbox mode for its testnet.
    #:
    #: Found by running the connection check, which is the only way it surfaces:
    #: public data answers on both settings, so the failure waits for the first
    #: call that touches an account.
    practice_mode: str = "set_sandbox_mode"

    def symbol(self, symbol: str) -> str:
        """`BTCUSDT` in this venue's unified spelling.

        Rejects anything that is not a USDT-quoted perpetual here rather than at
        the venue, where the error is a generic parameter complaint that says
        nothing about which symbol caused it.
        """
        if "/" in symbol:
            return symbol
        if not symbol.endswith("USDT"):
            raise ValueError(f"only USDT-quoted perpetuals are supported, got {symbol!r}")
        return f"{symbol[: -len('USDT')]}/USDT{self.symbol_suffix}"

    def build(
        self,
        *,
        testnet: bool,
        rate_limit_ms: int,
        api_key: str = "",
        api_secret: str = "",
    ) -> Any:
        """A configured ccxt client. Credentials are optional and often absent.

        Market data needs none -- reading public prices touches no account -- so
        passing empty strings here is the normal case for everything except the
        executor.
        """
        settings: dict[str, Any] = {
            "enableRateLimit": True,
            "rateLimit": rate_limit_ms,
            "options": dict(self.market_options),
        }
        if api_key:
            settings["apiKey"] = api_key
            settings["secret"] = api_secret

        client = getattr(ccxt, self.ccxt_id)(settings)
        if testnet:
            getattr(client, self.practice_mode)(True)
        return client


VENUES: dict[str, Venue] = {
    "bybit": Venue(
        name="bybit",
        ccxt_id="bybit",
        market_options={"defaultType": "swap", "defaultSubType": "linear"},
        symbol_suffix=":USDT",
        reports_key_rights=True,
        practice_mode="set_sandbox_mode",
    ),
    "binance": Venue(
        name="binance",
        ccxt_id="binanceusdm",
        # binanceusdm is already the USD-M futures client, so the type is implied
        # rather than selected. Setting defaultType here would be redundant at
        # best and, on some ccxt versions, would route spot calls into it.
        market_options={"defaultType": "future"},
        symbol_suffix="",
        # Binance has no unified equivalent of Bybit's key-permission endpoint.
        # The check is skipped rather than faked: a permissive guess would be a
        # safety check that reports success without having run.
        reports_key_rights=False,
        # ccxt refuses set_sandbox_mode on Binance futures now; demo trading is
        # the supported replacement and routes to demo-dapi.binance.com.
        practice_mode="enable_demo_trading",
    ),
}


def venue(name: str) -> Venue:
    """Look a venue up by the name in settings.yaml."""
    found = VENUES.get(name.strip().lower())
    if found is None:
        raise UnsupportedVenueError(
            f"{name!r} is not a venue this build knows; supported: {', '.join(SUPPORTED)}"
        )
    return found
