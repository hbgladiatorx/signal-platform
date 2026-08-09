"""USASpending.gov + SAM.gov clients: federal contract / grant awards.

Validator catalyst source (Section 5). Each award carries an AWARD DATE which the
PIT layer uses as ``knowable_at``. USASpending is an open API (no key); SAM.gov
requires a key.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import BaseClient


class USASpendingClient(BaseClient):
    """USASpending.gov v2 API. Open; no key required."""

    def award_search(
        self, recipient_name: str, frm: date, to: date, min_amount: float
    ) -> list[dict[str, Any]]:
        """POST-style award search, expressed via the spending_by_award endpoint.

        The base client issues GET; USASpending's search is POST. In production,
        override transport for this endpoint. Shape kept stable for the PIT layer.
        """
        payload = {
            "filters": {
                "recipient_search_text": [recipient_name],
                "time_period": [{"start_date": frm.isoformat(), "end_date": to.isoformat()}],
                "award_amounts": [{"lower_bound": min_amount}],
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Start Date"],
            "limit": 100,
        }
        data = self._post_json("/search/spending_by_award/", payload)
        return data.get("results", []) if isinstance(data, dict) else []

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        from .base import ProviderUnavailable

        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ProviderUnavailable(str(e)) from e
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = requests.post(
                url, json=payload, headers=self._auth_headers(), timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            # Surface as ProviderUnavailable so callers degrade gracefully rather
            # than aborting a backfill (e.g. a 422 on a recipient-name search).
            raise ProviderUnavailable(f"USASpending POST {path} failed: {e}") from e


class SAMClient(BaseClient):
    """SAM.gov opportunities/awards. Requires SAM_API_KEY."""

    def _auth_params(self) -> dict[str, str]:
        return {"api_key": self.api_key} if self.api_key else {}

    def opportunities(self, keyword: str, frm: date, to: date) -> list[dict[str, Any]]:
        data = self.get_json(
            "/opportunities/v2/search",
            {
                "keyword": keyword,
                "postedFrom": frm.strftime("%m/%d/%Y"),
                "postedTo": to.strftime("%m/%d/%Y"),
                "limit": 100,
            },
        )
        return data.get("opportunitiesData", []) if isinstance(data, dict) else []
