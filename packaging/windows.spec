# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

block_cipher = None

# In PyInstaller .spec, __file__ may be undefined. Use CWD as project root.
project_root = Path(os.getcwd()).resolve()
app_entry = str(project_root / 'app' / 'main.py')

# Minimal binaries: include local adb/fastboot if present to avoid system dependency
bin_dir = project_root / 'bin'
extra_binaries = []
for name in ('fastboot.exe', 'adb.exe'):
    p = bin_dir / name
    if p.exists():
        # (src, target_dir)
        extra_binaries.append((str(p), 'bin'))

# Extra datas: rely on default PySide6 hooks for plugins
extra_datas = []

# Do not exclude modules to keep runtime identical to dev environment
excludes = []

hiddenimports = []

a = Analysis(
    [app_entry],
    pathex=[str(project_root)],
    binaries=extra_binaries,
    datas=extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OnePlusAceProTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OnePlusAceProTool'
)
