"""referee/ — the validation gauntlet.

Library + CLI that takes the backtest corpus and returns honest verdicts:
Deflated Sharpe (Bailey & Lopez de Prado 2014), Probability of Backtest
Overfitting via CSCV (Bailey, Borwein, Lopez de Prado, Zhu 2017), Minimum
Track Record Length, purge+embargo cross-validation, and a synthetic noise
battery that the gauntlet must REJECT.

Every number is net of one realistic cost model (30bps round-trip = fee 10bps +
slip 5bps, matching the event-driven BacktestConfig default). n_trials fed into
DSR is the full corpus/program size — selection bias is not allowed back in
through a side door.

No execution. No broker wiring. Library, CLI, verdict, report. That is all.
"""
__all__ = ["stats", "corpus", "purge", "noise", "verdict", "report",
           "intake", "certify", "cert_report", "cli"]
