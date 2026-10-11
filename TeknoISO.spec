# -*- mode: python ; coding: utf-8 -*-
"""Especificación PyInstaller de TeknoISO (ejecutable de un solo archivo).

Antes de compilar, genera el icono:

    python assets/make_icon.py

Compilar:

    pyinstaller TeknoISO.spec

El ejecutable queda en dist/TeknoISO.exe.
"""

import os

ICONO = os.path.join("assets", "TeknoISO.ico")
if not os.path.exists(ICONO):
    raise SystemExit("Falta assets/TeknoISO.ico — ejecuta primero: python assets/make_icon.py")

a = Analysis(
    ["tekno_iso.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TeknoISO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONO,
)
