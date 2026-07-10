"""One-shot database setup — runs schema.sql against Supabase.

Usage:
    python -m db.setup
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from db.supabase_client import get_client


async def main() -> None:
    schema = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    client = await get_client()
    statements = [s.strip() for s in schema.split(";") if s.strip()]
    errors: list[str] = []
    for stmt in statements:
        try:
            await client.rpc("exec_sql", {"sql": stmt}).execute()
        except Exception as e:
            err = str(e)
            # supabase-py raises on unknown RPC — fall back to raw postgrest
            if "exec_sql" in err:
                # Supabase free tier: paste schema.sql manually in the SQL editor
                print("NOTE: Supabase free tier doesn't support exec_sql RPC.")
                print("Paste db/schema.sql into the Supabase SQL editor instead.")
                sys.exit(1)
            errors.append(f"{e!r}\nSQL: {stmt[:120]}")

    if errors:
        print(f"Setup completed with {len(errors)} error(s):")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("Database setup complete.")


if __name__ == "__main__":
    asyncio.run(main())
