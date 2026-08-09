"""Slow LLM meta-layer — a regime/risk controller that sits ABOVE the proven 1h
strategies and only throttles their exposure on a slow (daily) cadence.

It NEVER fires individual trades. Once per `cadence_bars`, it builds an
ANONYMIZED statistical digest of the asset's recent price action (no dates, no
ticker — so the LLM can't pattern-match to a remembered historical moment) and
asks Claude for a single number: gross_exposure in [0,1] for a mean-reversion
book. High in calm/ranging tape where MR works; low in strong trends / high-vol
/ risk-off where MR gets run over.

Look-ahead safety: a decision at bar i is computed from df.iloc[:i+1] only
(past + the just-closed bar) and is applied to bars STRICTLY AFTER i (the harness
forward-fills with `decision_ts < bar_ts`). This matches the engine's
"signal on close[i], fill at open[i+1]" semantics — no peeking.

Determinism / cost: every decision is cached to a JSONL keyed by a hash of the
ROUNDED digest, so (a) re-runs are free, (b) the control vs treatment runs and
any param sweep all reuse the same answers, and (c) near-identical tape dedupes.

Set META_MOCK=1 to replace the LLM with a transparent rule (exposure from the
trend z-score). Lets you validate the whole A/B pipeline end-to-end without
spending a cent, and doubles as a "is the LLM beating a dumb rule?" baseline.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

MODEL = os.environ.get("META_MODEL", "claude-sonnet-4-6")
CACHE_DIR = Path(os.environ.get("META_CACHE_DIR", "/app/logs"))

SYSTEM_PROMPT = """\
You are a risk-regime controller for an automated MEAN-REVERSION trading book.
Each call you receive anonymized statistics about one asset's recent price action
(no name, no dates). Output a single gross-exposure multiplier in [0,1] that scales
how much capital the mean-reversion strategy may deploy on the NEXT period.

Principles:
- Mean-reversion PROFITS in calm, ranging, range-bound tape (moderate vol, price
  oscillating around its trend). Give HIGH exposure (0.8-1.0) there.
- Mean-reversion gets RUN OVER by strong directional trends and volatility blowups
  (price far from trend and still extending, vol spiking, deep drawdowns). Cut
  exposure HARD (0.0-0.3) there — better to sit out than fight a trend.
- Intermediate / unclear regimes: 0.4-0.7.
- You are a throttle, not a forecaster. Do not try to predict direction.

