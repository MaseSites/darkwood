"""Which risk rule refused, and what it refused on.

For most of this project's life the answer was nowhere. `plan_entry` returned a
bare `None` for all five rules, the caller added one to a counter, and after a
thousand refusals there was a number and not one recoverable signal. That is
why the five rules are still untested hypotheses: `study_cost_floor.py` varied
the *threshold* of one of them across four markets, which is a different
question from whether the rule earns its place, and the second question can
only be asked from the signals the rule threw away.

Each test here drives one rule and asserts that it -- and not a neighbour --
gave the verdict. The rules run in a fixed order, so a signal that breaks two
is attributed to the first, and the counts stay a partition rather than
overlapping sets. `test_plan_entry_is_exactly_the_assessment` is the one that
keeps the old entry point from drifting away from the new one.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Rule, Side
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.sim.plan import Assessment, TradeIntent, assess, plan_entry

EQUITY = 1_000.0
EPOCH = 1_600_000_000_000
HOUR = 3_600_000


@pytest.fixture
def config() -> AppConfig:
    return load_config()


def intent(
    *,
    entry: float = 100.0,
    stop: float = 98.0,
    target: float | None = None,
    confidence: float = 60.0,
    side: Side = Side.LONG,
) -> TradeIntent:
    """A coherent long whose reward-to-risk clears the floor unless asked not to."""
    if target is None:
        risk = abs(entry - stop)
        target = entry + 2.0 * risk if side is Side.LONG else entry - 2.0 * risk
    return TradeIntent(
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        reason="A Momentum-Breakout (V08): zum Test",
    )


def verdict(
    what: TradeIntent, config: AppConfig, *, spec: SymbolSpec | None = None, equity: float = EQUITY
) -> Assessment:
    return assess(
        what,
        None,
        symbol="BTCUSDT",
        spec=spec or make_symbol_spec(),
        config=config,
        equity=equity,
        created_ts=EPOCH,
        expires_ts=EPOCH + 8 * HOUR,
    )


# --------------------------------------------------------------------------- #
# A signal that gets through
# --------------------------------------------------------------------------- #


def test_an_acceptable_signal_carries_its_cost_estimate(config: AppConfig) -> None:
    """The figure section 6 asks for under "geschätzte Kosten".

    Knowable before the entry, which is what makes it usable as a feature. The
    realised fee is not: a winner leaves at its target and pays maker, a loser
    leaves at its stop and pays taker, so "low cost" after the fact is only
    "ended well". That near-miss is recorded in `scripts/study_winners.py`.
    """
    result = verdict(intent(), config)
    assert result.accepted
    assert result.refused_by is None
    assert result.entry is not None
    assert 0.0 < result.cost_fraction <= config.risk.limits.max_cost_fraction_of_risk
    assert result.risk_amount > 0
    assert result.qty > 0
    assert result.leverage > 0
    assert result.reward_risk == pytest.approx(2.0)
    # The budget's own sentence, which nothing used to read.
    assert result.detail


def test_plan_entry_is_exactly_the_assessment(config: AppConfig) -> None:
    """The guarantee that the old entry point cannot drift from the new one.

    `plan_entry` is `assess(...).entry`. Two code paths computing one answer is
    the mistake this module's own docstring warns about, and the warning is
    only worth anything while something checks it.
    """
    for case in (
        intent(),
        intent(target=100.5),
        intent(confidence=10.0),
        intent(stop=70.0, target=145.0),
    ):
        kwargs = dict(
            symbol="BTCUSDT",
            spec=make_symbol_spec(),
            config=config,
            equity=EQUITY,
            created_ts=EPOCH,
            expires_ts=EPOCH + 8 * HOUR,
        )
        assert plan_entry(case, None, **kwargs) == assess(case, None, **kwargs).entry  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# One test per rule
# --------------------------------------------------------------------------- #


def test_a_reward_to_risk_below_the_floor(config: AppConfig) -> None:
    result = verdict(intent(target=100.5), config)
    assert result.refused_by is Rule.REWARD_RISK
    assert result.reward_risk == pytest.approx(0.25)
    assert "Chance-Risiko" in result.detail
    assert f"{config.risk.limits.min_reward_risk:.2f}" in result.detail


def test_a_confidence_below_the_floor(config: AppConfig) -> None:
    """Not a smaller position: a setup the system does not believe in is not a
    shrunken version of a good trade."""
    result = verdict(intent(confidence=10.0), config)
    assert result.refused_by is Rule.CONFIDENCE
    assert "Zuversicht" in result.detail
    assert result.risk_amount == 0.0


def test_a_position_too_small_for_the_venue(config: AppConfig) -> None:
    """The constraint a thousand-franc account really imposes.

    At 1% of 1,000 the risk is ten francs, and a wide stop turns that into a
    position the exchange will not place. `config/settings.yaml` says this is
    the point of using the real number rather than ten thousand.
    """
    result = verdict(
        intent(entry=100.0, stop=75.0, target=137.5),
        config,
        spec=make_symbol_spec(min_notional=50.0),
    )
    assert result.refused_by is Rule.SIZE
    assert "zu klein" in result.detail
    # The budget had already been computed, so it is reported.
    assert result.risk_amount > 0


def test_costs_too_large_a_share_of_the_risk(config: AppConfig) -> None:
    """The rule that was missing from the first backtests, and the fraction it
    decided on -- which used to be discarded on the line it was computed on."""
    result = verdict(intent(entry=100.0, stop=99.5, target=100.75), config)
    assert result.refused_by is Rule.COSTS
    assert result.cost_fraction > config.risk.limits.max_cost_fraction_of_risk
    assert "Kosten" in result.detail
    assert result.qty > 0, "the size was known before the costs refused it"


def test_a_stop_so_wide_that_liquidation_arrives_first(config: AppConfig) -> None:
    """The stop is where the plan says the trade is wrong; liquidation is where
    the exchange says it is over. The second must never come first."""
    result = verdict(intent(entry=100.0, stop=70.0, target=145.0), config)
    assert result.refused_by is Rule.LIQUIDATION
    assert "Liquidation" in result.detail
    assert result.cost_fraction > 0, "costs had passed before leverage refused"


# --------------------------------------------------------------------------- #
# The record these verdicts have to support
# --------------------------------------------------------------------------- #


def test_every_rule_is_reachable_and_each_signal_gets_exactly_one(config: AppConfig) -> None:
    """A partition, not overlapping sets.

    Without this the counts could not be added up: a signal failing both the
    cost rule and the leverage rule would appear under either depending on
    which branch was read, and the share each rule is responsible for -- the
    thing worth measuring -- would be unanswerable.
    """
    cases = {
        Rule.REWARD_RISK: (intent(target=100.5), None),
        Rule.CONFIDENCE: (intent(confidence=10.0), None),
        Rule.SIZE: (
            intent(entry=100.0, stop=75.0, target=137.5),
            make_symbol_spec(min_notional=50.0),
        ),
        Rule.COSTS: (intent(entry=100.0, stop=99.5, target=100.75), None),
        Rule.LIQUIDATION: (intent(entry=100.0, stop=70.0, target=145.0), None),
    }
    # `Rule.LIMITS` gehoert absichtlich NICHT hierher.
    #
    # Die fuenf oben sind Urteile ueber den TRADE und entstehen in
    # `sim/plan.py:assess`. `LIMITS` ist ein Urteil ueber das KONTO --
    # Tagesverlust, Wochenverlust, Abkuehlung, Zahl offener Positionen -- und
    # entsteht in `live/paper.py:_blocked_by_limits`. Dasselbe Signal waere
    # an einem anderen Tag durchgegangen, und `assess` kann es nicht
    # erzeugen.
    #
    # Getrieben wird es von `tests/test_paper_limits.py`. Die Teilung hier
    # ist also keine Ausnahme, sondern die Grenze: `assess` partitioniert
    # fuenf Gruende, und der sechste liegt ausserhalb.
    # `Rule.PICTURE` ebenso wenig (21.10.2026): das Gesamtbild entsteht erst
    # im Live-Pfad (`reason_at` vor `assess`), also kann `assess` diesen
    # Grund nicht erzeugen. Getrieben von `tests/test_regeln_21okt.py`.
    assert set(cases) == set(Rule) - {Rule.LIMITS, Rule.PICTURE}, (
        "ein assess-Grund existiert, den kein Test anfaehrt -- oder LIMITS ist "
        "in assess gewandert, was die Partition oben kaputt macht"
    )
    for rule, (case, spec) in cases.items():
        result = verdict(case, config, spec=spec)
        assert result.refused_by is rule, f"{rule} was not the verdict"
        assert result.entry is None
        assert result.detail, "a refusal with no sentence explains nothing"


def test_a_refusal_never_returns_an_order(config: AppConfig) -> None:
    """`accepted` and `refused_by` are two readings of one fact, so they cannot
    disagree -- which they could if a caller set them separately."""
    for case in (intent(target=100.5), intent(confidence=10.0)):
        result = verdict(case, config)
        assert not result.accepted
        assert result.refused_by is not None
    taken = verdict(intent(), config)
    assert taken.accepted and taken.refused_by is None


def test_the_order_is_unchanged_by_the_refactor(config: AppConfig) -> None:
    """The fields the journal and the broker read, still where they were."""
    result = verdict(intent(), config)
    entry = result.entry
    assert entry is not None
    assert entry.proposal_id == f"BTCUSDT-{EPOCH}"
    assert entry.setup == "A Momentum-Breakout (V08)"
    assert entry.limit_price == pytest.approx(100.0)
    assert entry.stop == pytest.approx(98.0)
    assert entry.target == pytest.approx(104.0)
    assert entry.qty == pytest.approx(result.qty)
    assert entry.leverage == pytest.approx(result.leverage)
    assert entry.risk_amount == pytest.approx(result.risk_amount)
    assert entry.snapshot_hash == "", "no snapshot was given, so none may be invented"


# --------------------------------------------------------------------------- #
# Die Schwelle darf nicht vom letzten Bit entschieden werden
# --------------------------------------------------------------------------- #


def _ziel_wie_setup_a(entry: float, stop: float, side: Side) -> float:
    """Genau die Zeile aus `strategy/setups.py:202`, nachgebaut.

    Nicht "ungefaehr so": die Reihenfolge der Rechenschritte IST der Fehler.
    `close + faktor * risk * sign` addiert einen winzigen Betrag auf einen
    grossen Preis, und was dabei an Bits wegfaellt, holt die spaetere
    Subtraktion nicht zurueck.
    """
    risk = abs(entry - stop)
    return entry + 1.5 * risk * side.sign


def test_ein_ziel_auf_der_schwelle_wird_nicht_abgelehnt(config: AppConfig) -> None:
    """Der gemeldete Fall, unveraendert.

    Am 19.10.2026 lehnte das Plankonto ein DOGEUSDT-Signal ab mit dem Text
    „Chance-Risiko 1.50 unter dem Minimum 1.50". Nachgerechnet lag das
    Verhaeltnis bei 1.4999999999999636 -- eine Luecke von 3,6e-14.

    Gemessen ueber alle 36.155 gespeicherten A-Signale lag **kein einziges**
    echt unter der Huerde; die 8.820 Ablehnungen waren vollstaendig Rauschen.
    """
    entry, stop = 0.07985, 0.07966
    ziel = _ziel_wie_setup_a(entry, stop, Side.LONG)
    absicht = intent(entry=entry, stop=stop, target=ziel)

    assert absicht.reward_risk < 1.5, (
        "Der Test prueft nichts, wenn das Verhaeltnis nicht wirklich knapp "
        "unter der Schwelle liegt -- dann ist die Rechnung exakt aufgegangen "
        "und der Fehler ist gar nicht nachgestellt."
    )
    assert absicht.reward_risk == pytest.approx(1.5, abs=1e-9)

    ergebnis = verdict(absicht, config)
    assert ergebnis.refused_by is not Rule.REWARD_RISK, (
        f"Chance-Risiko {absicht.reward_risk!r} wurde abgelehnt, obwohl es "
        f"{1.5 - absicht.reward_risk:.2e} von der Schwelle entfernt liegt"
    )


def test_ein_echt_zu_kleines_verhaeltnis_wird_weiter_abgelehnt(config: AppConfig) -> None:
    """Die Toleranz darf die Regel nicht aushebeln, nur ihr Rauschband raeumen.

    1,4 ist nicht 1,5, und der Abstand ist siebenstellig groesser als jedes
    Rundungsrauschen (gemessen groesste Abweichung: 2,78e-13).
    """
    entry, stop = 100.0, 98.0
    knapp_zu_wenig = entry + 1.4 * abs(entry - stop)

    ergebnis = verdict(intent(entry=entry, stop=stop, target=knapp_zu_wenig), config)

    assert ergebnis.refused_by is Rule.REWARD_RISK
    assert ergebnis.reward_risk == pytest.approx(1.4)


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_kein_ziel_aus_setup_as_bauweise_faellt_je_durch(
    config: AppConfig, side: Side
) -> None:
    """Die eigentliche Eigenschaft, ueber viele Preise statt an einem Fall.

    Setup A legt sein erstes Ziel auf genau 1,5 R -- dieselbe Zahl wie die
    Huerde. Ein so gebautes Ziel darf die Chance-Risiko-Regel NIE ausloesen,
    bei keinem Preis und keiner Stopweite. Vorher tat es das in 24,4 % der
    Faelle, und welche, entschied die letzte Stelle.

    Die Preise decken fuenf Groessenordnungen ab (DOGE bei 0,08 bis BTC bei
    70.000), weil genau dort der Fehler entsteht: je groesser der Preis im
    Verhaeltnis zur Stopweite, desto mehr Bits fallen beim Addieren weg.
    """
    preise = (0.07985, 0.2491, 1.1199, 12.318, 243.7, 3_412.55, 68_901.23)
    weiten = (0.0003, 0.0012, 0.005, 0.019, 0.047)

    durchgefallen = []
    geprueft = 0
    for entry in preise:
        for anteil in weiten:
            stop = entry - entry * anteil * side.sign
            ziel = _ziel_wie_setup_a(entry, stop, side)
            absicht = intent(entry=entry, stop=stop, target=ziel, side=side)
            if not absicht.is_coherent:
                continue
            geprueft += 1
            if verdict(absicht, config).refused_by is Rule.REWARD_RISK:
                durchgefallen.append((entry, stop, absicht.reward_risk))

    assert geprueft >= 30, f"nur {geprueft} Faelle geprueft -- der Fall zu eng"
    assert not durchgefallen, (
        f"{len(durchgefallen)} von {geprueft} Zielen aus Setup As Bauweise "
        f"wurden von der Chance-Risiko-Regel abgelehnt: {durchgefallen[:3]}"
    )
