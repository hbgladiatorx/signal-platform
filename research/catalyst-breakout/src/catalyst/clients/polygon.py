"""Polygon (Options Advanced) client.

PIT-relevant capabilities used by the system:
  * equity aggregates (point-in-time OHLCV, split/dividend adjusted),
  * full options chains with per-contract IV, greeks, OI, volume, quotes,
  * reference data INCLUDING DELISTED tickers (survivorship reconstruction),
  * corporate actions (splits, dividends).

NOTE: confirm exact endpoint paths / params against current Polygon docs before
production use. Paths below match the v2/v3 REST layout as of build time.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import BaseClient


class PolygonClient(BaseClient):
    def _auth_params(self) -> dict[str, str]:
        return {"apiKey": self.api_key} if self.api_key else {}

    # -- equities ----------------------------------------------------------
    def daily_aggregates(
        self, ticker: str, start: date, end: date, adjusted: bool = True
    ) -> list[dict[str, Any]]:
        """Adjusted daily bars. adjusted=True applies splits & dividends."""
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        data = self.get_json(path, {"adjusted": str(adjusted).lower(), "limit": 50000})
        return data.get("results", []) if isinstance(data, dict) else []

    # -- reference / survivorship -----------------------------------------
    def list_tickers(
        self, as_of: date, *, include_delisted: bool = True, market: str = "stocks"
    ) -> list[dict[str, Any]]:
        """Reference tickers active as of ``as_of``.

        include_delisted=True is REQUIRED for survivorship-correct universe
        reconstruction (Section 3 / anti-bias rule #3).
        """
        params = {
            "market": market,
            "date": as_of.isoformat(),
            "active": "false" if include_delisted else "true",
            "limit": 1000,
        }
        out: list[dict[str, Any]] = []
        data = self.get_json("/v3/reference/tickers", params)
        while isinstance(data, dict):
            out.extend(data.get("results", []))
            nxt = data.get("next_url")
            if not nxt:
                break
            data = self.get_json(nxt)
        return out

    def grouped_daily(self, day: date, adjusted: bool = True) -> list[dict[str, Any]]:
        """ALL US stocks' OHLCV for a single day in ONE call (survivorship-correct:
        delisted names appear on the days they traded). Empty on non-trading days."""
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}"
        data = self.get_json(path, {"adjusted": str(adjusted).lower()})
        return data.get("results", []) if isinstance(data, dict) else []

    def ticker_details(self, ticker: str, as_of: date) -> dict[str, Any]:
        """Reference details for one ticker as of a date (market_cap, delisted_utc)."""
        data = self.get_json(f"/v3/reference/tickers/{ticker}", {"date": as_of.isoformat()})
        return data.get("results", {}) if isinstance(data, dict) else {}

    # -- options -----------------------------------------------------------
    def options_chain(self, underlying: str, as_of: date) -> list[dict[str, Any]]:
        """Full chain snapshot w/ greeks, IV, OI, volume, quotes for as_of."""
        params = {"underlying_ticker": underlying, "as_of": as_of.isoformat(), "limit": 250}
        out: list[dict[str, Any]] = []
        data = self.get_json(f"/v3/snapshot/options/{underlying}", params)
        while isinstance(data, dict):
            out.extend(data.get("results", []))
            nxt = data.get("next_url")
            if not nxt:
                break
            data = self.get_json(nxt)
        return out

    def corporate_actions(self, ticker: str) -> dict[str, Any]:
        splits = self.get_json("/v3/reference/splits", {"ticker": ticker, "limit": 1000})
        divs = self.get_json("/v3/reference/dividends", {"ticker": ticker, "limit": 1000})
        return {
            "splits": splits.get("results", []) if isinstance(splits, dict) else [],
            "dividends": divs.get("results", []) if isinstance(divs, dict) else [],
        }
