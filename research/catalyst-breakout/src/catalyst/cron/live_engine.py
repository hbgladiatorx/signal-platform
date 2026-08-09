"""Daily LIVE signal engine (Railway cron entrypoint).

Wires Modules 0-5 for one trading day:
  watchlist (Module 1) -> catalyst gate (Module 2) -> wrapper (Module 3) ->
  entry/exit (Module 4) -> payload + persist + push (Module 5).

Selective by design: expect under one new entry per day. Validator-tier signals
are flagged requires_review for a human bull/bear judgement before action.

Runs against whatever is materialized in the panel as of `today`. Provider
clients are constructed when keys exist; missing providers degrade gracefully
(the signal is still emitted, with missing inputs flagged) rather than crash.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

from .. import config as config_mod
from ..clients.base import CacheStore, env_key
from ..clients.polygon import PolygonClient
from ..ingest.chain import make_chain_fetcher
from ..store.db import Database
from ..store.panel import AsOfPanel
from ..pit.features import get_pit_features
from ..screen.distressed import passes_screen
from ..catalysts.detectors import detect_from_panel
from ..options.wrapper import select_wrapper
from ..signals.entryexit import build_plan
from ..signals.output import build_payload, persist, push


def run(as_of: date | None = None) -> list[dict]:
    cfg = config_mod.load()
    as_of = as_of or datetime.now(timezone.utc).date()
    db = Database(cfg.runtime.database_url)
    db.bootstrap()
    panel = AsOfPanel(db, as_of)
    webhook = os.environ.get("SIGNAL_WEBHOOK_URL")
    generated_at = datetime.now(timezone.utc).isoformat()

    # Real options chain fetcher when a Polygon key is present; otherwise the
    # fetcher returns [] and the wrapper degrades to COMMON/REJECT.
    poly = None
    if env_key("POLYGON_API_KEY"):
        poly = PolygonClient(
            cfg.runtime.polygon_base_url, api_key=env_key("POLYGON_API_KEY"),
            cache=CacheStore(".cache/polygon", cfg.runtime.cache_ttl_seconds),
            max_retries=cfg.runtime.max_retries,
            backoff_base=cfg.runtime.backoff_base_seconds,
            backoff_max=cfg.runtime.backoff_max_seconds,
        )
    fetch_chain = make_chain_fetcher(poly)

    emitted: list[dict] = []
    universe = panel.universe(optionable_only=False)
    for u in universe:
        ticker = u["ticker"]
        row = get_pit_features(ticker, as_of, panel, cfg)
        if row is None:
            continue
        screen = passes_screen(row, cfg)
        if not screen.passed:
            continue  # Module 1 watchlist gate.

        catalysts = detect_from_panel(row, cfg)
        if not catalysts:
            continue  # Module 2: no fresh catalyst -> not a candidate.
        catalyst = sorted(
            catalysts, key=lambda c: (c.tier == "validator", c.knowable_at), reverse=True
        )[0]

        wrapper = select_wrapper(
            chain=fetch_chain(ticker, as_of),
            spot=row.price or 0.0,
            iv_rank=row.iv_rank,
            iv_rank_reliable=row.iv_rank_reliable,
            catalyst_resolution=None,
            as_of=as_of,
            target_price=None,
            market_cap=row.market_cap,
            cfg=cfg,
        )
        plan = build_plan(row, catalyst_trigger_price=row.price or 0.0, cfg=cfg)

        payload = build_payload(
            generated_at=generated_at, row=row, screen=screen,
            catalyst=catalyst, wrapper=wrapper, plan=plan,
        )
        persist(db, payload)
        push(payload, webhook)
        emitted.append({"ticker": ticker, "signal_id": payload.signal_id,
                        "requires_review": payload.requires_review,
                        "instrument": payload.instrument,
                        "confidence": payload.confidence_bucket})

    db.close()
    return emitted


if __name__ == "__main__":  # pragma: no cover
    out = run()
    print(f"live_engine: emitted {len(out)} signal(s)")
    for s in out:
        flag = " [REVIEW]" if s["requires_review"] else ""
        print(f"  {s['ticker']:6s} {s['instrument']:7s} {s['confidence']:6s}{flag}")
