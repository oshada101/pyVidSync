import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# python-vlc needs a system libvlc at import time; SyncApp tests use a fake player instead.
if "vlc" not in sys.modules:
    try:
        import vlc  # noqa: F401
    except (ImportError, OSError, NameError):
        sys.modules["vlc"] = types.ModuleType("vlc")


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
