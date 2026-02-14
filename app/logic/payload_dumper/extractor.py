from __future__ import annotations

import os
from multiprocessing import cpu_count
from threading import Event
from typing import Callable, Optional

from .dumper_core import DumperCore
from . import mtio
from .http_file import HttpRangeFileMTIO


def extract(
    source_path: str,
    out_dir: str,
    partitions: str = "",
    *,
    workers: Optional[int] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[Event] = None,
) -> bool:
    """Extract images from payload.bin or OTA zip containing payload.bin.

    - source_path: payload.bin 或包含 payload.bin 且 payload.bin 为 stored 的 OTA.zip
    - partitions: "boot,dtbo" 或 ""（全量）
    - cancel_event: 取消信号（置位后尽快停止）
    """

    if log_callback is None:
        def log_callback(_msg: str):
            return

    if cancel_event is None:
        cancel_event = Event()

    if workers is None:
        workers = max(1, cpu_count())

    os.makedirs(out_dir, exist_ok=True)

    payload_file = None
    try:
        if source_path.startswith('http://') or source_path.startswith('https://'):
            payload_file = HttpRangeFileMTIO(source_path)
        else:
            payload_file = mtio.MTFile(source_path, 'r')

        dumper = DumperCore(
            payload_file=payload_file,
            out_dir=out_dir,
            partitions=partitions,
            workers=workers,
            log_callback=log_callback,
            cancel_event=cancel_event,
        )
        dumper.run()
        return not cancel_event.is_set()
    finally:
        try:
            if payload_file is not None:
                payload_file.close()
        except Exception:
            pass
