"""The certify payload builder wires the exposure column through to the engine.

The engine intake is already exposure-aware; the gap was that the submitted
evidence didn't carry `positions_value`, so the path never engaged. These tests
prove the builder (services.api.certify_payload) now includes it with the right
name and aligned length, that a normal low-frequency strategy reaches a real
verdict END-TO-END through builder -> intake -> certify (not the engine in
isolation), and that the no-exposure fallback still produces the bare payload.

Engine (referee/) is untouched; this exercises only the client payload path.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np

from referee import certify, intake
from services.api.certify_payload import (
    EXPOSURE_COLUMN,
    build_certify_csv,
    build_certify_request,
)


def _platform_equity_rows(seed=0, with_exposure=True):
    """Synthesize a platform backtest equity curve in the shape the equity
    endpoint / load_backtest_equity returns: ts, cash, positions_value,
    total_equity. Low-frequency: 4 idle runs of 50 flat no-position bars
    interleaved with 30-bar active blocks -> 120 active bars (>= MIN_OBS)."""
    rng = np.random.default_rng(seed)
    rets, pos = [], []
    for _ in range(4):
        rets += [0.0] * 50;                       pos += [0.0] * 50
        rets += list(rng.normal(0.0, 0.01, 30));  pos += [1000.0] * 30

    base = dt.datetime(2023, 1, 2, tzinfo=dt.timezone.utc)
    eq = 10000.0
    rows = [{
        "ts": base.isoformat(),
        "cash": eq,
        "positions_value": (pos[0] if with_exposure else None),
        "total_equity": eq,
    }]
    for i, r in enumerate(rets):
        eq *= (1.0 + r)
        pv = pos[i] if with_exposure else None
        rows.append({
            "ts": (base + dt.timedelta(days=i + 1)).isoformat(),
            "cash": eq - (pv or 0.0),
            "positions_value": pv,
            "total_equity": eq,
        })
    return rows


def _grade(tmp_path, csv_text, name="ev.csv"):
    p = tmp_path / name
    p.write_text(csv_text)
    sub = intake.parse_submission(str(p), cost_bps=15, declared_trials=4)
    return certify.certify(sub)


# --------------------------------------------------------------------------
# 1) Payload carries the exposure column, right name, aligned length
# --------------------------------------------------------------------------
def test_payload_includes_exposure_column_aligned():
    rows = _platform_equity_rows(with_exposure=True)
    csv = build_certify_csv(rows)
    header, *data = csv.splitlines()
    assert header == f"timestamp,equity,{EXPOSURE_COLUMN}"
    assert EXPOSURE_COLUMN == "positions_value"           # exact name the intake reads
    # one positions_value per equity row -> length-aligned, never silently dropped
    assert len(data) == len(rows)
    assert all(len(line.split(",")) == 3 for line in data)


def test_builder_accepts_attribute_rows():
    """Works with the EquityPointRow / ORM-mapping shape too, not just dicts."""
    rows = [
        SimpleNamespace(ts="2023-01-02", cash=10000, positions_value=0, total_equity=10000),
        SimpleNamespace(ts="2023-01-03", cash=0, positions_value=500, total_equity=10010),
    ]
    csv = build_certify_csv(rows)
    assert csv.splitlines()[0].endswith(EXPOSURE_COLUMN)
    assert len(csv.splitlines()) == 3


# --------------------------------------------------------------------------
# 2) End-to-end: a low-frequency strategy now reaches a REAL verdict, and the
#    bare payload (no column) still shows the old false UNVERIFIABLE-by-stale-fill
# --------------------------------------------------------------------------
def test_low_frequency_strategy_reaches_real_verdict_through_builder(tmp_path):
    rows = _platform_equity_rows(seed=0, with_exposure=True)
    req = build_certify_request(rows, declared_trials=4, cost_bps=15)
    assert EXPOSURE_COLUMN in req["csv_text"]
    assert req["declared_trials"] == 4 and req["cost_bps"] == 15   # passthrough, unchanged

    verd = _grade(tmp_path, req["csv_text"], "with_exposure.csv")
    assert verd["integrity"]["status"] != "UNVERIFIABLE", verd["integrity"]["reasons"]
    assert verd["verdict"] in {"DEPLOY", "HOLD_CONDITIONAL", "REJECT"}
    assert not any("stale" in r for r in verd["integrity"]["reasons"])


def test_bare_payload_still_false_trips_proving_the_column_is_what_fixes_it(tmp_path):
    # Same strategy, exposure column withheld -> the pre-fix false UNVERIFIABLE.
    bare_rows = _platform_equity_rows(seed=0, with_exposure=False)
    bare_csv = build_certify_csv(bare_rows)
    assert EXPOSURE_COLUMN not in bare_csv
    verd = _grade(tmp_path, bare_csv, "bare.csv")
    assert verd["verdict"] == "UNVERIFIABLE"
    assert any("stale" in r for r in verd["integrity"]["reasons"]), verd["integrity"]["reasons"]


# --------------------------------------------------------------------------
# 3) Fallback: no exposure available -> bare payload exactly as before
# --------------------------------------------------------------------------
def test_no_exposure_fallback_is_bare():
    rows = _platform_equity_rows(with_exposure=False)
    csv = build_certify_csv(rows)
    assert csv.splitlines()[0] == "timestamp,equity"
    assert EXPOSURE_COLUMN not in csv
    req = build_certify_request(rows, declared_trials=1, cost_bps=10)
    assert EXPOSURE_COLUMN not in req["csv_text"]


def test_partial_exposure_falls_back_to_bare():
    """If positions_value is missing on any row, fall back to bare rather than
    emit a ragged column the engine would length-drop."""
    rows = _platform_equity_rows(with_exposure=True)
    rows[5]["positions_value"] = None
    csv = build_certify_csv(rows)
    assert csv.splitlines()[0] == "timestamp,equity"


def test_empty_rows_returns_none():
    assert build_certify_csv([]) is None
    assert build_certify_request([], declared_trials=1, cost_bps=10) is None
