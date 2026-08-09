"""
Single source of truth for every tunable CONFIG parameter in the system.

Anti-bias rule #5 (LOCKED PARAMETERS): these defaults are set a priori. They
must NOT be optimized against the test set. If you tune, do it on a held-out
walk-forward slice and record the change here with a dated comment. Never tune
to make the archetype names (INTC/NOK/DELL/MU) light up (anti-bias rule #6).

Every value here is overridable via environment variable CATALYST_<UPPER_KEY>
or a config dict passed to Config.load(). Nothing in the engine hardcodes a
threshold inline -- it all routes through here.
"""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class ScreenConfig:
    """Module 1 -- distressed-and-viable wide screen."""
    market_cap_floor_usd: float = 300_000_000.0
    # Distressed = (drawdown from 52w high >= X) OR (within Y of 52w low).
    min_drawdown_from_52w_high: float = 0.40
    within_pct_of_52w_low: float = 0.25
    # When False, the distress condition is NOT required -- the screen passes any
    # viable+liquid+optionable name regardless of drawdown. NOTE: this removes the
    # core "buy the beaten-down setup" thesis (Section 1); the system becomes a
    # catalyst-on-anything scanner. Kept True by default to preserve the strategy.
    require_distress: bool = True
    # Liquidity: average daily dollar volume floor.
    min_avg_daily_dollar_volume_usd: float = 5_000_000.0
    adv_lookback_days: int = 20
    # Viability: improving margin / FCF trend across last N quarters.
    viability_lookback_quarters: int = 4
    # We FLAG high leverage rather than excluding it (levered turnarounds in scope).
    leverage_flag_debt_to_equity: float = 2.0
    require_listed_options: bool = True


@dataclass(frozen=True)
class CatalystConfig:
    """Module 2 -- catalyst detection (the gate)."""
    # Structured catalysts.
    min_earnings_surprise_pct: float = 5.0
    require_guidance_raise_with_surprise: bool = True
    analyst_revision_cluster_n: int = 3          # >= N upgrades/target raises ...
    analyst_revision_window_days: int = 14       # ... within T days.
    insider_net_buy_threshold_usd: float = 1_000_000.0
    insider_window_days: int = 30
    institutional_position_delta_pct: float = 1.0  # new large 13F-style position.

    # Validator catalysts (sparse; the real edge).
    federal_award_min_usd: float = 10_000_000.0
    strategic_stake_min_pct: float = 5.0         # 13D/13G filing threshold of record.
    news_keywords: tuple = (
        "stake", "investment", "award", "partnership", "strategic",
        "equity investment", "supply agreement",
    )
    # Validator catalysts require a human bull/bear judgement in the LIVE engine.
    validator_requires_review: bool = True


@dataclass(frozen=True)
class OptionsConfig:
    """Module 3 -- options wrapper engine + IV-rank store."""
    iv_rank_window_trading_days: int = 252
    iv_rank_min_history_days: int = 60           # below this -> unreliable.
    iv_rank_split_threshold: float = 50.0        # <= low/mid -> LEAPS; > high -> spread.

    leaps_target_delta_low: float = 0.60
    leaps_target_delta_high: float = 0.70
    leaps_min_days_past_catalyst: int = 30       # expiry must land past resolution.

    # Liquidity gates per leg.
    min_open_interest_per_leg: int = 250
    max_bid_ask_pct_of_premium: float = 0.15
    min_contract_volume: int = 25

    # Sizing.
    max_premium_at_risk_pct_of_book: float = 0.02


@dataclass(frozen=True)
class EntryExitConfig:
    """Module 4 -- entry / exit generator."""
    atr_period: int = 14
    base_lookback_days: int = 50                 # consolidation low / 50-day base.
    # Do-not-chase: reject if price > N ATR above catalyst trigger price.
    do_not_chase_atr_mult: float = 2.5
    atr_stop_mult: float = 2.0
    # Target ladder weights / sources are structural; trim sizes here.
    trim_plan: tuple = (0.33, 0.33, 0.34)        # fractions trimmed at T1/T2/T3.


@dataclass(frozen=True)
class BacktestConfig:
    """Module 6 -- point-in-time backtester."""
    entry_lag_bars: int = 1                       # ENTRY IS T+1 OPEN. Never the signal bar.
    forward_horizons_months: tuple = (3, 6, 12)
    # Regime split (anti-bias: report eras separately, never blended).
    regime_boundaries: tuple = ("2021-01-01", "2023-01-01")
    # Validation / kill conditions.
    min_trades_per_bucket: int = 20               # refuse to report below this N.
    bootstrap_iterations: int = 10_000
    bootstrap_ci: float = 0.95
    # Options overlay fill realism (stage two only).
    options_bid_ask_haircut: float = 0.50         # fraction of spread paid vs mid.
    illiquid_extra_haircut: float = 0.25


@dataclass(frozen=True)
class RuntimeConfig:
    """Provider clients / runtime."""
    cache_ttl_seconds: int = 6 * 3600
    max_retries: int = 5
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 30.0
    # SQLite is the offline/test default; production points at Supabase Postgres.
    database_url: str = "sqlite:///catalyst.db"
    polygon_base_url: str = "https://api.polygon.io"
    finnhub_base_url: str = "https://finnhub.io/api/v1"
    edgar_base_url: str = "https://efts.sec.gov/LATEST/search-index"
    edgar_submissions_url: str = "https://data.sec.gov"
    usaspending_base_url: str = "https://api.usaspending.gov/api/v2"
    sam_base_url: str = "https://api.sam.gov"
    # SEC requires a descriptive UA with contact.
    user_agent: str = "catalyst-breakout-research contact@example.com"


@dataclass(frozen=True)
class Config:
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    catalyst: CatalystConfig = field(default_factory=CatalystConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    entry_exit: EntryExitConfig = field(default_factory=EntryExitConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    # Archetype names are the PATTERN SOURCE, not a scorecard (anti-bias rule #6).
    # Present ONLY so tests can assert nothing branches on them. Never read in
    # signal logic.
    archetype_names: tuple = ("INTC", "NOK", "DELL", "MU")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULTS = Config()
