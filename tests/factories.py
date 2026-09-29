"""Builders for domain objects in tests.

Defaults describe a plain bullish H1 setup. Every test overrides only the field it
is actually about, so a test's body reads as the thing it checks rather than as
twenty lines of scaffolding.
"""

from __future__ import annotations

from traidingbrain.domain import (
    Bias,
    Decision,
    Factor,
    HistoryStats,
    IndicatorReading,
    Level,
    LevelKind,
    LiquidityView,
    MarketSnapshot,
    RegimeKind,
    RiskLevel,
    Side,
    StructureView,
    SymbolSpec,
    Timeframe,
    TimeframeView,
    VolBucket,
)
from traidingbrain.domain.verdict import (
    Anchor,
    BrainVerdict,
    FactorScore,
    Scenarios,
    ScenarioSpec,
)

BASE_PRICE = 42_000.0
BASE_ATR = 420.0
BASE_TS = 1_700_000_000_000


def make_symbol_spec(**overrides: object) -> SymbolSpec:
    defaults: dict[str, object] = {
        "symbol": "BTCUSDT",
        "price_tick": 0.1,
        "qty_step": 0.001,
        "min_qty": 0.001,
        "min_notional": 5.0,
        "max_leverage": 100.0,
        "taker_fee": 0.00055,
        "maker_fee": 0.0002,
        "maintenance_margin_rate": 0.005,
    }
    return SymbolSpec.model_validate(defaults | overrides)


def make_timeframe_view(timeframe: Timeframe = Timeframe.H1, **overrides: object) -> TimeframeView:
    defaults: dict[str, object] = {
        "timeframe": timeframe,
        "regime": RegimeKind.TREND_UP,
        "volatility": VolBucket.NORMAL,
        "trend": Bias.BULLISH,
        "structure": StructureView(
            sequence="HL HH HL", bos=True, choch=False, bars_since_bos=4, bars_since_choch=None
        ),
        "liquidity": LiquidityView(
            sweep_up=False, sweep_down=True, bars_since_sweep=2, zone_level_ids=["lvl_2"]
        ),
        "indicators": [
            IndicatorReading(name="RSI", value=72.0, bias=Bias.BEARISH, strength=0.8),
            IndicatorReading(name="EMA21/55", value=1.02, bias=Bias.BULLISH, strength=0.6),
        ],
    }
    return TimeframeView.model_validate(defaults | overrides)


def make_levels(price: float = BASE_PRICE, atr: float = BASE_ATR) -> list[Level]:
    """A small, realistic ladder around the current price."""
    spec = [
        ("lvl_0", LevelKind.CURRENT, Timeframe.H1, price, 0),
        ("lvl_1", LevelKind.SWING_HIGH, Timeframe.H1, price + 2.4 * atr, 12),
        ("lvl_2", LevelKind.SWING_LOW, Timeframe.H1, price - 1.2 * atr, 6),
        ("lvl_3", LevelKind.FVG_MID, Timeframe.H1, price - 0.5 * atr, 3),
        ("lvl_4", LevelKind.PREV_DAY_LOW, Timeframe.D1, price - 2.8 * atr, 30),
        ("lvl_5", LevelKind.PREV_WEEK_HIGH, Timeframe.W1, price + 5.0 * atr, 90),
    ]
    return [
        Level(
            id=lid,
            kind=kind,
            timeframe=tf,
            price=lvl_price,
            distance_atr=(lvl_price - price) / atr,
            age_bars=age,
            touches=1,
        )
        for lid, kind, tf, lvl_price, age in spec
    ]


def make_snapshot(**overrides: object) -> MarketSnapshot:
    defaults: dict[str, object] = {
        "symbol": "BTCUSDT",
        "ts": BASE_TS,
        "signal_timeframe": Timeframe.H1,
        "price": BASE_PRICE,
        "atr": BASE_ATR,
        "frames": [
            make_timeframe_view(Timeframe.W1),
            make_timeframe_view(Timeframe.D1),
            make_timeframe_view(Timeframe.H4),
            make_timeframe_view(Timeframe.H1),
            make_timeframe_view(Timeframe.M15),
        ],
        "levels": make_levels(),
        "news": [],
        "history": HistoryStats(
            similar_situations_found=12,
            historical_winrate=0.63,
            mean_r_multiple=0.41,
            regime=RegimeKind.TREND_UP,
            sample_is_sufficient=False,
        ),
    }
    return MarketSnapshot.model_validate(defaults | overrides)


def make_scenario(side: Side = Side.LONG, **overrides: object) -> ScenarioSpec:
    if side is Side.LONG:
        defaults: dict[str, object] = {
            "side": Side.LONG,
            "entry": Anchor(level_id="lvl_3", offset_atr=0.0),
            "stop": Anchor(level_id="lvl_2", offset_atr=-0.3),
            "target": Anchor(level_id="lvl_1", offset_atr=0.0),
            "rationale": "Continuation into the imbalance after sell-side liquidity was taken.",
        }
    else:
        defaults = {
            "side": Side.SHORT,
            "entry": Anchor(level_id="lvl_1", offset_atr=0.0),
            "stop": Anchor(level_id="lvl_5", offset_atr=0.0),
            "target": Anchor(level_id="lvl_4", offset_atr=0.0),
            "rationale": "Rejection at the prior swing high with momentum divergence.",
        }
    return ScenarioSpec.model_validate(defaults | overrides)


def make_verdict(**overrides: object) -> BrainVerdict:
    defaults: dict[str, object] = {
        "schema_version": 1,
        "bias": Bias.BULLISH,
        "decision": Decision.VALID_TRADE,
        "risk": RiskLevel.MEDIUM,
        "factor_scores": [
            FactorScore(
                factor=Factor.STRUCTURE,
                score=0.7,
                confidence=0.8,
                reasoning="Higher highs and higher lows intact, break of structure confirmed.",
            ),
            FactorScore(
                factor=Factor.INDICATORS,
                score=0.1,
                confidence=0.5,
                reasoning="RSI stretched but trend strength argues against fading it.",
            ),
            FactorScore(
                factor=Factor.LIQUIDITY,
                score=0.6,
                confidence=0.7,
                reasoning="Sell-side liquidity swept and reclaimed within two bars.",
            ),
            FactorScore(
                factor=Factor.HISTORY,
                score=0.3,
                confidence=0.4,
                reasoning="Comparable setups skew positive, but the sample is thin.",
            ),
        ],
        "scenarios": Scenarios(
            bullish=make_scenario(Side.LONG),
            bearish=make_scenario(Side.SHORT),
            invalidation=Anchor(level_id="lvl_2", offset_atr=-0.8),
            invalidation_note="Acceptance below the swing low ends the bullish read.",
        ),
        "reasoning": [
            "Structure remains bullish across H4 and H1.",
            "Liquidity was taken below support and reclaimed.",
            "History is mildly supportive but the sample is too small to lean on.",
        ],
        "market_commentary": "Controlled continuation with liquidity-driven pullbacks.",
    }
    return BrainVerdict.model_validate(defaults | overrides)
