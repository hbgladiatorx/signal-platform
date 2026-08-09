"""Finnhub client: fundamentals, earnings, analyst revisions, insider & inst. ownership.

PIT WARNING: Finnhub fundamentals must be lagged to FILING availability, not
period-end (Section 3 / anti-bias rule #4). This client returns raw payloads; the
PIT layer (``catalyst.pit.features``) is responsible for stamping each datum with
its knowable date and filtering on it. Do not consume these directly in the
backtester.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import BaseClient


class FinnhubClient(BaseClient):
    def _auth_params(self) -> dict[str, str]:
        return {"token": self.api_key} if self.api_key else {}

    def basic_financials(self, ticker: str) -> dict[str, Any]:
        return self.get_json("/stock/metric", {"symbol": ticker, "metric": "all"})

    def reported_financials(self, ticker: str, freq: str = "quarterly") -> dict[str, Any]:
        """As-reported (not restated) financials. Each item carries filing date."""
        return self.get_json("/stock/financials-reported", {"symbol": ticker, "freq": freq})

    def earnings_calendar(self, ticker: str, frm: date, to: date) -> dict[str, Any]:
        return self.get_json(
            "/calendar/earnings",
            {"symbol": ticker, "from": frm.isoformat(), "to": to.isoformat()},
        )

    def earnings_surprises(self, ticker: str) -> list[dict[str, Any]]:
        data = self.get_json("/stock/earnings", {"symbol": ticker})
        return data if isinstance(data, list) else []

    def recommendation_trends(self, ticker: str) -> list[dict[str, Any]]:
        data = self.get_json("/stock/recommendation", {"symbol": ticker})
        return data if isinstance(data, list) else []

    def price_target(self, ticker: str) -> dict[str, Any]:
        return self.get_json("/stock/price-target", {"symbol": ticker})

    def insider_transactions(self, ticker: str, frm: date, to: date) -> dict[str, Any]:
        return self.get_json(
            "/stock/insider-transactions",
            {"symbol": ticker, "from": frm.isoformat(), "to": to.isoformat()},
        )

    def institutional_ownership(self, ticker: str, frm: date, to: date) -> dict[str, Any]:
        return self.get_json(
            "/stock/institutional-ownership",
            {"symbol": ticker, "from": frm.isoformat(), "to": to.isoformat()},
        )
