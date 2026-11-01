import json

import pytest

import presets
from presets import (
    DEFAULT_GAME_PRESETS,
    export_presets_to_file,
    fetch_preset_targets,
    import_presets_from_file,
    is_valid_public_ip,
    load_history,
    load_sessions,
    save_to_history,
    search_app_hosts_online,
)


def test_is_valid_public_ip():
    assert is_valid_public_ip("8.8.8.8") is True
    assert is_valid_public_ip("1.1.1.1") is True

    assert is_valid_public_ip("127.0.0.1") is False
    assert is_valid_public_ip("192.168.1.1") is False
    assert is_valid_public_ip("10.0.0.1") is False
    assert is_valid_public_ip("invalid_ip") is False
    assert is_valid_public_ip("") is False


def test_fetch_preset_targets():
    discord_targets = fetch_preset_targets("Discord")
    assert isinstance(discord_targets, list)
    assert "discord.com" in discord_targets
    assert "discord.gg" in discord_targets

    # Регистр и частичное имя не должны мешать.
    assert "discord.com" in fetch_preset_targets("discord")
    assert fetch_preset_targets("Gemini") == DEFAULT_GAME_PRESETS["Gemini"]["domains"]

    assert fetch_preset_targets("NonExistentPreset") == []


def test_history_save_and_load(tmp_path, monkeypatch):
    history_file = tmp_path / "test_history.json"
    monkeypatch.setattr(presets, "HISTORY_FILE", str(history_file))

    save_to_history("TestApp", ["example.com", "test.org", "example.com"])
    loaded = load_history()

    assert loaded["TestApp"] == ["example.com", "test.org"]


def test_legacy_history_is_migrated(tmp_path, monkeypatch):
    history_file = tmp_path / "legacy.json"
    history_file.write_text(
        json.dumps({"Telegram": ["t.me", "telegram.org"]}), encoding="utf-8"
    )
    monkeypatch.setattr(presets, "HISTORY_FILE", str(history_file))

    assert load_history()["Telegram"] == ["t.me", "telegram.org"]

    save_to_history("Steam", ["steamcommunity.com"])
    raw = json.loads(history_file.read_text(encoding="utf-8"))
    assert raw["presets"]["Steam"] == ["steamcommunity.com"]
    assert raw["presets"]["Telegram"] == ["t.me", "telegram.org"]
    assert raw["sessions"] == []


def test_sessions_are_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "HISTORY_FILE", str(tmp_path / "history.json"))

    record = {
        "timestamp": "2026-01-01T00:00:00",
        "strategy_file": "general (ALT11).bat",
        "params": {"desync_mode": "split"},
        "target_hosts": ["youtube.com"],
        "passed_count": 1,
        "total_count": 1,
        "success": True,
    }
    presets.add_session(record)

    sessions = load_sessions()
    assert len(sessions) == 1
    assert sessions[0]["params"] == {"desync_mode": "split"}


def test_export_and_import_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "HISTORY_FILE", str(tmp_path / "history.json"))
    target = tmp_path / "domains.json"

    assert export_presets_to_file(str(target), ["youtube.com", "discord.com", "youtube.com"])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["Экспорт"]["domains"] == ["youtube.com", "discord.com"]

    imported = import_presets_from_file(str(target))
    assert imported == ["youtube.com", "discord.com"]


def test_import_plain_text_file(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "HISTORY_FILE", str(tmp_path / "history.json"))
    source = tmp_path / "domains.txt"
    source.write_text("# comment\nyoutube.com\ninvalid_ip\n\nt.me\n", encoding="utf-8")

    assert import_presets_from_file(str(source)) == ["youtube.com", "t.me"]


def test_search_by_domain_and_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "HISTORY_FILE", str(tmp_path / "history.json"))

    hosts = search_app_hosts_online("https://example.com/path")
    assert hosts == ["example.com", "www.example.com"]

    discord = search_app_hosts_online("discord")
    assert "discord.com" in discord

    # Раньше "x" находился внутри любого слова (netflix -> x.com).
    netflix = search_app_hosts_online("netflix")
    assert "x.com" not in netflix
    assert netflix == []


def test_search_does_not_invent_domains(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "HISTORY_FILE", str(tmp_path / "history.json"))
    assert search_app_hosts_online("совершенно неизвестное приложение") == []
