from pathlib import Path
from PySide6.QtWidgets import QApplication
from typing import Literal

try:
    import winreg  # Windows-only
except Exception:  # pragma: no cover
    winreg = None

try:
    from qfluentwidgets import isDarkTheme as _is_dark_theme
except Exception:  # pragma: no cover
    _is_dark_theme = None

ThemeMode = Literal["system", "light", "dark"]

_DARK_OVERLAY = """
CardWidget { background-color: #1f1f1f; }
QDialog { background-color: #202020; color: #ffffff; }
QLabel,
QTextEdit,
QPlainTextEdit,
QTextBrowser,
QLineEdit,
QListWidget,
QListView,
QTreeWidget,
QTreeView,
QTableWidget,
QTableView {
    color: #ffffff;
}
"""

_LIGHT_OVERLAY = """
QWidget { color: #111111; }
CardWidget { color: #111111; }
QLabel,
QTextEdit,
QPlainTextEdit,
QTextBrowser,
QLineEdit,
QListWidget,
QListView,
QTreeWidget,
QTreeView,
QTableWidget,
QTableView {
    color: #111111;
}
QDialog { color: #111111; }
"""


def _load_qss(app: QApplication, qss_path: Path, fallback_dark: bool = False):
    if qss_path.exists():
        css = qss_path.read_text(encoding="utf-8")
        if css:
            app.setStyleSheet(css)
            return
    # fallback
    if fallback_dark:
        app.setStyleSheet("QWidget { background:#121212; color:#E6E1E5; }")
    else:
        app.setStyleSheet("QWidget { background:#FFFFFF; color:#1D1B20; }")


def detect_windows_theme() -> Literal["light", "dark"]:
    """Read Windows AppsUseLightTheme: 1=light, 0=dark. Default to light if unavailable."""
    try:
        if winreg is None:
            return "light"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if int(val) == 1 else "dark"
    except Exception:
        return "light"


def apply_theme(app: QApplication, mode: ThemeMode = "system"):
    base = Path(__file__).resolve().parent
    if mode == "system":
        sys_mode = detect_windows_theme()
        qss = base / "assets" / ("md3_light.qss" if sys_mode == "light" else "md3_dark.qss")
        _load_qss(app, qss, fallback_dark=(sys_mode == "dark"))
    elif mode == "light":
        qss = base / "assets" / "md3_light.qss"
        _load_qss(app, qss, fallback_dark=False)
    else:  # dark
        qss = base / "assets" / "md3_dark.qss"
        _load_qss(app, qss, fallback_dark=True)


def apply_runtime_overlay(app: QApplication | None, fallback_dark: bool = False):
    """Apply a lightweight stylesheet overlay so text colors match the current theme."""
    if app is None:
        return
    try:
        is_dark = bool(_is_dark_theme()) if _is_dark_theme else fallback_dark
    except Exception:
        is_dark = fallback_dark
    app.setStyleSheet(_DARK_OVERLAY if is_dark else _LIGHT_OVERLAY)


# Backward compatibility shim
def load_md3_theme(app: QApplication):
    apply_theme(app, "dark")
