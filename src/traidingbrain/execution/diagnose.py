"""Turning an exchange's rejection into something a person can act on.

A failed connection is one of the few errors here that a user, not a developer,
has to fix -- and it arrives as a thirty-line ccxt traceback ending in a four
digit code. That is indistinguishable from a crash, and the reasonable reaction
to it is to assume the program is broken rather than that a key is wrong.

Every code below names a *different* thing to do, which is the whole reason this
exists. "API key is invalid" and "permission denied" look equally fatal and have
nothing in common: the first means the key does not exist where it was looked
for, usually because it was created in another of Bybit's three environments; the
second means it exists and is not allowed to trade.

Nothing here changes behaviour. It changes what the person reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Bybit puts a numeric code in the body of every rejection. It survives ccxt's
#: wrapping because the raw JSON is appended to the exception message.
_BYBIT_CODE = re.compile(r'"retCode"\s*:\s*(\d+)')

#: Binance uses a negative number under a different key. The two schemes do not
#: overlap, which matters: a wrapped exception carries one or the other and never
#: says which venue produced it.
_BINANCE_CODE = re.compile(r'"code"\s*:\s*(-\d+)')


@dataclass(frozen=True)
class Diagnosis:
    """What went wrong, and the next thing to try."""

    headline: str
    detail: str
    fixable_by_user: bool = True

    def render(self, *, indent: str = "  ") -> str:
        body = "\n".join(f"{indent}{line}" for line in self.detail.strip().splitlines())
        return f"{indent}{self.headline}\n{body}"


def _environment_note(testnet: bool) -> str:
    where = "testnet.bybit.com" if testnet else "bybit.com (MAINNET)"
    other = "bybit.com" if testnet else "testnet.bybit.com"
    return (
        f"This run is pointed at {where}, set by TB_BYBIT__TESTNET in .env.\n"
        f"Bybit keeps three separate environments and a key works in exactly one:\n"
        f"  testnet.bybit.com   play money, separate registration\n"
        f"  bybit.com > Demo    play money, created from the real site\n"
        f"  bybit.com           real money\n"
        f"A key made on {other} will be rejected here even though it is a valid key."
    )


def diagnose(error: Exception, *, testnet: bool = True) -> Diagnosis:
    """Read an exchange failure and say what to do about it."""
    text = str(error)
    binance = _BINANCE_CODE.search(text)
    if binance is not None:
        return _BINANCE_BY_CODE.get(binance.group(1)) or _unrecognised(text)

    match = _BYBIT_CODE.search(text)
    code = match.group(1) if match else ""

    if code == "10003":
        return Diagnosis(
            "Bybit does not recognise this API key.",
            "The key is well-formed but no account here has it. Almost always this\n"
            "means it was created somewhere other than where it is being used, or\n"
            "that creating it never actually completed.\n\n"
            + _environment_note(testnet),
        )

    known = _BY_CODE.get(code)
    if known is not None:
        return known

    lowered = text.lower()
    if any(word in lowered for word in ("timed out", "timeout", "connection", "resolve", "dns")):
        return Diagnosis(
            "Could not reach Bybit at all.",
            "Nothing was sent, so nothing was changed. This is a network or DNS\n"
            "problem between this machine and the exchange.",
            fixable_by_user=False,
        )

    return _unrecognised(text)


def _unrecognised(text: str) -> Diagnosis:
    """Quote the venue verbatim rather than inventing an explanation.

    An unknown code with a confident-sounding cause attached is worse than the
    raw message: the raw message is at least true.
    """
    return Diagnosis(
        "The exchange rejected the connection.",
        f"No specific cause recognised. It said:\n\n{text[:400]}",
        fixable_by_user=False,
    )




def _build_table() -> dict[str, Diagnosis]:
    """Every entry names a different thing for the reader to do.

    A flat table rather than a chain of branches, so the codes that share an
    answer are visibly grouped and adding one stays a single line.
    """
    signature = Diagnosis(
        "Bybit rejected the signature on the request.",
        "The key was found, so TB_BYBIT__API_KEY is right and\n"
        "TB_BYBIT__API_SECRET is not -- typically a copy that lost a character,\n"
        "or a secret belonging to a different key. The secret is shown only once\n"
        "at creation, so if it was not saved, create a new key.\n"
        "A badly wrong system clock produces this same rejection.",
    )
    permission = Diagnosis(
        "This key exists but is not allowed to do that.",
        "On Bybit the trading right is the *Trade* column when creating a key,\n"
        "and the master switch above it must be Read-Write rather than Read-Only.\n"
        "A key with only Read-Only ticked watches the account perfectly well and\n"
        "can never place an order.\n"
        "Withdrawal rights are not needed and should stay off.",
    )
    venue_fault = Diagnosis(
        "Bybit had a problem on its side.",
        "A server fault or a rate limit rather than anything about this setup.\n"
        "Waiting and trying again is the whole fix.",
        fixable_by_user=False,
    )
    return {
        "10002": signature,
        "10004": signature,
        "10005": permission,
        "33004": permission,
        "10006": venue_fault,
        "10016": venue_fault,
        "10010": Diagnosis(
            "Bybit refused the request from this IP address.",
            "The key was created with an IP allow-list that does not include this\n"
            "machine. Either add it there, or create a key with no IP restriction.",
        ),
        "10024": Diagnosis(
            "Bybit is refusing this account access to derivatives.",
            "A restriction on the account, not on the key and not on this program,\n"
            "so no setting here will change it. The usual causes are an unverified\n"
            "account or a jurisdiction where Bybit does not offer the product.\n"
            "Testnet is normally exempt, so seeing this is good evidence that the\n"
            "browser was on the real site rather than testnet.bybit.com.",
        ),
    }


_BY_CODE = _build_table()


def _build_binance_table() -> dict[str, Diagnosis]:
    """Binance's setup-time rejections, by the code it returns.

    Only the ones that come up while connecting an account for the first time.
    Guessing at the rest would produce confident wrong advice, and the fallback
    already quotes the venue verbatim, which is at least true.
    """
    return {
        "-2015": Diagnosis(
            "Binance will not accept this API key.",
            "One of three things, and the message does not distinguish them:\n"
            "  * the key belongs to the other environment -- the futures testnet\n"
            "    at testnet.binancefuture.com has its own accounts and its own\n"
            "    keys, and a mainnet key fails here exactly like a typo\n"
            "  * Futures permission is not enabled on the key\n"
            "  * an IP restriction is set and this machine is not on the list",
        ),
        "-2014": Diagnosis(
            "The API key is malformed.",
            "Binance rejected the key's shape rather than its permissions, so this\n"
            "is a copy that lost or gained a character. Paste it again, without\n"
            "surrounding quotes and without a trailing space.",
        ),
        "-1022": Diagnosis(
            "Binance rejected the signature on the request.",
            "The key was found, so the key is right and the secret is not --\n"
            "typically a copy that lost a character. Binance shows the secret only\n"
            "once at creation; if it was not saved, create a new key.",
        ),
        "-1021": Diagnosis(
            "This machine's clock is too far from Binance's.",
            "Every request is signed with a timestamp and refused outside a narrow\n"
            "window, so a clock off by seconds fails sporadically rather than\n"
            "consistently. Turn on automatic time synchronisation and retry.",
        ),
        "-1003": Diagnosis(
            "Too many requests.",
            "A rate limit rather than anything about this setup. Waiting is the\n"
            "whole fix.",
            fixable_by_user=False,
        ),
        "-1121": Diagnosis(
            "Binance does not know that symbol.",
            "On USD-M futures a USDT perpetual is spelled BTC/USDT. The form\n"
            "BTC/USDT:USDT is Bybit's. Seeing this after a venue change means\n"
            "something is still converting symbols the old way.",
        ),
    }


_BINANCE_BY_CODE = _build_binance_table()
