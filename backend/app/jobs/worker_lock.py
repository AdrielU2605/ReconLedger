"""9 Process model: the durable worker runs in-process, so exactly one worker
process may claim queued jobs. A second launch is rejected at startup unless
an external worker coordinator is explicitly configured (out of MVP scope).
"""
from __future__ import annotations

import os
from pathlib import Path


class WorkerAlreadyRunningError(RuntimeError):
    def __init__(self, lock_path: Path, holder_pid: int) -> None:
        super().__init__(
            f"Another ReconLedger worker (pid {holder_pid}) already holds {lock_path}. "
            "A multi-process launch would let two workers claim the same queued job. "
            "Set RECONLEDGER_EXTERNAL_WORKER_CONFIGURED=true only if an external "
            "worker coordinator is actually managing exclusivity."
        )
        self.lock_path = lock_path
        self.holder_pid = holder_pid


def _pid_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except AttributeError:
        # Platforms without os.kill signal-0 support: assume alive to be safe.
        return True
    return True


class WorkerLock:
    """A PID lock file guarding single-process worker exclusivity.

    Not a security boundary - a cooperative guard against accidentally
    launching a second `uvicorn` against the same database.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._acquired = False

    def acquire(self, *, external_worker_configured: bool) -> None:
        if external_worker_configured:
            return
        if self._lock_path.exists():
            try:
                holder_pid = int(self._lock_path.read_text().strip())
            except (ValueError, OSError):
                holder_pid = -1
            if holder_pid > 0 and _pid_is_alive(holder_pid):
                raise WorkerAlreadyRunningError(self._lock_path, holder_pid)
        self._lock_path.write_text(str(os.getpid()))
        self._acquired = True

    def release(self) -> None:
        if self._acquired and self._lock_path.exists():
            self._lock_path.unlink()
        self._acquired = False

    def __enter__(self) -> "WorkerLock":
        self.acquire(external_worker_configured=False)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
