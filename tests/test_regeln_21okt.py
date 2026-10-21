"""Die zwei Regeln vom 21.10.2026: Ebenenliste und Bild-Tor.

Eingefroren wird hier, dass (1) die Vorgabe beides AUS laesst und die
Signatur dann byte-gleich bleibt, (2) die Ebenenliste in `SEARCH_ORDER`
sortiert wird, egal wie sie in der Datei steht, (3) beide Regeln in der
Signatur stehen, sobald sie gesetzt sind, und (4) der Ablehnungsgrund einen
eigenen Namen hat.
"""

from __future__ import annotations

from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Rule, Timeframe
from traidingbrain.journal.version import run_signature
from traidingbrain.strategies.guide import SEARCH_ORDER, GuidePool, allowed_timeframes


def _mit(config: AppConfig, **setups) -> AppConfig:
    engine = config.engine
    neu = engine.setups.model_copy(update=setups)
    return config.model_copy(update={"engine": engine.model_copy(update={"setups": neu})})


def test_defaults_leave_everything_as_before() -> None:
    config = load_config()
    assert config.engine.setups.timeframes is None
    assert config.engine.setups.require_agreement is False
    assert allowed_timeframes(config) == SEARCH_ORDER
    assert "|tf=" not in run_signature(config)
    assert "|bild" not in run_signature(config)


def test_timeframes_are_ordered_like_the_search_order() -> None:
    config = _mit(load_config(), timeframes=[Timeframe.H1, Timeframe.D1, Timeframe.H4])
    assert allowed_timeframes(config) == (Timeframe.D1, Timeframe.H4, Timeframe.H1)
    assert GuidePool.for_config(config).timeframes == (Timeframe.D1, Timeframe.H4, Timeframe.H1)


def test_both_rules_appear_in_the_signature_before_the_run_markers() -> None:
    config = _mit(
        load_config(), timeframes=[Timeframe.D1, Timeframe.H4, Timeframe.H1], require_agreement=True
    )
    sig = run_signature(config, max_bars=10)
    assert "|tf=D1,H4,H1|bild|10bars" in sig


def test_the_picture_rule_has_its_own_name() -> None:
    assert Rule.PICTURE.value == "bild"
    assert Rule.PICTURE is not Rule.LIMITS
