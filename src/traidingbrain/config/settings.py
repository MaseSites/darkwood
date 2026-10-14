"""Configuration: YAML for behaviour, environment for secrets.

The split is deliberate. `config/*.yaml` is committed and describes how the engine
thinks. Credentials arrive through `.env` and never touch a file that git tracks.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from traidingbrain.domain.enums import Factor, Timeframe

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# settings.yaml
# --------------------------------------------------------------------------- #


class ExchangeConfig(_Frozen):
    name: Literal["bybit", "binance"] = "bybit"
    market_type: Literal["linear"] = "linear"
    testnet: bool = True
    rate_limit_ms: int = Field(default=120, ge=0)


class SymbolsConfig(_Frozen):
    active: list[str]
    available: list[str]

    @model_validator(mode="after")
    def _active_is_subset(self) -> SymbolsConfig:
        unknown = set(self.active) - set(self.available)
        if unknown:
            raise ValueError(f"active symbols not in available: {sorted(unknown)}")
        return self


class TimeframesConfig(_Frozen):
    context: list[Timeframe]
    signal: Timeframe
    execution: Timeframe

    @model_validator(mode="after")
    def _signal_is_context(self) -> TimeframesConfig:
        if self.signal not in self.context:
            raise ValueError(f"signal timeframe {self.signal} must appear in context frames")
        if self.execution in self.context:
            raise ValueError(
                f"execution timeframe {self.execution} must not be analysed; it exists only "
                "to resolve intrabar ordering in the simulator"
            )
        return self

    @property
    def all_needed(self) -> list[Timeframe]:
        return [*self.context, self.execution]


class MacdConfig(_Frozen):
    fast: int = Field(gt=0)
    slow: int = Field(gt=0)
    signal: int = Field(gt=0)


class BollingerConfig(_Frozen):
    period: int = Field(gt=0)
    std: float = Field(gt=0)


class IndicatorsConfig(_Frozen):
    atr_period: int = Field(default=14, gt=0)
    rsi_period: int = Field(default=14, gt=0)
    ema_fast: int = Field(default=21, gt=0)
    ema_slow: int = Field(default=55, gt=0)
    macd: MacdConfig
    bb: BollingerConfig
    volume_ma: int = Field(default=20, gt=0)


class StructureConfig(_Frozen):
    swing_lookback: int = Field(default=3, ge=1)
    max_sequence_length: int = Field(default=6, ge=1)


class LiquidityConfig(_Frozen):
    equal_level_tolerance_atr: float = Field(gt=0)
    sweep_lookback_bars: int = Field(gt=0)
    fvg_min_size_atr: float = Field(gt=0)


class RegimeConfig(_Frozen):
    volatility_window: int = Field(gt=0)
    trend_window: int = Field(gt=0)


class HistoryConfig(_Frozen):
    k_neighbours: int = Field(gt=0)
    outcome_horizon_hours: int = Field(gt=0)
    embargo_hours: int = Field(ge=0)
    min_samples_for_stats: int = Field(ge=0)

    @model_validator(mode="after")
    def _embargo_covers_horizon(self) -> HistoryConfig:
        if self.embargo_hours < self.outcome_horizon_hours:
            raise ValueError(
                f"embargo_hours ({self.embargo_hours}) must be at least outcome_horizon_hours "
                f"({self.outcome_horizon_hours}); a neighbour whose outcome window overlaps the "
                "present bar encodes that bar"
            )
        return self

    @model_validator(mode="after")
    def _the_threshold_is_reachable(self) -> HistoryConfig:
        """A lookup can return at most `k_neighbours`, so asking for more is asking
        for something that cannot happen.

        This shipped: k was 25 and the threshold 30, so `sample_is_sufficient` was
        false on every one of seventy-one thousand lookups. Nothing failed, no
        error was raised, and the symptom -- the history factor contributing
        nothing and the confidence cap never lifting -- looked exactly like a
        genuine shortage of data. Two numbers in a YAML file cannot be relied on
        to stay consistent, so the relationship between them is checked here.

        Deduplication only removes neighbours, so k must exceed the threshold with
        room to spare rather than merely equal it.
        """
        if self.k_neighbours < self.min_samples_for_stats:
            raise ValueError(
                f"k_neighbours ({self.k_neighbours}) is below min_samples_for_stats "
                f"({self.min_samples_for_stats}), so a lookup can never return enough "
                "neighbours to quote a rate and the history factor is permanently "
                "silent. Raise k_neighbours well above the threshold -- deduplication "
                "removes cases from the same episode, so equality is not enough."
            )
        return self


class BrainConfig(_Frozen):
    model: str = "claude-opus-5-5"
    iteration_model: str = "claude-sonnet-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = Field(default=8000, gt=0)
    prompt_version: str = "v1"
    use_batch_api_for_backtest: bool = True
    max_usd_per_backtest: float = Field(default=25.0, gt=0)


class TriggerConfig(_Frozen):
    require_bos_or_choch: bool = True
    require_sweep: bool = False
    min_indicator_confluence: int = Field(default=2, ge=0)
    min_bars_between_calls: int = Field(default=4, ge=0)

    #: Minutes either side of a high-impact scheduled event during which no
    #: setup is taken. Zero disables it.
    #:
    #: The window is symmetric because both halves are the same problem: before
    #: a release the book thins as market makers step back, and after it the
    #: first move is frequently reversed. A stop placed on structure means
    #: nothing to either.
    news_blackout_minutes: int = Field(default=0, ge=0)

    #: Sessions during which setups may be taken. Empty means all of them, which
    #: is the honest default for a market that never closes -- a restriction
    #: nobody measured is a restriction that only narrows the sample.
    allowed_sessions: list[str] = Field(default_factory=list)

    #: Refuse setups when no desk is staffed. Thin books move further on the same
    #: order, so a break at 03:00 UTC is not the same evidence as one at 14:00.
    require_active_session: bool = False


class SimulationConfig(_Frozen):
    initial_equity: float = Field(gt=0)
    slippage_bps: float = Field(ge=0)
    fill_on_touch: bool = False
    entry_expiry_bars: int = Field(gt=0)
    pessimistic_intrabar: bool = True
    breakeven_at_r: float | None = Field(default=None, gt=0)
    """Move the stop to the entry once the trade is this far in profit.

    Off by default, because it is a change to what gets traded rather than a
    detail of how it is simulated. It lives here rather than in a strategy so
    that the gaps, the slippage, the liquidation check and the pessimistic
    intrabar ordering all still apply -- a rule tested beside the simulator
    instead of inside it is a second answer to the same question, and the first
    attempt at this missed liquidations, gaps and V08's runner at once."""

    target_cap_r: float | None = Field(default=None, gt=0)
    """Pull the take profit in to at most this many multiples of the risk.

    Off by default, same reasoning as `breakeven_at_r`: it changes what gets
    traded, so turning it on is a challenger arm, not a correction.

    **Why it lives here and not in the proposal.** `min_reward_risk` is 1.5 and
    `sim/plan.py` refuses anything below it. A cap applied where the proposal is
    built would therefore have refused *every* trade at a cap of 1.0 R -- zero
    trades, and the obvious "fix" would have been to weaken a protection rule
    in order to get a result. Capping here keeps the entry population fixed and
    varies only the exit, which is also the cleaner measurement: the other
    design would have mixed two effects, fewer trades taken and earlier exits.

    Registered as E15 on 14.10.2026. The reason it is worth measuring is a
    description nobody had summed: over 2,734 replay trades the planned target
    sits at a median +1.905 R while the median best position reached is
    +1.073 R, so **67.8 % of trades never touch their target, not even
    briefly**. E3 varied the exit RULE three ways and never varied the
    target's DISTANCE.

    That 67.8 % is a corrected figure and the correction is instructive. The
    first pass read 65.4 % because it compared two numbers built on different
    risk denominators: `max_favourable_r` comes from `examine()`, which is
    handed `entry=fill.entry_price` and `stop=reason.stop`, while
    `reward_risk` is plan over plan. They agree for 85.7 % of trades -- a
    limit order usually fills at its limit -- and for the rest they do not, so
    65 trades sat on the wrong side of the comparison."""

    max_hold_hours: float | None = Field(default=None, gt=0)
    """Close a position that has been held this long, on that ground alone.

    Off by default, and that default is the point: the broker has never had a
    time exit, so turning it on is a challenger arm to be measured against the
    champion, not a correction to slip in.

    Two reasons it is worth measuring. First, `learn/labels.py` already applies
    a time barrier and it binds in 2.9% of cases, so the label and the broker
    disagree today -- every R multiple from a labelled study assumes an exit
    the simulator will not make. Second, the broker holds exactly one position
    and has no time exit at all, so a single trade can occupy the only slot for
    days; measured on the ledger, about two thirds of BTC's four years lies
    behind a taken signal where the strategy is never even asked.

    In hours rather than bars, because `SimulationConfig` carries no timeframe
    and converting inside the broker would mean guessing one."""


