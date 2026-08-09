"""Config loading with env overrides.

Routes everything through :data:`config.defaults`. Reads optional overrides from
environment variables of the form ``CATALYST_<SECTION>_<KEY>`` so deployments can
tune without code edits -- but the *defaults* remain the locked, a-priori values
(anti-bias rule #5).
"""

from __future__ import annotations

import os
from dataclasses import replace, fields, is_dataclass
from typing import Any

# config/ is a top-level package (see pyproject pythonpath = ["src", "."]).
from config.defaults import Config, DEFAULTS


def _coerce(current: Any, raw: str) -> Any:
    """Coerce an env string to the type of the existing default value."""
    if isinstance(current, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(float(raw))
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, tuple):
        return tuple(p.strip() for p in raw.split(","))
    return raw


def load(env: dict[str, str] | None = None) -> Config:
    """Build a Config from defaults, applying CATALYST_<SECTION>_<KEY> overrides."""
    env = dict(os.environ if env is None else env)
    cfg = DEFAULTS

    # DATABASE_URL is a common, conventionally-named override.
    if env.get("DATABASE_URL"):
        cfg = replace(cfg, runtime=replace(cfg.runtime, database_url=env["DATABASE_URL"]))
    if env.get("SEC_USER_AGENT"):
        cfg = replace(cfg, runtime=replace(cfg.runtime, user_agent=env["SEC_USER_AGENT"]))

    updates: dict[str, dict[str, Any]] = {}
    for section_name in (f.name for f in fields(cfg)):
        section = getattr(cfg, section_name)
        if not is_dataclass(section):
            continue
        for f in fields(section):
            key = f"CATALYST_{section_name.upper()}_{f.name.upper()}"
            if key in env:
                cur = getattr(section, f.name)
                updates.setdefault(section_name, {})[f.name] = _coerce(cur, env[key])

    for section_name, changes in updates.items():
        section = getattr(cfg, section_name)
        cfg = replace(cfg, **{section_name: replace(section, **changes)})

    return cfg
