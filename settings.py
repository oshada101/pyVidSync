import json
import os
import sys

def get_settings_path() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "settings.json")


def load_settings() -> dict:
    path = get_settings_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_settings(data: dict):
    path = get_settings_path()
    existing = load_settings()
    existing.update(data)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)


def resolve_host() -> str | None:
    if val := os.environ.get("PARTYKIT_HOST"):
        return val
    return load_settings().get("partykit_host") or None