class PathsConfig(_Frozen):
    data_dir: Path
    parquet_dir: Path
    funding_dir: Path
    db_path: Path
    cache_db_path: Path
    runs_dir: Path

    def resolved(self, root: Path = PROJECT_ROOT) -> PathsConfig:
        return PathsConfig(
            data_dir=root / self.data_dir,
            parquet_dir=root / self.parquet_dir,
            funding_dir=root / self.funding_dir,
            db_path=root / self.db_path,
            cache_db_path=root / self.cache_db_path,
            runs_dir=root / self.runs_dir,
        )


class SetupsConfig(_Frozen):
    """Which of the guide's setups may trade.

    A setting rather than an edit to the tuple in `setups.py`, because
    switching one off is a decision about Severin's rules and belongs
    somewhere he can see it and change it back. The screen reads this list, and
    so does the pool.

    Leaving a setup out does not delete it: it keeps its tests, its rule card
    and its place in the comparison table. It simply does not get traded.
    """

    enabled: list[str]
    disabled_note: str = ""
    """Why something is off, in one line, next to the fact that it is."""


class EngineConfig(_Frozen):
    exchange: ExchangeConfig
    symbols: SymbolsConfig
    setups: SetupsConfig
    timeframes: TimeframesConfig
    indicators: IndicatorsConfig
    structure: StructureConfig
    liquidity: LiquidityConfig
    regime: RegimeConfig
    history: HistoryConfig
    brain: BrainConfig
    trigger: TriggerConfig
    simulation: SimulationConfig
    paths: PathsConfig


