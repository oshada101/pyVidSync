import os
import sys

# Point libvlc at the bundled plugins; on Windows also at the bundled DLLs.
# os.add_dll_directory and libvlc.dll exist only on Windows.
if hasattr(sys, '_MEIPASS'):
    meipass = sys._MEIPASS
    os.environ['VLC_PLUGIN_PATH'] = os.path.join(meipass, 'vlc_plugins')
    if sys.platform == "win32":
        os.add_dll_directory(meipass)
        os.environ['PATH'] = meipass + os.pathsep + os.environ.get('PATH', '')
        os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(meipass, 'libvlc.dll')
