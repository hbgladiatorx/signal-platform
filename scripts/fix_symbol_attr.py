"""Fix the resume-unsafe `self.symbol` pattern in user strategies.

These strategies assign `self.symbol = self.symbols[0]` in on_init() and read
`self.symbol` in on_bar(). The runner calls on_init() once-ever and only
rehydrates `self.state` across restarts, so `self.symbol` is lost on resume and
on_bar() raises AttributeError. We rewrite them to reference `self.symbols[0]`
directly (always set by the Strategy base __init__).

Backs up originals to scripts/strategy_backups/<name>.py before writing.
Validates the transformed source compiles before persisting.

Usage (throwaway container with DB access):
    python -m scripts.fix_symbol_attr
"""
from __future__ import annotations

import asyncio
import os
import re

from sqlalchemy import text

from packages.data.db import get_engine

BACKUP_DIR = "scripts/strategy_backups"


def fix_source(src: str) -> str:
    # 1) Drop the derived-attribute assignment in on_init (annotated or not).
    src = re.sub(
        r"(?m)^(?P<indent>[ \t]*)self\.symbol\b[ \t]*"
        r"(?::[^=\n]*)?=[ \t]*self\.symbols\[0\][ \t]*$",
        r"\g<indent># self.symbol removed — use self.symbols[0] directly (resume-safe)",
        src,
    )
    # 2) Replace remaining reads of the singular attribute (never matches
    #    self.symbols thanks to the negative lookahead).
    src = re.sub(r"\bself\.symbol\b(?!s)", "self.symbols[0]", src)
    return src


async def main() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    engine = get_engine()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, name, source_code FROM user_strategies ORDER BY name")
            )
        ).mappings().all()

    changed = []
    for r in rows:
        src = r["source_code"]
        if not re.search(r"\bself\.symbol\b(?!s)", src):
            continue  # not affected
        new_src = fix_source(src)
        if new_src == src:
            continue
        # Validate before persisting.
        try:
            compile(new_src, f"<user_strategy:{r['name']}>", "exec")
        except SyntaxError as e:
            print(f"SKIP {r['name']}: transformed source failed to compile: {e}")
            continue
        # Sanity: no singular self.symbol references should remain.
        assert not re.search(r"\bself\.symbol\b(?!s)", new_src), r["name"]
        with open(f"{BACKUP_DIR}/{r['name']}.py", "w") as f:
            f.write(src)
        changed.append((r["id"], r["name"], new_src))

    if not changed:
        print("No strategies needed fixing.")
        return
    async with engine.begin() as conn:
        for sid, name, new_src in changed:
            await conn.execute(
                text(
                    "UPDATE user_strategies SET source_code = :src, "
                    "updated_at = now() WHERE id = :id"
                ),
                {"src": new_src, "id": sid},
            )
            print(f"fixed: {name}")
    print(f"\n{len(changed)} strategies updated; originals in {BACKUP_DIR}/")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
