# -*- mode: python ; coding: utf-8 -*-

import os
import sys

# 部分精简 Python（如 Codex 内置运行时）不会被 PyInstaller 自动收集 Tcl/Tk，
# 这里显式打包 tkinter 依赖，保证 GUI exe 能启动。
_py_home = sys.base_prefix
_tk_binaries = []
for _name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
    _path = os.path.join(_py_home, "DLLs", _name)
    if os.path.exists(_path):
        _tk_binaries.append((_path, "."))
_tk_datas = []
_tcl_dir = os.path.join(_py_home, "tcl")
if os.path.isdir(_tcl_dir):
    _tk_datas.append((_tcl_dir, "tcl"))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_tk_binaries,
    datas=[('assets/icon.ico', 'assets')] + _tk_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TXT_Catcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)
