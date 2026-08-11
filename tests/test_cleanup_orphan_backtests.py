"""The orphan-detection rule for cleanup_orphan_backtests."""
from __future__ import annotations

from scripts.cleanup_orphan_backtests import orphan_ids


def _bt(id_: str, name: str) -> dict:
    return {"id": id_, "strategy_name": name}


def test_keeps_active_and_builtin_drops_deleted() -> None:
    bts = [
        _bt("1", "SPY RSI Oversold Reversal"),  # active user strategy -> keep
        _bt("2", "SMACrossover"),               # built-in -> keep
        _bt("3", "BollingerMeanReversion"),     # deleted -> orphan
        _bt("4", "every2mins"),                 # deleted -> orphan
        _bt("5", "RsiMeanReversion2"),          # deleted -> orphan
    ]
    ids = orphan_ids(
        bts,
        active_names=["SPY RSI Oversold Reversal"],
        builtin_names=["SMACrossover"],
    )
    assert ids == ["3", "4", "5"]


def test_empty_when_all_live() -> None:
    bts = [_bt("1", "A"), _bt("2", "B")]
    assert orphan_ids(bts, active_names=["A", "B"], builtin_names=[]) == []


def test_whitespace_and_missing_name_tolerated() -> None:
    bts = [_bt("1", " A "), {"id": "2"}]  # padded name matches; missing name -> orphan
    assert orphan_ids(bts, active_names=["A"], builtin_names=[]) == ["2"]