# --------------------------------------------------------------------------- #
# weights.yaml
# --------------------------------------------------------------------------- #


class ConfidenceConfig(_Frozen):
    floor: int = 0
    ceiling: int = 100
    scale_by_factor_confidence: bool = True
    cap_without_history: int = Field(default=75, ge=0, le=100)


class WeightsConfig(_Frozen):
    weights: dict[Factor, float]
    active: dict[Factor, bool]
    confidence: ConfidenceConfig

    @model_validator(mode="after")
    def _every_factor_declared(self) -> WeightsConfig:
        missing_w = set(Factor) - set(self.weights)
        missing_a = set(Factor) - set(self.active)
        if missing_w or missing_a:
            raise ValueError(
                f"weights.yaml must declare every factor; missing weights={sorted(missing_w)} "
                f"active={sorted(missing_a)}"
            )
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if not any(self.active.values()):
            raise ValueError("at least one factor must be active")
        return self

    def effective_weights(self) -> dict[Factor, float]:
        """Weights over the active factors only, renormalised to sum to 1.

        Dropping an inactive factor and renormalising is honest; leaving it in at
        weight zero quietly shrinks every score toward the middle.
        """
        live = {f: w for f, w in self.weights.items() if self.active.get(f, False)}
        total = sum(live.values())
        if total <= 0:
            raise ValueError("active factors carry zero total weight")
        return {f: w / total for f, w in live.items()}


# --------------------------------------------------------------------------- #
# risk.yaml
# --------------------------------------------------------------------------- #


class RiskTier(_Frozen):
    min_confidence: float = Field(ge=0, le=100)
    risk_pct: float = Field(gt=0, le=0.05)


