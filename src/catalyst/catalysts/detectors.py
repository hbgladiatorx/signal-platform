"""MODULE 2 -- catalyst detection (the gate, and the alpha).

A watchlist name becomes a CANDIDATE only when a fresh, material catalyst fires.
Two tiers (Section 5): structured (backtestable) and validator (the real edge).

Two entry points:
  * detect_from_panel(...)   -- reads catalysts already stamped in the panel with
                                knowable_at; used by the BACKTESTER (PIT-safe).
  * detect_live(...)         -- pulls from provider clients for the LIVE engine.

Both return List[CatalystHit]. Validator-tier hits are marked requires_review so
the live engine routes them to a human bull/bear judgement (an 8-K can be good or
bad).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import types as T
from .types import CatalystHit
from ..pit.features import FeatureRow
from config.defaults import Config, DEFAULTS


def _tier_for(ctype: str) -> str:
    return "validator" if ctype in T.VALIDATOR_TYPES else "structured"


def detect_from_panel(row: FeatureRow, cfg: Config = DEFAULTS) -> list[CatalystHit]:
    """Classify/filter panel-sourced catalyst rows into qualified CatalystHits.

    The panel rows already carry knowable_at <= as_of (the panel enforced it), so
    this is PIT-safe by construction. We apply config materiality thresholds.
    """
    hits: list[CatalystHit] = []
    for c in row.catalysts:
        ctype = c["catalyst_type"]
        payload = c.get("payload") or {}
        if not _is_material(ctype, payload, cfg):
            continue
        tier = c.get("tier") or _tier_for(ctype)
        requires_review = (
            tier == "validator" and cfg.catalyst.validator_requires_review
        )
        hits.append(
            CatalystHit(
                ticker=row.ticker,
                catalyst_type=ctype,
                source=c.get("source", "panel"),
                knowable_at=str(c["knowable_at"]),
                tier=tier,
                event_date=c.get("event_date"),
                requires_review=requires_review,
                payload=payload,
            )
        )
    return hits


def _is_material(ctype: str, payload: dict[str, Any], cfg: Config) -> bool:
    """Apply the configured materiality threshold for the catalyst type."""
    c = cfg.catalyst
    if ctype == T.EARNINGS_SURPRISE:
        surprise_ok = float(payload.get("surprise_pct", 0)) >= c.min_earnings_surprise_pct
        guidance_ok = (not c.require_guidance_raise_with_surprise) or bool(
            payload.get("guidance_raise")
        )
        return surprise_ok and guidance_ok
    if ctype == T.ANALYST_REVISION_CLUSTER:
        return int(payload.get("revision_count", 0)) >= c.analyst_revision_cluster_n
    if ctype == T.INSIDER_BUY_CLUSTER:
        return float(payload.get("net_buy_usd", 0)) >= c.insider_net_buy_threshold_usd
    if ctype == T.NEW_INSTITUTIONAL:
        return float(payload.get("position_delta_pct", 0)) >= c.institutional_position_delta_pct
    if ctype == T.FEDERAL_AWARD:
        return float(payload.get("award_amount_usd", 0)) >= c.federal_award_min_usd
    if ctype == T.STRATEGIC_STAKE_13D:
        # A 13D/13G is only filed when a holder crosses the 5% threshold, so the
        # form's existence implies materiality. If the stake % was parsed from the
        # filing body, enforce the configured floor; otherwise accept on form.
        if "stake_pct" in payload and payload["stake_pct"] is not None:
            return float(payload["stake_pct"]) >= c.strategic_stake_min_pct
        return True
    if ctype in (T.MATERIAL_8K, T.STRATEGIC_INVESTMENT):
        return True  # materiality confirmed at ingest (8-K cross-reference).
    return False


# --- live detection (provider-backed) -------------------------------------
def detect_live(
    ticker: str,
    as_of: date,
    *,
    finnhub=None,
    edgar=None,
    usaspending=None,
    cik: str | None = None,
    cfg: Config = DEFAULTS,
) -> list[CatalystHit]:
    """Pull fresh catalysts from providers for the LIVE engine.

    Each branch is wrapped defensively: a provider failure on one catalyst type
    must not suppress the others. Returns qualified, knowable-at-stamped hits.
    """
    hits: list[CatalystHit] = []
    window_start = as_of - timedelta(days=max(cfg.catalyst.analyst_revision_window_days, 30))

    if finnhub is not None:
        hits += _live_earnings(finnhub, ticker, as_of, cfg)
        hits += _live_analyst(finnhub, ticker, as_of, cfg)
        hits += _live_insider(finnhub, ticker, window_start, as_of, cfg)

    if edgar is not None and cik:
        hits += _live_edgar(edgar, ticker, cik, as_of, cfg)

    if usaspending is not None:
        hits += _live_federal(usaspending, ticker, window_start, as_of, cfg)

    return hits


def _safe(fn):
    try:
        return fn()
    except Exception:
        return []


def _live_earnings(client, ticker, as_of, cfg) -> list[CatalystHit]:
    def run():
        out = []
        for e in client.earnings_surprises(ticker):
            period = e.get("period", "")
            if not period or period > as_of.isoformat():
                continue
            est, act = e.get("estimate"), e.get("actual")
            if est in (None, 0) or act is None:
                continue
            surprise = 100.0 * (act - est) / abs(est)
            payload = {"surprise_pct": surprise, "guidance_raise": e.get("guidance_raise", False)}
            if _is_material(T.EARNINGS_SURPRISE, payload, cfg):
                out.append(
                    CatalystHit(ticker, T.EARNINGS_SURPRISE, "finnhub",
                               knowable_at=period, tier="structured", payload=payload)
                )
        return out
    return _safe(run)


def _live_analyst(client, ticker, as_of, cfg) -> list[CatalystHit]:
    def run():
        trends = client.recommendation_trends(ticker)
        recent = [t for t in trends if t.get("period", "") <= as_of.isoformat()]
        if len(recent) < 2:
            return []
        now, prev = recent[0], recent[1]
        ups = (now.get("strongBuy", 0) + now.get("buy", 0)) - (
            prev.get("strongBuy", 0) + prev.get("buy", 0)
        )
        payload = {"revision_count": max(ups, 0)}
        if _is_material(T.ANALYST_REVISION_CLUSTER, payload, cfg):
            return [CatalystHit(ticker, T.ANALYST_REVISION_CLUSTER, "finnhub",
                                knowable_at=now.get("period"), tier="structured", payload=payload)]
        return []
    return _safe(run)


def _live_insider(client, ticker, frm, as_of, cfg) -> list[CatalystHit]:
    def run():
        data = client.insider_transactions(ticker, frm, as_of)
        txns = data.get("data", []) if isinstance(data, dict) else []
        net = sum((t.get("change", 0) or 0) * (t.get("transactionPrice", 0) or 0)
                  for t in txns if (t.get("change", 0) or 0) > 0)
        payload = {"net_buy_usd": net}
        if _is_material(T.INSIDER_BUY_CLUSTER, payload, cfg):
            return [CatalystHit(ticker, T.INSIDER_BUY_CLUSTER, "finnhub",
                                knowable_at=as_of.isoformat(), tier="structured", payload=payload)]
        return []
    return _safe(run)


def _live_edgar(client, ticker, cik, as_of, cfg) -> list[CatalystHit]:
    def run():
        out = []
        for f in client.recent_filings(cik, ("8-K", "SC 13D", "SC 13G"), as_of):
            ctype = T.STRATEGIC_STAKE_13D if f["form"].startswith("SC 13") else T.MATERIAL_8K
            out.append(
                CatalystHit(
                    ticker, ctype, "edgar",
                    knowable_at=(f.get("acceptanceDateTime") or f.get("filingDate"))[:10],
                    tier="validator",
                    event_date=f.get("filingDate"),
                    requires_review=cfg.catalyst.validator_requires_review,
                    payload={"form": f["form"], "accession": f.get("accessionNumber")},
                )
            )
        return out
    return _safe(run)


def _live_federal(client, ticker, frm, as_of, cfg) -> list[CatalystHit]:
    def run():
        out = []
        for a in client.award_search(ticker, frm, as_of, cfg.catalyst.federal_award_min_usd):
            amt = a.get("Award Amount") or a.get("award_amount") or 0
            payload = {"award_amount_usd": amt, "award_id": a.get("Award ID")}
            if _is_material(T.FEDERAL_AWARD, payload, cfg):
                out.append(
                    CatalystHit(
                        ticker, T.FEDERAL_AWARD, "usaspending",
                        knowable_at=(a.get("Start Date") or as_of.isoformat())[:10],
                        tier="validator",
                        requires_review=cfg.catalyst.validator_requires_review,
                        payload=payload,
                    )
                )
        return out
    return _safe(run)
