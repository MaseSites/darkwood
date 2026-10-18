"""Was eine `ExecutionPolicy` zusichern darf und was nicht.

**Der Anlass steht in `audit/P0A_LEGACY_FREEZE.md`.** Der Simulator nimmt
Maker am Einstieg (`sim/broker.py:493`, LIMIT => maker, ohne Kreuzungsprüfung)
und Maker am Target (`sim/broker.py:746`) an. Der Executor
(`execution/order.py:265`) erzwingt weder das eine noch das andere: er sendet
`timeInForce: GTC` ohne `PostOnly` und `takeProfit` ohne `tpOrderType`, und
Bybits Vorgabe für linear ist Market. Gemessene obere Schranke dieser
Abweichung über 7.335 Fills: **-0.021979 R je Trade**, korrigiert
[-0.022488, -0.021477] — das 1,7-fache der gesamten gemessenen Erwartung.

Der Vertrag, den diese Tests festnageln:

1. **Ein Limit ist kein Maker.** Ein GTC-Limit kann sofort ausführbar sein und
   dann Taker zahlen. Nur `PostOnly` verhindert das, indem die Börse den
   Auftrag storniert.
2. **Ein Limit-TP ist auch kein Maker.** Ein nach Trigger erzeugter Limit-TP
   ruhte vorher nicht im Buch.
3. **Die günstigere Annahme braucht einen Beweis**, nicht eine Absicht. Eine
   Policy erklärt, was gesendet wird; ein separates Flag sagt, ob die
   Liquidity Role bestätigt ist. Ohne Beweis rechnet das Kostenmodell Taker.
4. **Der Stop ist immer Market.** Ein Limit-Stop kann in einer Lücke
   unausgeführt bleiben, und das ist die eine Order, die ausführen muss.
"""

from __future__ import annotations

import pytest

from traidingbrain.execution.policy import (
    POLICIES,
    EntryLiquidity,
    ExecutionPolicy,
    ExitOrderType,
    policy_for,
)

# --------------------------------------------------------------------------- #
# Der Kern: eine Absicht ist kein Beweis
# --------------------------------------------------------------------------- #


def test_ein_gtc_limit_zahlt_taker_am_einstieg() -> None:
    """`taker_allowed` heisst Taker, auch wenn ein Limit gesendet wird.

    Das ist der heutige Executor: `timeInForce: GTC` ohne `PostOnly`.
    """
    p = POLICIES["bybit:safety-first"]
    assert p.entry_liquidity is EntryLiquidity.LIMIT_TAKER_ALLOWED
    assert p.entry_fee() == p.taker_fee


def test_post_only_allein_genuegt_noch_nicht() -> None:
    """PostOnly erlaubt die Maker-Annahme -- bewiesen ist sie damit nicht.

    Ein PostOnly-Auftrag wird storniert statt als Taker zu füllen, also KANN
    er nur maker werden. Ob er überhaupt füllt, ist eine andere Frage, und sie
    entscheidet, ob der Trade existiert -- nicht, was er kostet. Darum darf
    PostOnly die Maker-Gebühr tragen, sobald die Rolle bestätigt ist.
    """
    absicht = ExecutionPolicy(
        venue="bybit",
        name="probe",
        entry_liquidity=EntryLiquidity.POST_ONLY_MAKER,
        take_profit_order_type=ExitOrderType.MARKET,
        stop_order_type=ExitOrderType.MARKET,
        maker_fee=0.0002,
        taker_fee=0.00055,
        slippage_bps=3.0,
        fee_provenance="Test",
        maker_role_proven=False,
    )
    assert absicht.entry_fee() == absicht.taker_fee, "unbewiesen => Taker"

    bewiesen = absicht.with_proven_maker_role()
    assert bewiesen.entry_fee() == bewiesen.maker_fee


