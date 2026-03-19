from __future__ import annotations

import os
from threading import Event
from typing import Callable, Optional


from app.logic.payload_dumper import extract as _extract_payload


class PayloadExtractor:
    """Shared payload.bin extractor wrapper.

    统一走项目内置的 Python 解包实现（app.logic.payload_dumper）。
    这样调试环境与打包后都无需依赖外部 exe，也无需特殊的 python 启动参数。
    """

    def __init__(self, log_callback: Callable[[str], None], step_start: Optional[Callable[[str, str], None]] = None, step_finish: Optional[Callable[[str, bool, str], None]] = None):
        self.log = log_callback
        self.step_start = step_start
        self.step_finish = step_finish
        self._cancel = Event()

    def stop(self):
        self._cancel.set()

    def extract(self, source: str, output_dir: str, partitions: str = "") -> bool:
        source = str(source)
        output_dir = str(output_dir)
        partitions = (partitions or "").strip()

        os.makedirs(output_dir, exist_ok=True)

        if self._cancel.is_set():
            return False

        return _extract_payload(
            source,
            output_dir,
            partitions,
            log_callback=self.log,
            step_start=self.step_start,
            step_finish=self.step_finish,
            cancel_event=self._cancel,
        )
