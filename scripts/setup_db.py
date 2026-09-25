"""One-time Supabase setup: create the civic_data table + seed sample rows.

Usage (from project root, venv activated, .env configured):

    python scripts/setup_db.py
"""
import sys
from pathlib import Path

# Allow running as a script from anywhere: add project root to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database import ensure_schema, seed_demo_records  # noqa: E402


def main() -> int:
    print("CityPulse database setup")
    print("-" * 40)

    ok, err = ensure_schema()
    if not ok:
        print(f"FAILED to create schema: {err}")
        print("Check DATABASE_URL in .env (password URL-encoded, e.g. @ -> %40).")
        return 1
    print("OK: civic_data table + indexes ready")

    ok, err = seed_demo_records()
    if not ok:
        print(f"FAILED to seed demo rows: {err}")
        return 1
    print("OK: sample rows seeded (idempotent — safe to re-run)")

    print("\nDone. The dashboard will now read from Supabase when reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
