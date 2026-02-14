from __future__ import annotations

import io
from threading import Lock
from typing import Optional

import httpx

from . import mtio


class HttpRangeFileMTIO(mtio.MTIOBase):
    """MTIO implementation backed by HTTP Range requests."""

    def __init__(self, url: str, *, max_retry: int = 10, headers: Optional[dict] = None):
        self.url = url
        self.max_retry = max_retry
        self.client = httpx.Client(headers=headers)
        self.lock = Lock()
        self.transferred_bytes = 0

        h = self.client.head(url)
        if h.headers.get('Accept-Ranges', 'none') != 'bytes':
            raise ValueError(f"Remote does not support ranges: {url}")
        size = int(h.headers.get('Content-Length', 0))
        if size <= 0:
            raise ValueError(f"Remote has no length: {url}")
        self.size = size

    def read(self, off: int, size: int) -> bytes:
        if self.closed():
            raise ValueError('closed!')
        ba = bytearray(size)
        n = self.readinto(off, size, ba)
        return bytes(ba[:n])

    def readinto(self, off: int, size: int, ba) -> int:
        if self.closed():
            raise ValueError('closed!')
        if size == 0:
            return 0

        end_pos = min(off + size - 1, self.size - 1)
        expected_size = end_pos - off + 1
        received = 0
        retry_count = 0

        while received < expected_size:
            headers = {"Range": f"bytes={off + received}-{end_pos}"}
            try:
                with self.client.stream('GET', self.url, headers=headers) as r:
                    if r.status_code != 206:
                        raise io.UnsupportedOperation(
                            f"Remote did not return partial content: {self.url} {r.status_code}"
                        )
                    for chunk in r.iter_bytes(8192):
                        ba[received : received + len(chunk)] = chunk
                        received += len(chunk)
                        with self.lock:
                            self.transferred_bytes += len(chunk)
            except httpx.ConnectTimeout as e:
                retry_count += 1
                if retry_count >= self.max_retry:
                    raise e
        return received

    def write(self, off: int, content: bytes) -> int:
        raise NotImplementedError

    def get_size(self) -> int:
        return int(self.size)

    def set_size(self, size: int):
        raise NotImplementedError

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    def closed(self) -> bool:
        try:
            return self.client.is_closed
        except Exception:
            return True
