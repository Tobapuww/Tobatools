import os, sys

def _runtime_base():
    # When frozen by PyInstaller, sys._MEIPASS points to extracted dir
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return base
    # Fallback to current file directory
    return os.path.dirname(os.path.abspath(__file__))

# Ensure packaged 'app' (obfuscated) is importable both in dev and frozen
BASE = _runtime_base()
CANDIDATES = [
    BASE,
    os.path.join(BASE, "app"),
]
for p in CANDIDATES:
    if p and os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from app.main import main
except Exception:
    # Try plain path (dev fallback)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "build", "obf"))
    from app.main import main

if __name__ == "__main__":
    main()
