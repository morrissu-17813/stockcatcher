from __future__ import annotations

import os
from pathlib import Path


class SingleInstanceLock:
    """Small cross-platform process lock using atomic file creation."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                owner = self.path.read_text(encoding="utf-8")
            except OSError:
                owner = "unknown"
            pid = None
            for line in owner.splitlines():
                if line.startswith("pid="):
                    try:
                        pid = int(line.split("=", 1)[1])
                    except ValueError:
                        pass
            alive = False
            if pid and pid != os.getpid():
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    alive = False
            if not alive:
                self.path.unlink(missing_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(f"pid={os.getpid()}\n")
                self.acquired = True
                return
            raise RuntimeError(f"TIANJI_ALREADY_RUNNING: {owner[:200]}")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}\n")
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.path.unlink(missing_ok=True)
        finally:
            self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