def test_ein_limit_target_ist_ohne_beweis_ein_taker_target() -> None:
    """Der teuerste Einzelposten des Legacy-Modells.

    `broker.py:746` setzt `maker_exit = reason is ExitReason.TARGET` --
    unbedingt. Gemessen kostet allein diese Annahme -0.005835 R je Trade
    (-0.015948 R je Target-Ausgang, n=2.684).
    """
    p = ExecutionPolicy(
        venue="bybit",
        name="probe",
        entry_liquidity=EntryLiquidity.POST_ONLY_MAKER,
        take_profit_order_type=ExitOrderType.RESTING_LIMIT,
        stop_order_type=ExitOrderType.MARKET,
        maker_fee=0.0002,
        taker_fee=0.00055,
        slippage_bps=3.0,
        fee_provenance="Test",
        maker_role_proven=False,
    )
    assert p.target_fee() == p.taker_fee
    assert p.with_proven_maker_role().target_fee() == p.maker_fee


def test_ein_market_target_bleibt_taker_auch_mit_beweis() -> None:
    """Kein Beweis macht aus einer Market-Order einen Maker-Fill."""
    p = POLICIES["bybit:safety-first"].with_proven_maker_role()
    assert p.take_profit_order_type is ExitOrderType.MARKET
    assert p.target_fee() == p.taker_fee


def test_der_stop_zahlt_immer_taker() -> None:
    for p in POLICIES.values():
        assert p.stop_order_type is ExitOrderType.MARKET
        assert p.stop_fee() == p.taker_fee
        assert p.with_proven_maker_role().stop_fee() == p.taker_fee


# --------------------------------------------------------------------------- #
# Was eine Policy nicht sein darf
# --------------------------------------------------------------------------- #


def test_ein_limit_stop_wird_abgelehnt() -> None:
    """Der Stop ist die eine Order, die ausführen MUSS."""
    with pytest.raises(ValueError, match="Stop"):
        ExecutionPolicy(
            venue="bybit",
            name="kaputt",
            entry_liquidity=EntryLiquidity.LIMIT_TAKER_ALLOWED,
            take_profit_order_type=ExitOrderType.MARKET,
            stop_order_type=ExitOrderType.RESTING_LIMIT,
            maker_fee=0.0002,
            taker_fee=0.00055,
            slippage_bps=3.0,
            fee_provenance="Test",
        )


@pytest.mark.parametrize(
    ("maker", "taker"),
    [(0.0002, 0.0001), (0.00055, 0.00055)],
)
def test_maker_muss_billiger_sein_als_taker(maker: float, taker: float) -> None:
    """Eine Gebührentabelle, in der Maker nicht billiger ist, ist ein Tippfehler.

    Nicht weil es physikalisch unmöglich wäre -- Maker-Rabatte können negativ
    sein --, sondern weil maker >= taker jede Maker-Annahme wertlos macht und
    damit mit grosser Wahrscheinlichkeit zwei vertauschte Zahlen ist. Genau
    diese Verwechslung hat das Projekt schon beim Venue-Etikett getroffen.
    """
    with pytest.raises(ValueError, match="billiger"):
        ExecutionPolicy(
            venue="bybit",
            name="kaputt",
            entry_liquidity=EntryLiquidity.LIMIT_TAKER_ALLOWED,
            take_profit_order_type=ExitOrderType.MARKET,
            stop_order_type=ExitOrderType.MARKET,
            maker_fee=maker,
            taker_fee=taker,
            slippage_bps=3.0,
            fee_provenance="Test",
        )


def test_eine_policy_ohne_herkunft_der_gebuehren_wird_abgelehnt() -> None:
    """Eine Zahl ohne Quelle ist in diesem Projekt keine Zahl."""
    with pytest.raises(ValueError, match="Herkunft"):
        ExecutionPolicy(
            venue="bybit",
            name="kaputt",
            entry_liquidity=EntryLiquidity.LIMIT_TAKER_ALLOWED,
            take_profit_order_type=ExitOrderType.MARKET,
            stop_order_type=ExitOrderType.MARKET,
            maker_fee=0.0002,
            taker_fee=0.00055,
            slippage_bps=3.0,
            fee_provenance="  ",
        )


# --------------------------------------------------------------------------- #
# Die Auswahl
# --------------------------------------------------------------------------- #


