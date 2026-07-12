"""Single-writer lock, released by the OS on ANY process death — stale locks
are structurally impossible (which is why this is an OS lock, not a pidfile).
The pid inside the file is advisory, for friendly messages only."""
from __future__ import annotations

import os


class Lock:
    def __init__(self, fd: int, path: str):
        self._fd = fd
        self.path = path

    def release(self) -> None:
        try:
            os.close(self._fd)            # closing the fd drops the OS lock
        except OSError:
            pass


def acquire(path: str) -> Lock | None:
    """Try to take the lock; None if another process (or fd) holds it."""
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    return Lock(fd, path)


def holder_pid(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip() or 0) or None
    except (OSError, ValueError):
        return None
