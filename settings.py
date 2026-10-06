import json
import logging
import os
import sys

log = logging.getLogger(__name__)

APP_DIR_NAME = "VideoSync"
SETTINGS_FILE = "settings.json"


def _user_config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_DIR_NAME)


def _bundled_settings_path() -> str:
    """settings.json shipped next to the executable (frozen) or the source tree (dev). Read-only fallback."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, SETTINGS_FILE)


def get_settings_path() -> str:
    return os.path.join(_user_config_dir(), SETTINGS_FILE)


def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable settings file %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        log.warning("Ignoring settings file %s: expected a JSON object", path)
        return None
    return data


def load_settings() -> dict:
    for path in (get_settings_path(), _bundled_settings_path()):
        data = _read(path)
        if data is not None:
            return data
    return {}


def save_settings(updates: dict) -> None:
    """Merge `updates` into the user settings file; a value of None removes the key. Raises OSError."""
    data = load_settings()
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def resolve_host() -> str | None:
    if val := os.environ.get("PARTYKIT_HOST", "").strip():
        return val
    return load_settings().get("partykit_host") or None
