from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt, QCoreApplication, QSettings, QTimer
from PySide6.QtGui import QIcon
import sys
import traceback
import faulthandler

from app.ui.disclaimer import DisclaimerDialog
from app.ui.fluent_main_window import FluentMainWindow
from app.ui.startup_splash import StartupSplash
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
    QCoreApplication.setOrganizationName("tobapuwTools")
    QCoreApplication.setOrganizationDomain("tobapuw.local")
    root_dir = Path(__file__).resolve().parents[1]
    icon_path = root_dir / "android-chrome-512x512.png"
    disclaimer_marker = root_dir / ".disclaimer_accepted"
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

    splash = None
    try:
        # Disclaimer
        disclaimer_ok = False
        try:
            if disclaimer_marker.exists():
                disclaimer_ok = True
        except Exception:
            disclaimer_ok = False

        if not disclaimer_ok:
            try:
                if settings.value("disclaimer/accepted", False) in (True, "true", "1", 1):
                    disclaimer_ok = True
            except Exception:
                disclaimer_ok = False

        if not disclaimer_ok:
            dlg = DisclaimerDialog()
            if dlg.exec() != QDialog.Accepted:
                sys.exit(0)
            # mark accepted
            try:
                disclaimer_marker.write_text("accepted=1\n", encoding="utf-8")
            except Exception:
                try:
                    settings.setValue("disclaimer/accepted", True)
                except Exception:
                    pass

        splash = StartupSplash(icon_path=str(icon_path) if icon_path.exists() else "", light=True)
        if app_icon is not None:
            try:
                splash.setWindowIcon(app_icon)
            except Exception:
                pass
        try:
            splash.set_status("正在部署运行环境")
            splash.center_on_screen()
            splash.show()
        except Exception:
            pass

        try:
            QTimer.singleShot(300, lambda: splash.set_status("正在加载依赖") if splash else None)
            QTimer.singleShot(900, lambda: splash.set_status("正在加载UI界面") if splash else None)
        except Exception:
            pass

        window = FluentMainWindow(eager_load=True)
        try:
            window.hide()
        except Exception:
            pass
    except Exception:
        try:
            if splash is not None:
                splash.close()
        except Exception:
            pass
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
    splash_shown_at = None
    try:
        import time

        splash_shown_at = time.time() if splash is not None else None
    except Exception:
        splash_shown_at = None

    _startup_finished = False

    def _finish_startup():
        nonlocal _startup_finished
        if _startup_finished:
            return
        try:
            import time

            if splash is not None and splash_shown_at is not None:
                # Ensure user can perceive the animation
                min_show = 2.5
                elapsed = time.time() - float(splash_shown_at)
                if elapsed < min_show:
                    QTimer.singleShot(int((min_show - elapsed) * 1000), _finish_startup)
                    return
        except Exception:
            pass

        _startup_finished = True
        try:
            if splash is not None:
                try:
                    splash.set_status("正在启动")
                except Exception:
                    pass
        except Exception:
            pass

        try:
            window.show()
        except Exception:
            pass

        try:
            if splash is not None:
                try:
                    splash.fade_out_and_close(duration_ms=220)
                except Exception:
                    splash.close()
        except Exception:
            pass

    try:
        window.initialized.connect(_finish_startup)
    except Exception:
        pass

    # fallback in case initialized signal is not emitted
    try:
        QTimer.singleShot(5000, _finish_startup)
    except Exception:
        pass

    try:
        sys.exit(app.exec())
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
