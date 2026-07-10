"""Apply incremental schema migrations to the Supabase DB."""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS = [
    # Add customer_id to opportunities so each agency sees only their own
    """
    ALTER TABLE opportunities
    ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id);
    """,
    # Create index for the new column
    """
    CREATE INDEX IF NOT EXISTS idx_opportunities_customer
    ON opportunities(customer_id);
    """,
    # Rename slack_webhook -> slack_webhook_url (add new column, keep old for safety)
    """
    ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS slack_webhook_url TEXT;
    """,
    # Copy existing data from old column to new column
    """
    UPDATE customers
    SET slack_webhook_url = slack_webhook
    WHERE slack_webhook IS NOT NULL AND slack_webhook_url IS NULL;
    """,
]


async def run_migrations():
    from supabase import acreate_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    client = await acreate_client(url, key)
    for i, sql in enumerate(MIGRATIONS, 1):
        sql = sql.strip()
        print(f"[{i}/{len(MIGRATIONS)}] Running: {sql[:60]}…")
        try:
            res = await client.rpc("exec_sql", {"sql": sql}).execute()
            print(f"  OK: {res}")
        except Exception as e:
            # Try via postgrest directly
            print(f"  rpc failed ({e}), trying raw query…")
            try:
                # Use the REST API directly
                import httpx
                headers = {
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient() as http:
                    resp = await http.post(
                        f"{url}/rest/v1/rpc/exec_sql",
                        json={"sql": sql},
                        headers=headers,
                        timeout=30,
                    )
                    print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e2:
                print(f"  Both methods failed: {e2}")


if __name__ == "__main__":
    asyncio.run(run_migrations())
