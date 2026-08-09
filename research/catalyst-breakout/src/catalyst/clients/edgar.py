"""SEC EDGAR client: full-text search + submissions API.

This is the CATALYST POINT-IN-TIME SOURCE OF RECORD (Section 2). The field that
matters is the filing ACCEPTANCE timestamp -- when the market could have known --
not the event/period date. 8-K material events and 13D/13G strategic stakes are
read here and stamped with ``acceptanceDateTime``.

EDGAR requires NO API key but DOES require a descriptive User-Agent with contact
info, and rate-limits to ~10 req/s. The base client's backoff handles 429s.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import BaseClient


class EdgarClient(BaseClient):
    def __init__(self, *args, submissions_url: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.submissions_url = (submissions_url or "https://data.sec.gov").rstrip("/")

    def full_text_search(
        self, query: str, forms: str, frm: date, to: date
    ) -> list[dict[str, Any]]:
        """EDGAR full-text search (EFTS). Returns filing hits w/ acceptance times."""
        params = {
            "q": query,
            "forms": forms,
            "dateRange": "custom",
            "startdt": frm.isoformat(),
            "enddt": to.isoformat(),
        }
        data = self.get_json("/LATEST/search-index", params)
        hits = data.get("hits", {}).get("hits", []) if isinstance(data, dict) else []
        return hits

    def ticker_cik_map(self) -> dict[str, str]:
        """SEC ticker -> zero-padded 10-digit CIK map (company_tickers.json)."""
        data = self.get_json("https://www.sec.gov/files/company_tickers.json")
        out: dict[str, str] = {}
        if isinstance(data, dict):
            for v in data.values():
                t = v.get("ticker")
                cik = v.get("cik_str")
                if t and cik is not None:
                    out[t.upper()] = str(cik).zfill(10)
        return out

    def company_submissions(self, cik: str) -> dict[str, Any]:
        """All recent submissions for a CIK, incl. acceptanceDateTime per filing."""
        cik10 = str(cik).zfill(10)
        return self.get_json(f"{self.submissions_url}/submissions/CIK{cik10}.json")

    def recent_filings(
        self, cik: str, forms: tuple[str, ...], as_of: date
    ) -> list[dict[str, Any]]:
        """Filings of given forms with acceptance <= as_of (PIT enforced here)."""
        subs = self.company_submissions(cik)
        recent = subs.get("filings", {}).get("recent", {})
        cols = ("form", "acceptanceDateTime", "filingDate", "primaryDocument", "accessionNumber")
        rows = zip(*(recent.get(c, []) for c in cols))
        out = []
        for form, accepted, filed, doc, accession in rows:
            if form not in forms:
                continue
            # acceptanceDateTime like '2023-09-18T16:30:11.000Z'
            accepted_date = (accepted or filed or "")[:10]
            if accepted_date and accepted_date <= as_of.isoformat():
                out.append(
                    {
                        "form": form,
                        "acceptanceDateTime": accepted,
                        "filingDate": filed,
                        "primaryDocument": doc,
                        "accessionNumber": accession,
                    }
                )
        return out
