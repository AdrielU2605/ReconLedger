import os
from pathlib import Path

import pytest

from app.jobs.worker_lock import WorkerAlreadyRunningError, WorkerLock


def test_lock_is_acquired_and_released(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"
    lock = WorkerLock(lock_path)
    lock.acquire(external_worker_configured=False)
    assert lock_path.exists()
    assert lock_path.read_text().strip() == str(os.getpid())
    lock.release()
    assert not lock_path.exists()


def test_second_acquire_by_a_live_process_is_refused(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"
    # Simulate a lock held by this same (definitely-alive) process's pid,
    # written by an earlier launch that never released it cleanly.
    lock_path.write_text(str(os.getpid()))

    lock = WorkerLock(lock_path)
    with pytest.raises(WorkerAlreadyRunningError):
        lock.acquire(external_worker_configured=False)


def test_stale_lock_from_a_dead_pid_is_reclaimed(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"
    # PID 999999 is extremely unlikely to be a live process on any test runner.
    lock_path.write_text("999999")

    lock = WorkerLock(lock_path)
    lock.acquire(external_worker_configured=False)
    assert lock_path.read_text().strip() == str(os.getpid())


def test_external_worker_configured_bypasses_the_lock_entirely(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text(str(os.getpid()))  # would normally refuse

    lock = WorkerLock(lock_path)
    lock.acquire(external_worker_configured=True)  # must not raise
