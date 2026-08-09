"""Provider payload -> panel row transforms, with knowable_at stamping.

This is where point-in-time integrity is ESTABLISHED at write time (the panel
then enforces it at read time). Every loader is responsible for stamping the
correct knowable_at / period_end / date so that nothing in the panel is dated
earlier than the moment the market could have known it.

Field names follow each provider's documented schema as of build time. CONFIRM
against current docs before a production backfill -- API surfaces drift. Each
extractor is defensive: a missing/renamed field yields None or is skipped rather
than crashing the whole backfill.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any

from ..catalysts import types as T


# --- prices (Polygon aggregates) ------------------------------------------
def prices_from_polygon(ticker: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Polygon daily aggs (adjusted) -> price rows. 't' is epoch ms (UTC)."""
    out = []
    for r in results:
        ts = r.get("t")
        if ts is None:
            continue
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
        close = r.get("c")
        out.append({
            "ticker": ticker, "date": d.isoformat(),
            "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
            "close": close, "volume": r.get("v"),
            "adj_close": close,  # aggregates fetched with adjusted=true
        })
    return out


def prices_from_grouped(day: date, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Polygon grouped-daily results (all tickers for one day) -> price rows.

    Each result carries 'T' (ticker) and o/h/l/c/v for ``day``. adjusted=true at
    fetch time, so close is the split/dividend-adjusted close.
    """
    out = []
    iso = day.isoformat()
    for r in results:
        t = r.get("T")
        if not t:
            continue
        c = r.get("c")
        out.append({
            "ticker": t, "date": iso,
            "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
            "close": c, "volume": r.get("v"), "adj_close": c,
        })
    return out


# --- universe (Polygon reference, survivorship-correct) -------------------
def universe_from_polygon(
    as_of: date, details: list[dict[str, Any]], optionable: set[str] | None = None
) -> list[dict[str, Any]]:
    """Reference ticker details -> universe membership rows as of as_of.

    `optionable` is the set of tickers with a listed chain (the caller determines
    this; without it we fall back to the reference 'options' flag if present).
    delisted_utc non-null => the name later delisted but stays in the as-of set.
    """
    opt = optionable or set()
    out = []
    for t in details:
        tk = t.get("ticker")
        if not tk:
            continue
        delisted = (t.get("delisted_utc") or "")[:10] or None
        is_opt = tk in opt if optionable is not None else bool(t.get("options"))
        out.append({
            "ticker": tk, "as_of": as_of.isoformat(),
            "active": 0 if delisted else 1,
            "delisted_date": delisted,
            "optionable": 1 if is_opt else 0,
            "market_cap": t.get("market_cap"),
        })
    return out


# --- fundamentals (Finnhub financials-reported) ---------------------------
def fundamentals_from_finnhub(ticker: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """As-reported financials -> fundamentals rows.

    knowable_at := filing acceptance date ('acceptedDate', fallback 'filedDate').
    period_end  := 'endDate'. We extract FCF and margins best-effort from the
    as-reported statement concepts; unknown concepts yield None.
    """
    out = []
    for item in payload.get("data", []):
        period_end = (item.get("endDate") or "")[:10]
        knowable = (item.get("acceptedDate") or item.get("filedDate") or "")[:10]
        if not period_end or not knowable:
            continue
        rep = item.get("report", {}) or {}
        ic = _concepts(rep.get("ic", []))   # income statement
        cf = _concepts(rep.get("cf", []))   # cash flow
        bs = _concepts(rep.get("bs", []))   # balance sheet

        revenue = _first(ic, "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax")
        op_income = _first(ic, "OperatingIncomeLoss")
        gross = _first(ic, "GrossProfit")
        op_cf = _first(cf, "NetCashProvidedByUsedInOperatingActivities")
        capex = _first(cf, "PaymentsToAcquirePropertyPlantAndEquipment")
        debt = _first(bs, "LongTermDebtNoncurrent", "LongTermDebt",
                      "LongTermDebtAndCapitalLeaseObligations", "DebtLongtermAndShorttermCombinedAmount")
        equity = _first(bs, "StockholdersEquity")

        fcf = (op_cf - capex) if (op_cf is not None and capex is not None) else op_cf
        out.append({
            "ticker": ticker, "period_end": period_end, "knowable_at": knowable,
            "fcf": fcf,
            "gross_margin": _ratio(gross, revenue),
            "op_margin": _ratio(op_income, revenue),
            "debt_to_equity": _ratio(debt, equity),
            "as_reported": 1,
        })
    return out


def _local_name(concept: str) -> str:
    """Strip the XBRL namespace prefix: 'us-gaap_OperatingIncomeLoss' -> 'OperatingIncomeLoss'.

    Finnhub reports concepts as '{taxonomy}_{LocalName}' (us-gaap, srt, or a
    company-specific prefix). The local name has no underscore, so splitting once
    on '_' isolates it regardless of taxonomy.
    """
    return concept.split("_", 1)[1] if "_" in concept else concept


def _concepts(items: list[dict[str, Any]]) -> dict[str, float]:
    """Map local concept name -> value. Keyed by the namespace-stripped local
    name so matching is taxonomy-agnostic. First occurrence wins."""
    out: dict[str, float] = {}
    for it in items:
        concept = it.get("concept")
        val = it.get("value")
        if concept is not None and isinstance(val, (int, float)):
            out.setdefault(_local_name(str(concept)), float(val))
    return out


def _first(d: dict[str, float], *keys: str) -> float | None:
    for k in keys:
        if k in d:
            return d[k]
    return None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


# --- catalysts ------------------------------------------------------------
def _cid(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def catalysts_from_earnings(ticker: str, surprises: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Finnhub earnings surprises -> earnings catalysts. knowable_at := report date."""
    out = []
    for e in surprises:
        period = (e.get("period") or "")[:10]
        est, act = e.get("estimate"), e.get("actual")
        if not period or est in (None, 0) or act is None:
            continue
        surprise = 100.0 * (act - est) / abs(est)
        out.append({
            "catalyst_id": _cid(ticker, T.EARNINGS_SURPRISE, period),
            "ticker": ticker, "catalyst_type": T.EARNINGS_SURPRISE, "source": "finnhub",
            "knowable_at": period, "event_date": period, "tier": "structured",
            "requires_review": 0,
            "payload": {"surprise_pct": surprise, "guidance_raise": e.get("guidance_raise", False)},
        })
    return out


def catalysts_from_edgar(ticker: str, filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """EDGAR 8-K / 13D / 13G filings -> validator catalysts.

    knowable_at := filing acceptance date (the source of record for 'when the
    market could have known'). requires_review=1 (an 8-K can be good or bad).
    """
    out = []
    for f in filings:
        form = f.get("form", "")
        accepted = (f.get("acceptanceDateTime") or f.get("filingDate") or "")[:10]
        if not accepted:
            continue
        ctype = T.STRATEGIC_STAKE_13D if form.startswith("SC 13") else T.MATERIAL_8K
        out.append({
            "catalyst_id": _cid(ticker, ctype, f.get("accessionNumber", accepted)),
            "ticker": ticker, "catalyst_type": ctype, "source": "edgar",
            "knowable_at": accepted, "event_date": (f.get("filingDate") or "")[:10] or None,
            "tier": "validator", "requires_review": 1,
            "payload": {"form": form, "accession": f.get("accessionNumber")},
        })
    return out


def catalysts_from_federal(ticker: str, awards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """USASpending awards -> federal-award validator catalysts. knowable_at := award start date."""
    out = []
    for a in awards:
        start = (a.get("Start Date") or a.get("period_of_performance_start_date") or "")[:10]
        amount = a.get("Award Amount") or a.get("award_amount") or 0
        award_id = a.get("Award ID") or a.get("generated_internal_id") or start
        if not start:
            continue
        out.append({
            "catalyst_id": _cid(ticker, T.FEDERAL_AWARD, award_id),
            "ticker": ticker, "catalyst_type": T.FEDERAL_AWARD, "source": "usaspending",
            "knowable_at": start, "event_date": start, "tier": "validator",
            "requires_review": 1,
            "payload": {"award_amount_usd": amount, "award_id": award_id},
        })
    return out
