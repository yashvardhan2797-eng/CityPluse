"""Apply SQL migrations in filename order, tracked in schema_migrations.

Usage (venv active, DATABASE_URL configured):
    python scripts/apply_migrations.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database import get_connection  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name       TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def main() -> int:
    print("CityPulse migration runner")
    print("-" * 40)

    files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("No migration files found.")
        return 0

    # NOTE: psycopg3 closes the connection when its `with` block exits,
    # so all work (including commit) happens inside the block.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(TRACKING_TABLE)
            for name in files:
                cur.execute("SELECT 1 FROM schema_migrations WHERE name = %s", (name,))
                if cur.fetchone():
                    print(f"SKIP (already applied): {name}")
                    continue
                sql = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
                print(f"APPLY: {name}")
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
        conn.commit()

    print("\nDone: schema is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