Respond with ONLY a JSON object, no prose:
{"regime": "range|trend_up|trend_down|risk_off", "gross_exposure": 0.0, "notes": "<=12 words"}
"""


@dataclass
class RegimeDecision:
    ts: datetime
    gross_exposure: float
    regime: str
    notes: str
    source: str  # "llm" | "cache" | "mock" | "fallback"


# ----------------------------------------------------------------------------
# Digest — anonymized, rounded features from history up to (and including) bar i.
# ----------------------------------------------------------------------------
def _rsi(close: np.ndarray, period: int = 14) -> float:
    if len(close) <= period:
        return 50.0
    d = np.diff(close)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    # Wilder smoothing
    ag = up[:period].mean()
    al = dn[:period].mean()
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + up[i]) / period
        al = (al * (period - 1) + dn[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return float(100 - 100 / (1 + rs))


def build_digest(hist: pd.DataFrame) -> dict | None:
    """Anonymized, rounded stats from the visible history. None if too short."""
    c = hist["close"].to_numpy(float)
    if len(c) < 220:
        return None
    ret = np.diff(c) / c[:-1]
    vol_1d = float(np.std(ret[-24:]))            # realized vol, last day (hourly)
    vol_30d = float(np.std(ret[-720:])) if len(ret) >= 720 else float(np.std(ret))
    vol_ratio = vol_1d / vol_30d if vol_30d > 0 else 1.0
    sma200 = float(np.mean(c[-200:]))
    sd200 = float(np.std(c[-200:])) or 1.0
    trend_z = (c[-1] - sma200) / sd200           # how far above/below trend, in sd
    ret_1d = c[-1] / c[-24] - 1
    ret_7d = c[-1] / c[-168] - 1 if len(c) >= 168 else c[-1] / c[0] - 1
    hi_7d = float(np.max(c[-168:])) if len(c) >= 168 else float(np.max(c))
    dd_from_high = c[-1] / hi_7d - 1             # <=0
    rsi14 = _rsi(c[-200:])
    # Round hard — kills noise, maximizes cache hits, anonymizes magnitude.
    return {
        "trend_z": round(float(trend_z), 1),
        "vol_ratio": round(float(vol_ratio), 1),
        "vol_30d_pct": round(float(vol_30d) * 100, 2),
        "ret_1d_pct": round(float(ret_1d) * 100, 1),
        "ret_7d_pct": round(float(ret_7d) * 100, 0),
        "dd_from_7d_high_pct": round(float(dd_from_high) * 100, 0),
        "rsi14": round(float(rsi14), 0),
    }


def _digest_key(digest: dict) -> str:
    return hashlib.sha1(
        json.dumps(digest, sort_keys=True).encode()
    ).hexdigest()[:16]


# ----------------------------------------------------------------------------
# Decision — mock rule, disk cache, or live LLM.
# ----------------------------------------------------------------------------
def _mock_exposure(digest: dict) -> dict:
    """Transparent baseline: exposure falls as price stretches from trend and as
    short-vol spikes. No API. Used for plumbing smoke-tests + as a dumb-rule bench."""
    z = abs(digest["trend_z"])
    vr = digest["vol_ratio"]
    expo = 1.0
    expo -= min(0.6, 0.25 * max(0.0, z - 1.0))   # stretched-trend penalty
    expo -= min(0.4, 0.3 * max(0.0, vr - 1.5))   # vol-spike penalty
    expo = max(0.0, min(1.0, expo))
    reg = "range" if z < 1 else ("trend_up" if digest["trend_z"] > 0 else "trend_down")
    return {"regime": reg, "gross_exposure": round(expo, 2), "notes": "mock rule"}


def _make_client():
    from anthropic import Anthropic

    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=60.0)


def _call_llm(digest: dict, client=None) -> dict:
    if client is None:
        client = _make_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=120,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(digest)}],
    )
    text = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()
    start, end = text.find("{"), text.rfind("}")
    obj = json.loads(text[start : end + 1])
    return obj


def _normalize(obj: dict) -> dict:
    expo = float(obj.get("gross_exposure", 0.5))
    expo = max(0.0, min(1.0, expo))
    return {
        "regime": str(obj.get("regime", "unknown"))[:20],
        "gross_exposure": expo,
        "notes": str(obj.get("notes", ""))[:80],
    }


class _Cache:
    def __init__(self, path: Path):
        self.path = path
        self.mem: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.mem[rec["key"]] = rec["decision"]

    def get(self, key: str) -> dict | None:
        return self.mem.get(key)

    def put(self, key: str, digest: dict, decision: dict) -> None:
        self.mem[key] = decision
        with self.path.open("a") as f:
            f.write(json.dumps({"key": key, "digest": digest, "decision": decision}) + "\n")


# ----------------------------------------------------------------------------
# Top-level: produce the regime timeline for a window.
# ----------------------------------------------------------------------------
def compute_regime_timeline(
    df: pd.DataFrame,
    *,
    symbol_tag: str,
    cadence_bars: int = 24,
    warmup_bars: int = 220,
) -> list[RegimeDecision]:
    """Walk df at `cadence_bars` cadence; return one RegimeDecision per step.

    `symbol_tag` only namespaces the cache file — it is NOT shown to the LLM.
    Decisions are emitted at the decision bar's timestamp; the harness applies
    each to bars strictly after it (forward-fill with decision_ts < bar_ts).
    """
    mock = os.environ.get("META_MOCK") == "1"
    workers = int(os.environ.get("META_WORKERS", "16"))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Shared cross-symbol cache: an anonymized rounded digest decides the same
    # regardless of ticker, so all symbols read/write one file and reuse answers.
    cache = _Cache(CACHE_DIR / f"meta_cache{'_mock' if mock else '_llm'}.jsonl")

    # --- pass 1: enumerate decision points (ts, digest, key) ---
    points: list[tuple[datetime, dict, str]] = []
    for i in range(warmup_bars, len(df), cadence_bars):
        digest = build_digest(df.iloc[: i + 1])
        if digest is None:
            continue
        points.append((df.index[i].to_pydatetime(), digest, _digest_key(digest)))

    # --- resolve: only the UNIQUE, UNCACHED digests need work ---
    todo = {key: dg for _, dg, key in points if cache.get(key) is None}
    n_new = len(todo)
    if todo and mock:
        for key, dg in todo.items():
            cache.put(key, dg, _normalize(_mock_exposure(dg)))
    elif todo:
        from concurrent.futures import ThreadPoolExecutor

        client = _make_client()

        def _one(item):
            key, dg = item
            try:
                return key, dg, _normalize(_call_llm(dg, client)), "llm"
            except Exception as e:  # noqa: BLE001 — one bad call must not kill the run
                return key, dg, {"regime": "fallback", "gross_exposure": 0.5,
                                 "notes": f"err:{type(e).__name__}"}, "fallback"

        n_fallback = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for key, dg, dec, src in ex.map(_one, list(todo.items())):
                cache.put(key, dg, dec)  # main-thread writes only — no file race
                n_fallback += src == "fallback"
        if n_fallback:
            print(f"  [{symbol_tag}] WARNING {n_fallback}/{n_new} LLM calls fell back", flush=True)

    # --- pass 2: assemble timeline from cache ---
    out = [
        RegimeDecision(ts=ts, gross_exposure=cache.get(key)["gross_exposure"],
                       regime=cache.get(key)["regime"], notes=cache.get(key)["notes"],
                       source="cache")
        for ts, _, key in points
    ]
    print(f"  [{symbol_tag}] {len(out)} decisions ({n_new} new {'mock' if mock else 'LLM'} "
          f"calls, {len(out) - n_new} from cache)", flush=True)
    return out
