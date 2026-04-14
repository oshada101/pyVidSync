import os
import sys

if hasattr(sys, '_MEIPASS'):
    os.environ['VLC_PLUGIN_PATH'] = os.path.join(sys._MEIPASS, 'vlc_plugins')
