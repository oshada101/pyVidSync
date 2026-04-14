# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

vlc_lib_dir = '/usr/lib/x86_64-linux-gnu'
vlc_plugins_dir = '/usr/lib/x86_64-linux-gnu/vlc/plugins'

binaries = [
    (os.path.join(vlc_lib_dir, 'libvlc.so.5'), '.'),
    (os.path.join(vlc_lib_dir, 'libvlccore.so.9'), '.'),
]

datas = [
    ('.env', '.'),
    (vlc_plugins_dir, 'vlc_plugins'),
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'vlc',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'websockets.legacy.server',
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
