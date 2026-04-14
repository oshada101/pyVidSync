import os
import sys

if hasattr(sys, '_MEIPASS'):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
    os.environ['VLC_PLUGIN_PATH'] = os.path.join(sys._MEIPASS, 'vlc_plugins')