class SizingConfig(_Frozen):
    #: Wessen Kapital die Positionsgroesse bemisst.
    #:
    #: `account` -- jedes Symbol bemisst sich an seinem eigenen Konto. Das war
    #: bis zum 13.10.2026 das einzige Verhalten, und es ist ein Messgeruest:
    #: `live/paper.py` erklaert, dass die Backtests jedes Symbol gegen
    #: dasselbe Startkapital groessen, damit ein Vorwaertslauf vergleichbar
    #: bleibt.
    #:
    #: `portfolio` -- die Groesse bemisst sich am Kapital ALLER Konten
    #: zusammen, so wie ein echtes Boersenkonto, das mehrere Maerkte haelt.
    #:
    #: **Warum das ueberhaupt ein Schalter ist.** Unter `account` riskiert
    #: ein Trade 1 % von einem Zwoelftel des Kapitals, also 0,083 % des
    #: Ganzen. Das ist nicht als Risikoentscheidung gewaehlt worden, es
    #: faellt aus der Kontostruktur. Gemessen am 13.10.2026: 10,06 USDT je
    #: Trade statt 120,76, und die 26 bereinigten Vorwaertstrades haetten
    #: +906,73 statt +75,56 USDT ergeben.
    #:
    #: Der Schalter steht in der Konfiguration und nicht im Code, weil
    #: `run_signature` ihn traegt: Trades vor und nach der Umstellung sind
    #: sonst unter einem Schluessel vermischt, und genau das hat die
    #: Vorwaertsstichprobe schon einmal von 18 auf 11 Trades schrumpfen
    #: lassen.
    basis: str = Field(default="account", pattern="^(account|portfolio)$")

    min_confidence: float = Field(ge=0, le=100)
    tiers: list[RiskTier]
    uncalibrated_cap_risk_pct: float = Field(gt=0, le=0.05)
    min_samples_for_uncap: int = Field(ge=0)
    absolute_max_risk_pct: float = Field(gt=0, le=0.05)

    #: Has the claim that higher confidence earns more risk actually been shown?
    #:
    #: Default false, because absence of a measurement is not a passing grade.
    #: While this is false the cap holds no matter how many cases exist, and
    #: `min_samples_for_uncap` is a necessary-but-not-sufficient second
    #: condition rather than the whole gate.
    #:
    #: It is a separate switch because the sample count was doing a job it
    #: cannot do. It was compared against the neighbours of *one bar*, and
    #: "this bar has 200 lookalikes" is a fact about locality, not evidence
    #: that a confidence number means anything. Answering the real question
    #: needs the confidence recorded alongside each resolved case, which
    #: `history.Case` does not carry yet.
    calibration_proven: bool = False

    @model_validator(mode="after")
    def _tiers_ascend(self) -> SizingConfig:
        if not self.tiers:
            raise ValueError("at least one risk tier is required")
        confs = [t.min_confidence for t in self.tiers]
        risks = [t.risk_pct for t in self.tiers]
        if confs != sorted(confs) or risks != sorted(risks):
            raise ValueError("risk tiers must ascend in both confidence and risk_pct")
        if max(risks) > self.absolute_max_risk_pct:
            raise ValueError(f"a tier exceeds absolute_max_risk_pct ({self.absolute_max_risk_pct})")
        return self


class LeverageConfig(_Frozen):
    min_liquidation_buffer_r: float = Field(gt=0)
    max: float = Field(gt=0)
    allow_user_increase: bool = False


class LimitsConfig(_Frozen):
    max_open_positions: int = Field(ge=1)
    max_positions_per_symbol: int = Field(ge=1)
    max_daily_loss_pct: float = Field(gt=0)
    max_weekly_loss_pct: float = Field(gt=0)
    cooldown_after_consecutive_losses: int = Field(ge=1)
    cooldown_hours: int = Field(ge=0)
    min_reward_risk: float = Field(gt=0)
    max_cost_fraction_of_risk: float = Field(gt=0, le=1.0)


class ExecutionConfig(_Frozen):
    max_price_drift_bps: float = Field(gt=0)
    confirmation_token_ttl_seconds: int = Field(gt=0)
    proposal_ttl_seconds: int = Field(gt=0)
    stop_watchdog_deadline_seconds: float = Field(gt=0)


class RiskConfig(_Frozen):
    sizing: SizingConfig
    leverage: LeverageConfig
    limits: LimitsConfig
    execution: ExecutionConfig


# --------------------------------------------------------------------------- #
# .env
# --------------------------------------------------------------------------- #


class BybitCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = SecretStr("")
    api_secret: SecretStr = SecretStr("")
    testnet: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key.get_secret_value() and self.api_secret.get_secret_value())


