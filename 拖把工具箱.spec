# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('android-chrome-512x512.png', '.'), ('android-chrome-512x512.ico', '.'), ('app', 'app'), ('bin', 'bin')]
binaries = []
hiddenimports = []
datas += collect_data_files('qfluentwidgets')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtQml', 'PySide6.QtQml.*', 'PySide6.QtQuick',
        'PySide6.QtWebEngine', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick',
        'numpy', 'numpy.*', 'scipy', 'scipy.*',
        'PySide6.QtPdf', 'PySide6.QtVirtualKeyboard',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='拖把工具箱',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    hide_console='hide-early',
    icon='android-chrome-512x512.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='拖把工具箱',
)

# --- Post-processing: trim Qt translations and plugins to essentials ---
import os
from pathlib import Path

def _filter_qt_files(base_path: Path):
    # Remove unwanted Qt DLLs
    pyside_dir = base_path / '_internal' / 'PySide6'
    if pyside_dir.is_dir():
        unwanted_dlls = {
            'Qt6Qml.dll', 'Qt6QmlMeta.dll', 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll',
            'Qt6Quick.dll', 'Qt6Pdf.dll', 'Qt6VirtualKeyboard.dll',
        }
        for dll in pyside_dir.glob('Qt6*.dll'):
            if dll.name in unwanted_dlls:
                try:
                    dll.unlink()
                except Exception:
                    pass
    # Keep only zh_CN translations
    trans_dir = base_path / '_internal' / 'PySide6' / 'translations'
    if trans_dir.is_dir():
        for qm in trans_dir.glob('*.qm'):
            if not (qm.name.startswith('qtbase_zh_CN') or qm.name.startswith('qt_zh_CN')):
                try:
                    qm.unlink()
                except Exception:
                    pass
    # Keep only essential plugins
    plugins_dir = base_path / '_internal' / 'PySide6' / 'plugins'
    if plugins_dir.is_dir():
        # Remove entire plugin categories except those we need
        keep_dirs = {'platforms', 'imageformats'}
        for entry in plugins_dir.iterdir():
            if entry.is_dir() and entry.name not in keep_dirs:
                try:
                    import shutil
                    shutil.rmtree(entry)
                except Exception:
                    pass
        # In imageformats, keep only ico/jpeg/png
        img_dir = plugins_dir / 'imageformats'
        if img_dir.is_dir():
            keep_files = {'qico.dll', 'qjpeg.dll', 'qpng.dll'}
            for dll in img_dir.glob('*.dll'):
                if dll.name not in keep_files:
                    try:
                        dll.unlink()
                    except Exception:
                        pass

# Run the filter after COLLECT
_filter_qt_files(Path(os.getcwd()))
