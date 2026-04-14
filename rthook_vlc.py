import os
import sys

if hasattr(sys, '_MEIPASS'):
    meipass = sys._MEIPASS
    os.add_dll_directory(meipass)
    os.environ['PATH'] = meipass + os.pathsep + os.environ.get('PATH', '')
    os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(meipass, 'libvlc.dll')
    os.environ['VLC_PLUGIN_PATH'] = os.path.join(meipass, 'vlc_plugins')
