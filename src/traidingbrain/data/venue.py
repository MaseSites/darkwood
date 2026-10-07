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

#: Venues this has been checked against **and that may be traded on**.
#: `config/settings.yaml` must name one of these; `tests/test_config.py`
#: enforces it. Adding one means filling in a Venue below and running the
#: conformance test, not editing a string here.
SUPPORTED = ("bybit", "binance")

#: Venues that may be READ and must never be configured for trading.
#:
#: The distinction is deliberate and is a safety boundary, not bookkeeping.
#: `binance_spot` exists so the basis of E6.1 can be measured; it is not a
#: place this system places orders. Keeping it out of `SUPPORTED` means a
#: `settings.yaml` naming it is refused at load, before anything connects --
#: which is the point at which a mistake is still cheap.
#:
#: If a data-only venue should ever become tradable, that is a decision with
#: its own review (account rights, order protection, the held confirmation),
#: and moving a string between these two tuples is not that review.
DATA_ONLY = ("binance_spot",)


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

        Rejects anything that is not USDT-quoted here rather than at the venue,
        where the error is a generic parameter complaint that says nothing
        about which symbol caused it.
        """
        if "/" in symbol:
            return symbol
        if not symbol.endswith("USDT"):
            raise ValueError(
                f"only USDT-quoted markets are supported on {self.name}, got {symbol!r}"
            )
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
    # SPOT, and it exists for one reason: the basis.
    #
    # E6.1 is "spot long against perp short, SAME VENUE". Its registered
    # blocker was "keine Spot-Reihe auf der Platte, also Basisrisiko
    # ungemessen" -- and the basis is the whole risk of that trade. Funding
    # is collected on the perp leg; what can go wrong is the two legs
    # drifting apart. Measuring that needs both series from one exchange on
    # one clock, which is exactly what a cross-venue substitute cannot give.
    #
    # Eight of the twelve markets carry BINANCE funding (ADA, ATOM, AVAX,
    # BNB, DOGE, DOT, LINK, LTC; the other four are Bybit), and the perp
    # candles are Binance throughout. So for those eight, and only those,
    # spot + perp + funding are one venue and E6.1 is answerable.
    #
    # `ccxt.binance` is the spot client; `binanceusdm` above is the futures
    # one. They are separate clients on purpose -- the comment above warns
    # that setting defaultType on the futures client can route spot calls
    # into it, and this entry is the other half of that separation.
    #
    # **This is a research data source.** It holds no credentials and the
    # executor does not read it: `execution/` resolves its venue from
    # `config/settings.yaml`, which selects a perpetual venue, and reaching
    # the exchange at all still requires the server-issued confirmation
    # token. Adding a readable venue does not add a path to an order.
    "binance_spot": Venue(
        name="binance_spot",
        ccxt_id="binance",
        market_options={"defaultType": "spot"},
        symbol_suffix="",
        reports_key_rights=False,
        practice_mode="set_sandbox_mode",
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
