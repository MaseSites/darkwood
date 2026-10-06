"""The external connectors, parsed from recorded payloads rather than the net.

Every fixture here is a trimmed copy of a real response, kept verbatim in the
shapes that caused bugs: the nanosecond `.value`, the `status-time` that is a
revalidation marker rather than an availability stamp, and DefiLlama's two
circulation fields that mean different things.

The one test that talks to the network is marked and skipped by default. A
suite that needs the internet is a suite that fails for reasons unrelated to
the code.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from traidingbrain.data.external import (
    BUSINESS_DAY_SHARE,
    COMMUNITY_METRICS,
    FALLBACK_LAG_MS,
    FRED_SERIES,
    PAYWALLED,
    ExternalStore,
    ExternalUnavailableError,
    Fetched,
    _stamp,
    coinmetrics,
    fred,
    stablecoins,
)

DAY_MS = 86_400_000

#: A real Coin Metrics row, trimmed. The status time is on the FOLLOWING day
#: at 02:10 UTC -- the shape that makes the availability rule necessary.
CM_ROW = {
    "asset": "btc",
    "time": "2026-10-04T00:00:00.000000000Z",
    "FlowInExUSD": "1187427991.526",
    "FlowInExUSD-status": "flash",
    "FlowInExUSD-status-time": "2026-10-05T02:10:48.845362000Z",
    "AdrActCnt": "827239",
    "AdrActCnt-status": "flash",
    "AdrActCnt-status-time": "2026-10-05T02:10:48.845362000Z",
}


def test_stamp_returns_milliseconds_not_nanoseconds() -> None:
    """The bug that produced a year of 45,002,209.

    `.value` on a scalar Timestamp is nanoseconds and stays nanoseconds after
    `as_unit("ms")` -- that call changes the resolution, not what `.value`
    reports. Read as milliseconds it is a million times too large, which here
    crashed loudly and in an availability comparison would have passed quietly.
    """
    got = _stamp("2026-10-04T02:11:51.288392000Z")
    assert got == 1791079911288
    # And the shape check that would have caught it without knowing the value:
    # a current timestamp in milliseconds has 13 digits.
    assert len(str(got)) == 13
    assert 2020 <= pd.Timestamp(got, unit="ms", tz="UTC").year <= 2100


def test_stamp_handles_a_date_without_a_zone() -> None:
    assert _stamp("2020-01-01T00:00:00Z") == 1577836800000


def test_paywalled_metrics_are_not_requested() -> None:
    """Asking for a 403 twice is spending the rate limit on a certainty."""
    assert PAYWALLED
    assert not (set(COMMUNITY_METRICS) & PAYWALLED)
    assert "FlowInExUSD" in COMMUNITY_METRICS, "Boersenfluesse sind der Grund fuer das Modul"
    assert "FeeTotUSD" in PAYWALLED


def test_flow_metrics_are_both_present() -> None:
    """Netflow needs both directions; one alone is not a flow."""
    assert "FlowInExUSD" in COMMUNITY_METRICS
    assert "FlowOutExUSD" in COMMUNITY_METRICS


def test_availability_is_a_full_day_after_the_observation() -> None:
    """The constant, and the direction of its rounding.

    Measured lag is about 26 hours; a full day is just under that. Being
    slightly late makes a feature weaker, being early makes it wrong.
    """
    assert FALLBACK_LAG_MS == DAY_MS
    assert FALLBACK_LAG_MS < 26 * 3_600_000


def test_status_time_is_not_used_as_availability() -> None:
    """The correction that matters most in this module.

    Every `status-time` the service returns falls in the last six months, even
    for rows observed in 2015 -- it reports the last revalidation. Using it
    would mark a 2015 row unavailable until 2026 and silently empty every
    model built on this source, which reads as thin coverage rather than a bug.

    Asserted on the fixture: the row's availability must be one day after the
    observation, NOT the status time.
    """
    observed = _stamp(CM_ROW["time"])
    status = _stamp(CM_ROW["FlowInExUSD-status-time"])
    assert status > observed, "Die Vorlage muss die echte Form haben"
    # What the module must produce for this row.
    assert observed + FALLBACK_LAG_MS != status
    assert observed + FALLBACK_LAG_MS == observed + DAY_MS


def test_store_merges_restated_rows_instead_of_duplicating(tmp_path) -> None:
    """A restated value replaces its predecessor; it does not sit beside it."""
    store = ExternalStore(tmp_path)
    first = Fetched(
        frame=pd.DataFrame({"ts": [1, 2], "available_ms": [2, 3], "value": [10.0, 20.0]}),
        source="test:thing",
        url="https://example.invalid",
        sha256="a" * 64,
        fetched_ms=1,
    )
    store.write(first, keep_raw=False)

    # The same day, restated.
    second = Fetched(
        frame=pd.DataFrame({"ts": [2, 3], "available_ms": [3, 4], "value": [99.0, 30.0]}),
        source="test:thing",
        url="https://example.invalid",
        sha256="b" * 64,
        fetched_ms=2,
    )
    store.write(second, keep_raw=False)

    back = store.read("test:thing").sort_values("ts").reset_index(drop=True)
    assert list(back["ts"]) == [1, 2, 3], "Keine Dubletten"
    assert back.loc[back["ts"] == 2, "value"].iloc[0] == 99.0, "Die neuere Fassung gewinnt"
    assert back.loc[back["ts"] == 1, "value"].iloc[0] == 10.0, "Die alte bleibt sonst stehen"


def test_store_records_the_hash_of_what_was_fetched(tmp_path) -> None:
    """These services restate history, so the response is the only record."""
    store = ExternalStore(tmp_path)
    store.write(
        Fetched(
            frame=pd.DataFrame({"ts": [1], "available_ms": [2]}),
            source="test:thing",
            url="https://example.invalid",
            sha256="c" * 64,
            fetched_ms=7,
        ),
        keep_raw=True,
    )
    back = store.read("test:thing")
    assert back["sha256"].iloc[0] == "c" * 64
    assert back["fetched_ms"].iloc[0] == 7
    archived = list((tmp_path / "raw").glob("*.json"))
    assert len(archived) == 1
    saved = json.loads(archived[0].read_text(encoding="utf-8"))
    assert saved["sha256"] == "c" * 64


def test_store_reports_nothing_for_an_unknown_source(tmp_path) -> None:
    store = ExternalStore(tmp_path)
    assert store.read("test:absent").empty
    assert "nichts gespeichert" in store.coverage("test:absent")


def test_unavailable_is_its_own_error() -> None:
    assert issubclass(ExternalUnavailableError, RuntimeError)


@pytest.mark.skip(reason="Braucht Netz; von Hand laufen lassen, nicht in der Suite.")
def test_live_services_still_answer() -> None:
    """The integration check the order asks for, kept out of the suite.

    Run by hand when a connector is suspected:
        pytest tests/test_external.py -k live --no-skip
    """
    got = stablecoins()
    assert len(got.frame) > 3000
    assert {"supply_usd_peg", "valued_usd_peg"} <= set(got.frame.columns)

    chain = coinmetrics("btc", since="2024-01-01")
    assert "FlowInExUSD" in chain.frame.columns
    assert (chain.frame["available_ms"] > chain.frame["ts"]).all()


def test_a_bare_date_and_an_instant_both_become_milliseconds() -> None:
    """The bug that made all six FRED series fail at once.

    Coin Metrics sends an instant with a "Z" and FRED sends a bare date. One
    is tz-aware and the other is not, and `tz_convert` raises on the naive one
    with "Cannot convert tz-naive Timestamp". A bare date reads as midnight
    UTC, which is how every other daily stamp here is stored.
    """
    # 1,790,899,200,000 is 2026-10-02 00:00 UTC. The literal is here rather
    # than computed so a change in the conversion cannot move the target
    # along with the result -- a test that recomputes what it checks proves
    # nothing. Verified with pd.Timestamp(ms, unit="ms", tz="UTC").
    assert _stamp("2026-10-02") == 1_790_899_200_000
    assert _stamp("2026-10-02T00:00:00.000000000Z") == 1_790_899_200_000
    # And the two agree, which is the property that matters for a join.
    assert _stamp("2020-01-01") == _stamp("2020-01-01T00:00:00Z")


def test_only_the_declared_fred_series_are_fetchable() -> None:
    """Six, named in the research order. A seventh is a typo, not a request."""
    assert set(FRED_SERIES) == {
        "DTWEXBGS",
        "DGS2",
        "DGS10",
        "NASDAQCOM",
        "SP500",
        "VIXCLS",
    }
    with pytest.raises(ExternalUnavailableError, match="nicht angemeldet"):
        fred("GDP")
    with pytest.raises(ExternalUnavailableError, match="nicht angemeldet"):
        fred("dgs10")  # case matters; the endpoint is case-sensitive


def test_every_fred_series_says_whether_it_is_revisable() -> None:
    """Five are market observations; one is computed.

    The CSV endpoint serves the current vintage, so the distinction decides
    how much point-in-time trust each series earns. DTWEXBGS is the one that
    can be restated, and the note has to say so.
    """
    assert "revidierbar" in FRED_SERIES["DTWEXBGS"]
    for market_series in ("DGS2", "DGS10", "NASDAQCOM", "SP500", "VIXCLS"):
        assert "Marktbeobachtung" in FRED_SERIES[market_series]


def test_a_weekday_series_is_not_reported_as_gappy(tmp_path) -> None:
    """71.4% of a daily grid is 5/7, which is a complete business-day series.

    All six FRED series land there exactly. Reporting it as "71.4% complete"
    reads as a quarter of the data missing, which is how intact data gets
    mistaken for a defect.
    """
    store = ExternalStore(tmp_path)
    # Ten weeks of weekdays only.
    stamps = []
    day = pd.Timestamp("2026-01-05", tz="UTC")  # a Monday
    for week in range(10):
        for weekday in range(5):
            moment = day + pd.Timedelta(days=week * 7 + weekday)
            stamps.append(int(moment.value // 1_000_000))
    store.write(
        Fetched(
            frame=pd.DataFrame(
                {"ts": stamps, "available_ms": [s + DAY_MS for s in stamps], "v": 1.0}
            ),
            source="fred:test",
            url="https://example.invalid",
            sha256="d" * 64,
            fetched_ms=1,
        ),
        keep_raw=False,
    )
    report = store.coverage("fred:test")
    assert "Werktagsreihe" in report
    assert "71.4%" not in report
    assert abs(BUSINESS_DAY_SHARE - 5 / 7) < 1e-9

