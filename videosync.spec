# -*- mode: python ; coding: utf-8 -*-
import os

# Linux build uses the system VLC (`apt install vlc`) instead of bundling it: bundled libvlc
# plugins link against the build distro's codec libraries and break on other distro versions.
binaries = []
datas = []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'vlc',
        'websockets',
        'websockets.asyncio.client',
        'dotenv',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_vlc.py'],
    excludes=[],
    noarchive=False,
)

# PyInstaller auto-collects libvlc via python-vlc; drop it so the system libvlc and its plugins match.
a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).startswith(('libvlc.so', 'libvlccore.so'))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='videosync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='videosync',
)
