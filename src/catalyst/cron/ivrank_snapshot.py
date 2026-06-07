"""Daily IV-rank snapshot job (Railway cron entrypoint).

Snapshots ATM IV per watchlist name into the iv_snapshots table so the wrapper
engine can compute IV rank as a trailing percentile. Until >= 60 trading days of
history exist for a name, IV rank stays UNRELIABLE and the live engine defers
options sizing to a human (Module 3).

Runs just after the close (see railway.toml). Requires a Polygon key in
production; without one it logs and exits cleanly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from .. import config as config_mod
from ..clients.base import CacheStore, ProviderUnavailable, env_key
from ..clients.polygon import PolygonClient
from ..store.db import Database
from ..store.panel import AsOfPanel
from ..options.ivrank import atm_iv_from_chain, snapshot_atm_iv


def run(as_of: date | None = None) -> int:
    cfg = config_mod.load()
    as_of = as_of or datetime.now(timezone.utc).date()
    db = Database(cfg.runtime.database_url)
    db.bootstrap()

    key = env_key("POLYGON_API_KEY")
    if not key:
        print("ivrank_snapshot: no POLYGON_API_KEY -> skipping (offline mode).")
        return 0

    poly = PolygonClient(
        cfg.runtime.polygon_base_url, api_key=key,
        cache=CacheStore(".cache/polygon", cfg.runtime.cache_ttl_seconds),
        max_retries=cfg.runtime.max_retries,
        backoff_base=cfg.runtime.backoff_base_seconds,
        backoff_max=cfg.runtime.backoff_max_seconds,
    )

    panel = AsOfPanel(db, as_of)
    count = 0
    for u in panel.universe(optionable_only=True):
        ticker = u["ticker"]
        try:
            latest = panel.latest_price(ticker)
            if not latest:
                continue
            spot = latest.get("adj_close") or latest.get("close")
            chain = poly.options_chain(ticker, as_of)
            iv = atm_iv_from_chain(chain, spot)
            if iv is not None:
                snapshot_atm_iv(db, ticker, as_of, iv)
                count += 1
        except ProviderUnavailable:
            continue  # skip names that fail; do not abort the whole job.

    db.close()
    return count


if __name__ == "__main__":  # pragma: no cover
    n = run()
    print(f"ivrank_snapshot: wrote {n} ATM-IV snapshot(s)")
