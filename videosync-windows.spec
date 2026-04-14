# -*- mode: python ; coding: utf-8 -*-
import os

vlc_dir = os.environ.get('VLC_DIR', r'C:\Program Files\VideoLAN\VLC')
vlc_plugins_dir = os.path.join(vlc_dir, 'plugins')

binaries = [
    (os.path.join(vlc_dir, 'libvlc.dll'), '.'),
    (os.path.join(vlc_dir, 'libvlccore.dll'), '.'),
    (os.path.join(vlc_dir, 'axvlc.dll'), '.'),
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
