"""VALIDATION GATE -- the report refuses to publish stats below the minimum N.

Section 11 kill condition: minimum trade count >= 20 per catalyst bucket before
any bucket's stats are considered meaningful. The report must SUPPRESS, not
publish, an under-N bucket -- and it must segment by catalyst type AND regime.
"""

from dataclasses import replace

from catalyst.backtest.engine import Trade
from catalyst.backtest import report
from config.defaults import DEFAULTS


def _trade(ct, signal_date, ret=0.1, filled=True, tier="structured"):
    return Trade(
        ticker="SYN", signal_date=signal_date, entry_date=signal_date,
        entry_price=10.0, filled=filled, no_fill_reason="" if filled else "do_not_chase",
        catalyst_type=ct, tier=tier, requires_review=False,
        fixed_horizon={3: ret, 6: ret, 12: ret},
        rules_return=ret, rules_exit_reason="target_3", holding_days=30,
    )


def test_under_n_bucket_is_suppressed():
    # Only 5 filled trades in this catalyst bucket -> below default min N of 20.
    trades = [_trade("federal_award", "2024-01-15", ret=0.4) for _ in range(5)]
    rep = report.generate(trades, DEFAULTS)
    bucket = rep["by_catalyst"]["federal_award"]
    assert bucket.reported is False
    assert "min_trades_per_bucket" in bucket.suppressed_reason
    assert bucket.rules_stats is None


def test_at_or_above_n_bucket_is_reported():
    cfg = replace(DEFAULTS, backtest=replace(DEFAULTS.backtest, min_trades_per_bucket=20))
    trades = [_trade("earnings_surprise_guidance_raise", "2024-02-01", ret=0.15)
              for _ in range(25)]
    rep = report.generate(trades, cfg)
    bucket = rep["by_catalyst"]["earnings_surprise_guidance_raise"]
    assert bucket.reported is True
    assert bucket.rules_stats is not None
    assert bucket.rules_stats.n == 25


def test_report_segments_by_regime():
    cfg = replace(DEFAULTS, backtest=replace(DEFAULTS.backtest, min_trades_per_bucket=1))
    trades = (
        [_trade("earnings_surprise_guidance_raise", "2019-06-01") for _ in range(3)]   # pre-2021
        + [_trade("earnings_surprise_guidance_raise", "2024-06-01") for _ in range(3)]  # AI-era
    )
    rep = report.generate(trades, cfg)
    # Two distinct regimes must appear, never blended into one stat.
    assert len(rep["by_regime"]) >= 2
    labels = list(rep["by_regime"].keys())
    assert any("2021" in l for l in labels)


def test_no_fill_rate_is_tracked():
    cfg = replace(DEFAULTS, backtest=replace(DEFAULTS.backtest, min_trades_per_bucket=1))
    trades = ([_trade("material_8k", "2024-01-01", filled=True) for _ in range(3)]
              + [_trade("material_8k", "2024-01-01", filled=False) for _ in range(1)])
    rep = report.generate(trades, cfg)
    bucket = rep["by_catalyst"]["material_8k"]
    assert bucket.n_signals == 4
    assert bucket.n_filled == 3
    assert abs(bucket.no_fill_rate - 0.25) < 1e-9
