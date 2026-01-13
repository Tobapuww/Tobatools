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
    # Support for multiprocessing in frozen apps (payload_dumper uses it)
    import multiprocessing
    multiprocessing.freeze_support()

    # Sub-command dispatch for payload-dumper
    if len(sys.argv) > 1 and sys.argv[1] == '--payload-dumper':
        import runpy
        # Remove the flag so payload_dumper receives correct arguments
        sys.argv.pop(1)
        try:
            # Execute payload_dumper as if run with python -m payload_dumper
            runpy.run_module('payload_dumper', run_name='__main__', alter_sys=True)
        except SystemExit:
            pass
        except Exception as e:
            print(f"Error executing payload_dumper: {e}", file=sys.stderr)
        sys.exit(0)

    main()
