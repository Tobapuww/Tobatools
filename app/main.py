from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt, QCoreApplication, QSettings
from PySide6.QtGui import QIcon
import sys
import traceback
import faulthandler

from app.ui.disclaimer import DisclaimerDialog
from app.ui.fluent_main_window import FluentMainWindow
from app.ui.theme import apply_runtime_overlay
from qfluentwidgets import Theme, setTheme, setThemeColor


def main():
    # 在 PyInstaller --windowed 模式下，sys.stderr 可能为 None
    # 需要先检查再启用 faulthandler
    if sys.stderr is not None:
        try:
            faulthandler.enable()
        except Exception:
            pass
    
    app = QApplication(sys.argv)
    app.setApplicationName("拖把工具箱")
    QCoreApplication.setOrganizationName("OnePlusTools")
    QCoreApplication.setOrganizationDomain("oneplus.local")
    root_dir = Path(__file__).resolve().parents[1]
    icon_path = root_dir / "android-chrome-512x512.png"
    app_icon = None
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
    # 使用 QFluentWidgets 主题（跟随设置：system/light/dark）
    settings = QSettings()
    mode = settings.value("theme/mode", "system")
    if mode == "light":
        setTheme(Theme.LIGHT)
    elif mode == "dark":
        setTheme(Theme.DARK)
    else:
        # AUTO 会跟随系统浅/深色
        try:
            auto = getattr(Theme, "AUTO", Theme.LIGHT)
            setTheme(auto)
        except Exception:
            setTheme(Theme.LIGHT)
    setThemeColor('#2A74DA')

    # 应用运行时覆盖，修正浅/深色模式下的字体可读性
    apply_runtime_overlay(app, fallback_dark=(mode == "dark"))

    try:
        # Disclaimer
        dlg = DisclaimerDialog()
        if dlg.exec() != QDialog.Accepted:
            sys.exit(0)

        window = FluentMainWindow()
    except Exception:
        traceback.print_exc()
        raise
    if app_icon is not None:
        try:
            window.setWindowIcon(app_icon)
        except Exception:
            pass
    try:
        scr = app.primaryScreen()
        geo = scr.availableGeometry() if scr else None
        if geo:
            w = int(min(1180, max(900, geo.width() * 0.75)))
            h = int(min(740, max(560, geo.height() * 0.60)))
            window.resize(w, h)
            # center
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + (geo.height() - h) // 2
            window.move(x, y)
        else:
            window.resize(1000, 700)
    except Exception:
        window.resize(1000, 700)
    window.show()
    try:
        sys.exit(app.exec())
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
