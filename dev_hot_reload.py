import os
import subprocess
import sys
import time
from pathlib import Path


WATCH_DIRS = [Path(__file__).resolve().parent / "app"]
WATCH_EXTS = {".py", ".json", ".qss", ".ui"}
POLL_INTERVAL = 0.5
DEBOUNCE_SECONDS = 0.6


def _iter_watch_files() -> list[Path]:
    files: list[Path] = []
    for d in WATCH_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in WATCH_EXTS:
                continue
            files.append(p)
    return files


def _snapshot_mtimes(files: list[Path]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in files:
        try:
            out[str(p)] = p.stat().st_mtime
        except OSError:
            continue
    return out


def _has_changes(prev: dict[str, float], cur: dict[str, float]) -> bool:
    if prev.keys() != cur.keys():
        return True
    for k, v in cur.items():
        if prev.get(k) != v:
            return True
    return False


def _start_app() -> subprocess.Popen:
    cmd = [sys.executable, "-m", "app.main"]
    return subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent))


def _stop_app(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    try:
        p.terminate()
    except Exception:
        pass

    try:
        p.wait(timeout=3)
        return
    except Exception:
        pass

    try:
        p.kill()
    except Exception:
        pass


def main() -> int:
    print("[hot-reload] watching:")
    for d in WATCH_DIRS:
        print(f"  - {d}")
    print("[hot-reload] start app: python -m app.main")

    watched = _iter_watch_files()
    mtimes = _snapshot_mtimes(watched)

    proc = _start_app()

    last_change_at = 0.0
    try:
        while True:
            time.sleep(POLL_INTERVAL)

            # refresh file list occasionally to pick up new files
            watched = _iter_watch_files()
            cur = _snapshot_mtimes(watched)

            if _has_changes(mtimes, cur):
                now = time.time()
                mtimes = cur
                last_change_at = now

            # debounce restart
            if last_change_at and (time.time() - last_change_at) >= DEBOUNCE_SECONDS:
                last_change_at = 0.0
                print("[hot-reload] change detected -> restarting...")
                _stop_app(proc)
                proc = _start_app()

            # if app exited, restart (useful after crash)
            if proc.poll() is not None:
                code = proc.returncode
                print(f"[hot-reload] app exited (code={code}) -> restarting...")
                proc = _start_app()

    except KeyboardInterrupt:
        print("\n[hot-reload] stopping...")
        _stop_app(proc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