def test_jede_policy_nennt_ihre_venue_und_ist_unter_ihr_auffindbar() -> None:
    for key, p in POLICIES.items():
        venue, _, name = key.partition(":")
        assert p.venue == venue
        assert p.name == name
        assert policy_for(venue, name) is p


@pytest.mark.parametrize(
    ("venue", "name"),
    [
        ("binance", "gibt-es-nicht"),   # Venue bekannt, Policy nicht
        ("kraken", "safety-first"),     # Policy-Name bekannt, Venue nicht
        ("bybit", ""),                  # leerer Name
        ("", "safety-first"),           # leere Venue
    ],
)
def test_eine_unbekannte_policy_bricht_ab_statt_zu_raten(
    venue: str, name: str
) -> None:
    """Kein Rückfall auf eine Vorgabe.

    Der Vorgabewert `venue_name: str = "bybit"` in `execution/order.py:91` ist
    genau der Grund, warum diese Funktion keinen hat: zwei Aufrufstellen
    übergaben nichts und bekamen stillschweigend Bybit, während die
    Konfiguration Binance sagte.
    """
    with pytest.raises(KeyError):
        policy_for(venue, name)


def test_safety_first_existiert_fuer_jede_unterstuetzte_venue() -> None:
    """Die konservative Baseline muss überall verfügbar sein.

    Policy A (alles Taker) ist die einzige, die heute belegbar ist. Fehlte sie
    für eine Venue, wäre der einzige Weg dorthin eine unbewiesene Annahme.
    """
    venues = {p.venue for p in POLICIES.values()}
    for v in venues:
        assert policy_for(v, "safety-first").all_taker()


def test_safety_first_rechnet_alles_als_taker() -> None:
    for v in {p.venue for p in POLICIES.values()}:
        p = policy_for(v, "safety-first")
        assert p.entry_fee() == p.taker_fee
        assert p.target_fee() == p.taker_fee
        assert p.stop_fee() == p.taker_fee
        assert p.all_taker()


def test_maker_target_ist_nicht_all_taker_aber_unbewiesen() -> None:
    """Policy B deklariert die Absicht und bleibt bis zum Beweis teuer."""
    p = policy_for("bybit", "maker-target")
    assert p.entry_liquidity is EntryLiquidity.POST_ONLY_MAKER
    assert p.take_profit_order_type is ExitOrderType.RESTING_LIMIT
    assert not p.maker_role_proven
    assert p.all_taker(), "unbewiesen rechnet wie Policy A"
    assert not p.with_proven_maker_role().all_taker()


# --------------------------------------------------------------------------- #
# Der Kostenboden, den eine Policy impliziert
# --------------------------------------------------------------------------- #


def test_der_kostenboden_folgt_aus_der_policy_nicht_aus_einer_konstante() -> None:
    """`d_min = c / f`, und `c` kommt aus der Policy.

    Legacy rechnete 1.3125 % aus maker+taker+3bps bei einem Deckel von 8 %.
    Unter Policy A sind es taker+taker+Slippage, also 1.75 % -- und das würde
    2.529 von 7.335 Legacy-Fills (34.5 %) nicht zulassen.
    """
    p = policy_for("bybit", "safety-first")
    # Limit-Einstieg rutscht nicht, Market-Stop rutscht.
    c = p.round_trip_cost_fraction()
    assert c == pytest.approx(0.00055 + 0.00055 + 0.0003)
    assert p.min_economic_stop_fraction(0.08) == pytest.approx(0.0175, abs=1e-9)

    # Und Policy B MIT Beweis ist genau das Legacy-Kostenmodell.
    legacy = policy_for("bybit", "maker-target").with_proven_maker_role()
    assert legacy.round_trip_cost_fraction() == pytest.approx(
        0.0002 + 0.00055 + 0.0003
    )
    assert legacy.min_economic_stop_fraction(0.08) == pytest.approx(
        0.013125, abs=1e-9
    )
    assert c > legacy.round_trip_cost_fraction(), "Policy A ist teurer"


def test_ein_deckel_von_null_gibt_keinen_unendlichen_boden() -> None:
    p = policy_for("bybit", "safety-first")
    with pytest.raises(ValueError, match="Deckel"):
        p.min_economic_stop_fraction(0.0)
