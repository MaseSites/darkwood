"""The ratchet, and the four ways it would quietly stop being one.

`learn/register.py` is what makes "it only gets better" an arithmetic statement
instead of a hope. It can only do that if four things hold, and none of them is
visible from reading a passing report:

1. **A test-fold result can never crown a champion.** Those folds have been
   read across every arm ever tried here, so a number from them is a candidate.
2. **A higher mean is not enough.** All eight hypotheses rejected on 05.10.2026
   looked like a higher mean at first.
3. **The threshold tightens as the holdout is consulted.** A holdout read
   twenty times and then picked from is a validation fold with extra steps.
4. **Re-running the same arm is not a second attempt.** Otherwise the attempt
   count -- the thing the correction rests on -- would grow every time somebody
   pressed enter, and the correction would strangle real findings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from traidingbrain.learn.register import (
    FAMILY_CONFIDENCE,
    MIN_HOLDOUT_TRADES,
    Register,
    Result,
    Stage,
    Verdict,
)

NOW = 1_791_200_000_000


@pytest.fixture
def register(tmp_path: Path) -> Register:
    return Register(tmp_path / "experiments.sqlite")


def result(
    arm: str,
    *,
    stage: Stage = Stage.HOLDOUT,
    mean: float = 0.10,
    low: float = 0.05,
    high: float = 0.15,
    n: int = 200,
) -> Result:
    return Result(arm=arm, stage=stage, n=n, mean_r=mean, low=low, high=high)


def crown_baseline(register: Register, *, mean: float = 0.0) -> None:
    register.crown(
        result("champion", mean=mean, low=mean - 0.05, high=mean + 0.05),
        run_signature="sig",
        now_ms=NOW,
        note="die heutige Konfiguration, eingefroren",
    )


# --------------------------------------------------------------------------- #
# The four properties
# --------------------------------------------------------------------------- #


def test_a_test_fold_result_can_never_crown_a_champion(register: Register) -> None:
    """Even a spectacular one.

    The walk-forward test folds have been read across every arm tried in this
    project. A number from them is where an idea comes from, not where it is
    confirmed.
    """
    crown_baseline(register)
    judgement = register.judge(
        result("wunderarm", stage=Stage.TEST, mean=5.0, low=4.0, high=6.0)
    )

    assert judgement.verdict is Verdict.RECORDED
    assert not judgement.replaces
    assert "kein Urteil" in judgement.reason


def test_a_higher_mean_alone_does_not_replace_the_champion(register: Register) -> None:
    """How all eight rejected hypotheses looked at first."""
    crown_baseline(register)
    judgement = register.judge(result("knapp_besser", mean=0.02, low=-0.04, high=0.08))

    assert judgement.margin > 0, "the arm really is higher on the point estimate"
    assert judgement.verdict is Verdict.INSIDE_NOISE
    assert not judgement.replaces
    assert "enthaelt den Champion" in judgement.reason


def test_the_required_confidence_tightens_with_every_consultation(register: Register) -> None:
    """The holdout is consumable, and this is the arithmetic of spending it."""
    crown_baseline(register)
    first = register.judge(result("arm1")).required_confidence

    for i in range(9):
        register.record(result(f"arm{i}"), run_signature="sig", now_ms=NOW + i)

    later = register.judge(result("arm_spaet")).required_confidence

    assert later > first, "the bar did not rise as the holdout was spent"
    assert first == pytest.approx(FAMILY_CONFIDENCE)
    # Ten consultations: the error budget is split ten ways.
    assert later == pytest.approx(1.0 - (1.0 - FAMILY_CONFIDENCE) / 10)


def test_rerunning_one_arm_is_not_a_second_attempt(register: Register) -> None:
    """Otherwise the correction would punish pressing enter twice."""
    crown_baseline(register)
    for _ in range(5):
        register.record(result("derselbe_arm"), run_signature="sig", now_ms=NOW)

    assert register.consultations() == 1
    assert len(register.all(stage=Stage.HOLDOUT)) == 1


# --------------------------------------------------------------------------- #
# What may replace, and what is kept
# --------------------------------------------------------------------------- #


def test_a_clear_winner_on_the_holdout_may_replace(register: Register) -> None:
    crown_baseline(register, mean=0.0)
    judgement = register.judge(result("echt_besser", mean=0.20, low=0.12, high=0.28))

    assert judgement.verdict is Verdict.BEATS_CHAMPION
    assert judgement.replaces
    assert "schliesst den Champion" in judgement.reason


def test_too_few_trades_is_a_refusal_not_a_verdict(register: Register) -> None:
    crown_baseline(register)
    judgement = register.judge(
        result("duenn", mean=0.5, low=0.3, high=0.7, n=MIN_HOLDOUT_TRADES - 1)
    )

    assert judgement.verdict is Verdict.INSIDE_NOISE
    assert not judgement.replaces
    assert str(MIN_HOLDOUT_TRADES) in judgement.reason


def test_a_worse_arm_is_named_worse_rather_than_noisy(register: Register) -> None:
    """The three refusals mean different things and a report should say which."""
    crown_baseline(register, mean=0.10)
    judgement = register.judge(result("schlechter", mean=0.02, low=-0.01, high=0.05))

    assert judgement.verdict is Verdict.WORSE
    assert judgement.margin < 0


def test_the_failures_are_kept_and_that_is_the_point(register: Register) -> None:
    """A register of winners reports a selected sample as the whole."""
    crown_baseline(register)
    for name in ("gebuehr", "weiter_stop", "zieldeckel", "lernfilter"):
        register.record(
            result(name, mean=-0.05, low=-0.12, high=0.02), run_signature="sig", now_ms=NOW
        )

    rows = register.all(stage=Stage.HOLDOUT)
    assert len(rows) == 4, "a failed attempt was dropped"
    assert {row[0] for row in rows} == {"gebuehr", "weiter_stop", "zieldeckel", "lernfilter"}


def test_every_row_carries_the_code_that_produced_it(register: Register) -> None:
    """Champion-versus-challenger compares two versions of the code."""
    crown_baseline(register)
    register.record(result("ein_arm"), run_signature="sig", now_ms=NOW)

    [row] = register.all(stage=Stage.HOLDOUT)
    assert row[8], "no code version was recorded"


def test_exploration_is_free_and_worth_nothing(register: Register) -> None:
    """Train and validation may be consulted endlessly; they cannot decide."""
    crown_baseline(register)
    for i in range(50):
        register.record(
            result(f"idee{i}", stage=Stage.EXPLORE), run_signature="sig", now_ms=NOW + i
        )

    assert register.consultations() == 0, "exploration spent the holdout"
    assert register.judge(result("x")).required_confidence == pytest.approx(FAMILY_CONFIDENCE)


def test_the_first_champion_can_be_crowned_against_nothing(register: Register) -> None:
    """There has to be a way to start, and it is explicit rather than implied."""
    assert register.champion() is None

    champion = register.crown(
        result("heutige_konfiguration", mean=-0.0340),
        run_signature="sig",
        now_ms=NOW,
        note="4 Maerkte, 3300 Trades",
    )

    assert register.champion() == champion
    assert "heutige_konfiguration" in champion.describe()
    assert "-0.0340" in champion.describe()


def test_crowning_replaces_rather_than_accumulating(register: Register) -> None:
    """One champion, or the word means nothing."""
    crown_baseline(register, mean=0.0)
    register.crown(result("neuer", mean=0.20), run_signature="sig", now_ms=NOW + 1)

    champion = register.champion()
    assert champion is not None
    assert champion.arm == "neuer"
    assert champion.mean_r == pytest.approx(0.20)


def test_the_judgement_states_the_level_before_the_measurement(register: Register) -> None:
    """So the confidence cannot be chosen after seeing the result.

    `required_confidence` is readable without passing an interval, which is
    what lets a caller compute its bounds at the right level the first time
    rather than discovering which level would have passed.
    """
    crown_baseline(register)
    for i in range(3):
        register.record(result(f"arm{i}"), run_signature="sig", now_ms=NOW + i)

    judgement = register.judge(result("naechster", mean=0.0, low=0.0, high=0.0))

    # Four, not three: judging this arm is itself a consultation. Leaving it
    # out would let the last attempt in a family escape the correction the
    # others paid, and the last attempt is the one somebody is hoping about.
    assert judgement.attempts == 4
    assert judgement.required_confidence == pytest.approx(1.0 - (1.0 - FAMILY_CONFIDENCE) / 4)
    assert judgement.required_confidence > FAMILY_CONFIDENCE


def test_rejudging_a_recorded_arm_does_not_raise_its_own_bar(register: Register) -> None:
    """Measuring the same arm again must not make it harder to pass."""
    crown_baseline(register)
    register.record(result("arm_a"), run_signature="sig", now_ms=NOW)

    assert register.judge(result("arm_a")).attempts == 1
    assert register.judge(result("arm_b")).attempts == 2, "a new arm must count itself"


def test_a_foreign_unit_counts_as_an_attempt_but_never_as_a_verdict(
    register: Register,
) -> None:
    """The forward-score arms were measured as a rank correlation, not in R.

    Writing +0.004 into a column of R multiples would be a number nobody could
    read back correctly, and a rank correlation cannot be compared against a
    champion's expectancy at all. So it is filed -- the attempt is real and
    must be countable -- and it can never crown anything.
    """
    crown_baseline(register)
    judgement = register.judge(
        Result(
            arm="vorhersage_5h",
            stage=Stage.HOLDOUT,
            n=34394,
            mean_r=0.0039,
            low=0.0,
            high=0.0,
            unit="Rangkorrelation",
        )
    )

    assert judgement.verdict is Verdict.RECORDED
    assert not judgement.replaces
    assert "nicht in R" in judgement.reason


def test_the_unit_is_stored_so_a_row_cannot_be_misread(register: Register) -> None:
    crown_baseline(register)
    register.record(
        Result(
            arm="vorhersage_10h",
            stage=Stage.TEST,
            n=34395,
            mean_r=0.0045,
            low=0.0,
            high=0.0,
            unit="Rangkorrelation",
        ),
        run_signature="sig",
        now_ms=NOW,
    )

    [row] = register.all(stage=Stage.TEST)
    assert row[6] == "Rangkorrelation"
