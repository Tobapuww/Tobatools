from __future__ import annotations

import os
from threading import Lock


class MTIOBase:
    def read(self, off: int, size: int) -> bytes:
        raise NotImplementedError

    def readinto(self, off: int, size: int, ba) -> int:
        raise NotImplementedError

    def write(self, off: int, content: bytes) -> int:
        raise NotImplementedError

    def get_size(self) -> int:
        raise NotImplementedError

    def set_size(self, size: int):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class MTFile(MTIOBase):
    def __init__(self, path: str, mode: str):
        # mode: 'r' 'rb' 'w' 'wb'
        if 'b' not in mode:
            mode = mode + 'b'
        self._f = open(path, mode)
        self._lock = Lock()

    def read(self, off: int, size: int) -> bytes:
        with self._lock:
            self._f.seek(off, os.SEEK_SET)
            return self._f.read(size)

    def readinto(self, off: int, size: int, ba) -> int:
        with self._lock:
            self._f.seek(off, os.SEEK_SET)
            return self._f.readinto(ba)

    def write(self, off: int, content: bytes) -> int:
        with self._lock:
            self._f.seek(off, os.SEEK_SET)
            return self._f.write(content)

    def get_size(self) -> int:
        with self._lock:
            cur = self._f.tell()
            self._f.seek(0, os.SEEK_END)
            sz = self._f.tell()
            self._f.seek(cur, os.SEEK_SET)
            return sz

    def set_size(self, size: int):
        with self._lock:
            self._f.truncate(size)

    def close(self):
        with self._lock:
            try:
                self._f.close()
            except Exception:
                pass
