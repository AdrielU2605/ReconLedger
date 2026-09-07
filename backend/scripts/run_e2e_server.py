"""Boots the real API against a throwaway SQLite database, for Playwright's
webServer to drive. Never touches the developer's own reconledger.db.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def main() -> None:
    db_path = BACKEND_DIR / "e2e.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()

    env = os.environ.copy()
    env["RECONLEDGER_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    env["RECONLEDGER_WORKER_LOCK_PATH"] = str(BACKEND_DIR / "e2e-worker.lock")

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True
    )
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