class Secrets(BaseSettings):
    """Credentials and machine-local paths. Never logged, never serialised."""

    model_config = SettingsConfigDict(
        env_prefix="TB_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Both of these are read under their own canonical names *and* under the TB_
    # prefix, because the prefix is a trap here. `.env.example` has always listed
    # `ANTHROPIC_API_KEY`, which is the name Anthropic's own tooling uses and the
    # name anyone would write -- and with only the prefix configured it was read
    # from `TB_ANTHROPIC_API_KEY` and the plain spelling was silently ignored.
    # A credential that is present, correct and unread is the worst of the three.
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "TB_ANTHROPIC_API_KEY"),
    )
    #: A long-lived token from `claude setup-token`, for the subscription brain.
    #:
    #: Here rather than in a Windows environment variable for the same reason as
    #: every other credential: one file to fill in, one file to keep out of git.
    #: The CLI only reads it from the environment, so the brain puts it there for
    #: the subprocess and nowhere else.
    claude_code_oauth_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("CLAUDE_CODE_OAUTH_TOKEN", "TB_CLAUDE_CODE_OAUTH_TOKEN"),
    )
    bybit: BybitCredentials = BybitCredentials()
    #: Where Postgres lives, as a libpq URL. Empty means "not configured", which
    #: is a supported state: the SQLite stores work standalone and are what a
    #: single machine needs. Postgres earns its place when the collector, the
    #: engine and the dashboard stop being the same process.
    postgres_url: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TB_POSTGRES_URL", "POSTGRES_URL", "DATABASE_URL"),
    )
    #: A *separate* database for the test suite, and the reason it has to exist.
    #:
    #: The Postgres proposal tests truncate `proposals` before each case. That
    #: was harmless while no database was reachable and every run skipped. It
    #: stopped being harmless the moment one was: `postgres_url` is what the
    #: live loop writes real proposals into, and a test run against it is a
    #: delete.
    #:
    #: Empty means the Postgres cases skip, exactly as they did before. Pointing
    #: it at the same database as `postgres_url` is refused rather than allowed
    #: -- see `tests/conftest.py`.
    postgres_test_url: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TB_POSTGRES_TEST_URL", "POSTGRES_TEST_URL"),
    )
    kill_switch_file: Path = Path("data/KILL_SWITCH")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


class AppConfig(_Frozen):
    """Everything the engine needs, validated once at startup."""

    engine: EngineConfig
    weights: WeightsConfig
    risk: RiskConfig

    @model_validator(mode="after")
    def _the_uncap_threshold_is_reachable(self) -> AppConfig:
        """The same trap as `HistoryConfig._the_threshold_is_reachable`, one file over.

        That validator catches an unreachable threshold *within* settings.yaml.
        This one shipped anyway, because the two numbers live in different files
        and therefore in different models, which neither could see across:
        `risk.yaml` asked for 200 cases, and the quantity it was compared
        against -- `snapshot.history.similar_situations_found` -- is the
        neighbour count of a single bar, capped at `k_neighbours` of 120 and cut
        further by the distance filter and deduplication. So `<=120 < 200` was
        true at every decision, and the 1% cap that has held every trade held by
        arithmetic accident rather than by decision.

        A safety property that holds for the wrong reason is not a safety
        property: it would have gone on holding, silently, if the evidence had
        one day justified lifting it. So the check binds exactly when it starts
        to matter -- the moment somebody marks calibration proven.
        """
        sizing = self.risk.sizing
        if not sizing.calibration_proven:
            return self
        k = self.engine.history.k_neighbours
        if sizing.min_samples_for_uncap >= k:
            raise ValueError(
                f"min_samples_for_uncap ({sizing.min_samples_for_uncap}) is not below "
                f"k_neighbours ({k}), and the sample count handed to risk_budget is one "
                "bar's usable neighbours -- at most k, and fewer after the distance "
                "filter and deduplication. The gate could never open, so the risk cap "
                "would hold by accident while appearing to be calibrated. Either raise "
                "k_neighbours well above the threshold, or count cases over the whole "
                "evidence base instead of one bar's neighbourhood."
            )
        return self


@functools.lru_cache(maxsize=1)
def load_config(config_dir: Path | None = None) -> AppConfig:
    """Read and validate every config file.

    Cached, because config is read in a lot of places and re-parsing it would be
    both wasteful and a source of drift if a file changed mid-run.
    """
    directory = config_dir or CONFIG_DIR
    engine = EngineConfig.model_validate(_read_yaml(directory / "settings.yaml"))
    engine = engine.model_copy(update={"paths": engine.paths.resolved()})
    return AppConfig(
        engine=engine,
        weights=WeightsConfig.model_validate(_read_yaml(directory / "weights.yaml")),
        risk=RiskConfig.model_validate(_read_yaml(directory / "risk.yaml")),
    )


@functools.lru_cache(maxsize=1)
def load_secrets() -> Secrets:
    return Secrets()
