from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from app.logic.payload_extractor import PayloadExtractor


class OJZPackageLoader:
    def __init__(
        self,
        log_callback: Callable[[str], None],
        step_start: Optional[Callable[[str, str], None]] = None,
        step_finish: Optional[Callable[[str, bool, str], None]] = None,
    ):
        self.log = log_callback
        self.step_start = step_start
        self.step_finish = step_finish
        self._extractor: Optional[PayloadExtractor] = None

    def stop(self):
        try:
            if self._extractor is not None:
                self._extractor.stop()
        except Exception:
            pass

    @staticmethod
    def free_space_bytes(folder: str) -> int:
        usage = shutil.disk_usage(folder)
        return int(usage.free)

    @staticmethod
    def count_partition_images(folder: str) -> int:
        p = Path(folder)
        if not p.exists():
            return 0
        return sum(1 for f in p.glob('*.img'))

    def extract_all_from_ota(self, ota_path: str, out_dir: str) -> bool:
        self._extractor = PayloadExtractor(
            log_callback=self.log,
            step_start=self.step_start,
            step_finish=self.step_finish,
        )
        try:
            return self._extractor.extract(ota_path, out_dir, partitions="")
        finally:
            self._extractor = None
