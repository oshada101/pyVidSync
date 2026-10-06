import json
import os

import pytest

import settings


@pytest.fixture
def paths(tmp_path, monkeypatch):
    user_dir = tmp_path / "user"
    bundled = tmp_path / "bundled" / "settings.json"
    bundled.parent.mkdir()
    monkeypatch.setattr(settings, "_user_config_dir", lambda: str(user_dir))
    monkeypatch.setattr(settings, "_bundled_settings_path", lambda: str(bundled))
    monkeypatch.delenv("PARTYKIT_HOST", raising=False)
    return user_dir / "settings.json", bundled


def test_missing_files_give_empty(paths):
    assert settings.load_settings() == {}


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", "\"str\""])
def test_unreadable_file_ignored(paths, content):
    user, _ = paths
    user.parent.mkdir()
    user.write_text(content)
    assert settings.load_settings() == {}


def test_bundled_file_is_fallback(paths):
    user, bundled = paths
    bundled.write_text(json.dumps({"partykit_host": "bundled.dev"}))
    assert settings.resolve_host() == "bundled.dev"
    settings.save_settings({"partykit_host": "mine.dev"})
    assert settings.resolve_host() == "mine.dev"
    assert json.loads(bundled.read_text()) == {"partykit_host": "bundled.dev"}  # never written


def test_save_merges_and_none_removes(paths):
    user, _ = paths
    settings.save_settings({"partykit_host": "a.dev", "other": 1})
    settings.save_settings({"partykit_host": None})
    assert json.loads(user.read_text()) == {"other": 1}
    assert not os.path.exists(str(user) + ".tmp")


def test_env_var_wins(paths, monkeypatch):
    settings.save_settings({"partykit_host": "file.dev"})
    monkeypatch.setenv("PARTYKIT_HOST", " env.dev ")
    assert settings.resolve_host() == "env.dev"
    monkeypatch.setenv("PARTYKIT_HOST", "  ")
    assert settings.resolve_host() == "file.dev"


def test_save_error_propagates(paths, monkeypatch):
    def boom(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(settings.os, "makedirs", boom)
    with pytest.raises(OSError):
        settings.save_settings({"partykit_host": "x.dev"})
