import os
import sys

# Point libvlc at the bundled plugins, if any; on Windows also at the bundled DLLs.
# os.add_dll_directory and libvlc.dll exist only on Windows.
if hasattr(sys, '_MEIPASS'):
    meipass = sys._MEIPASS
    bundled_plugins = os.path.join(meipass, 'vlc_plugins')
    if os.path.isdir(bundled_plugins):  # Linux builds use the system VLC and its own plugins
        os.environ['VLC_PLUGIN_PATH'] = bundled_plugins
    if sys.platform == "win32":
        os.add_dll_directory(meipass)
        os.environ['PATH'] = meipass + os.pathsep + os.environ.get('PATH', '')
        os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(meipass, 'libvlc.dll')
