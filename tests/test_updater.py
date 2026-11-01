import pytest

from updater import (
    UpdateError,
    build_update_script,
    is_newer,
    launch_update,
    parse_checksums,
    parse_release,
    parse_version,
)


def test_parse_version_and_compare():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2.3-beta") == (1, 2, 3)
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("0.9.9", "1.0.0")


def test_parse_release():
    data = {
        "tag_name": "v1.0.1",
        "name": "Release",
        "body": "notes",
        "assets": [
            {"name": "ZapretStrategyTuner-Setup-1.0.1.exe",
             "browser_download_url": "https://example/setup.exe"},
            {"name": "SHA256SUMS.txt",
             "browser_download_url": "https://example/sums.txt"},
        ],
    }
    info = parse_release(data)
    assert info.version == "1.0.1"
    assert info.installer_url.endswith("/setup.exe")
    assert info.checksums_url.endswith("/sums.txt")


def test_parse_release_requires_checksums():
    with pytest.raises(UpdateError):
        parse_release({
            "tag_name": "v1.0.1",
            "assets": [
                {"name": "ZapretStrategyTuner-Setup-1.0.1.exe",
                 "browser_download_url": "https://example/setup.exe"},
            ],
        })


def test_parse_checksums():
    sums = (
        "a" * 64 + "  ZapretStrategyTuner-Setup-1.0.0.exe\n"
        + "b" * 64 + " *other.exe\n"
        + "# comment\n"
    )
    parsed = parse_checksums(sums)
    assert parsed["ZapretStrategyTuner-Setup-1.0.0.exe"] == "a" * 64
    assert parsed["other.exe"] == "b" * 64


def test_update_script_contains_silent_install():
    script = build_update_script(
        r"C:\Temp\setup.exe", r"C:\App\fuzzer.exe", pid=1234
    )
    assert 'set "PID=1234"' in script
    assert 'PID eq %PID%' in script
    assert r"C:\Temp\setup.exe" in script
    assert r"C:\App\fuzzer.exe" in script
    assert "/VERYSILENT" in script
    assert "/NORESTART" in script


def test_update_script_has_wait_timeout_and_kill():
    script = build_update_script(
        r"C:\Temp\setup.exe", r"C:\App\fuzzer.exe", pid=1234
    )
    # PID ищем вместе с пробелами, иначе find ловит цифры из поля памяти.
    assert 'findstr /C:" %PID% "' in script
    # Если приложение не закрылось — принудительное завершение вместо вечного цикла.
    assert "taskkill /F /PID %PID%" in script
    assert "GEQ 45" in script


def test_launch_update_disabled_for_source_runs(tmp_path):
    setup = tmp_path / "setup.exe"
    setup.write_bytes(b"MZ")
    assert launch_update(str(setup)) is False
