# -*- mode: python ; coding: utf-8 -*-
import glob
import os

# Defaults match Debian/Ubuntu x86_64; override with VLC_LIB_DIR / VLC_PLUGINS_DIR.
vlc_lib_dir = os.environ.get('VLC_LIB_DIR', '/usr/lib/x86_64-linux-gnu')
vlc_plugins_dir = os.environ.get('VLC_PLUGINS_DIR', os.path.join(vlc_lib_dir, 'vlc', 'plugins'))

binaries = [
    (lib, '.')
    for pattern in ('libvlc.so.*', 'libvlccore.so.*')
    for lib in glob.glob(os.path.join(vlc_lib_dir, pattern))
]
if not binaries:
    raise SystemExit(f"No libvlc found in {vlc_lib_dir}; set VLC_LIB_DIR")

datas = [
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
