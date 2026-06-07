"""One-off: recompile stored user_strategies from their graph_json.

Existing rows were compiled before the long/short fix and hold contradictory
source ("RSI < 30 and RSI > 70" → 0 trades). Recompile each row that has a
graph_json, validate, and update source_code / class_name / params_schema when
the compile succeeds and the source actually changed. Rows without a graph_json
(hand-written or LLM-translated) are left untouched.
"""

import asyncio
import json

from sqlalchemy import text

from packages.data.db import get_engine
from packages.strategy.graph_compiler import compile_graph_to_source
from packages.strategy.validator import validate_strategy_source


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "select id, name, asset_class, graph_json, source_code "
            "from user_strategies where graph_json is not null"
        ))).mappings().all()

        print(f"{len(rows)} strategies with a graph_json")
        updated = skipped = failed = 0
        for r in rows:
            graph = r["graph_json"]
            if isinstance(graph, str):
                graph = json.loads(graph)
            compiled = compile_graph_to_source(
                name=r["name"], asset_class=r["asset_class"] or "stocks", graph=graph,
            )
            if not compiled.ok or not compiled.source_code:
                print(f"  SKIP (compile fallback) {r['name']!r}: {compiled.reason}")
                failed += 1
                continue
            if compiled.source_code == r["source_code"]:
                skipped += 1
                continue
            validation = validate_strategy_source(compiled.source_code)
            if not validation.ok:
                print(f"  SKIP (invalid) {r['name']!r}: "
                      f"{[e.as_dict() for e in validation.errors][:2]}")
                failed += 1
                continue
            await conn.execute(
                text("update user_strategies set source_code=:s, class_name=:c, "
                     "params_schema=cast(:p as jsonb), updated_at=now() where id=:id"),
                {"s": compiled.source_code,
                 "c": validation.class_name or compiled.class_name,
                 "p": json.dumps(validation.params_schema),
                 "id": r["id"]},
            )
            print(f"  UPDATED {r['name']!r}")
            updated += 1

        print(f"\nupdated={updated} unchanged={skipped} fallback/invalid={failed}")


if __name__ == "__main__":
    asyncio.run(main())
