import os

from fuzzer_engine import _sanitize_bat_for_run

SERVICE_BAT = """@echo off
chcp 65001 > nul
cd /d "%~dp0"
call service.bat status_zapret
call service.bat check_updates
call service.bat load_game_filter
call service.bat load_user_lists
pause
start "zapret" /min "%BIN%winws2.exe" --wf-tcp-out=80,443,%GameFilter% ^
 --lua-init=@"%LUA%zapret-lib.lua"
"""


def test_sanitize_removes_all_service_bat_calls(tmp_path):
    result = _sanitize_bat_for_run(SERVICE_BAT, str(tmp_path))
    lowered = result.lower()
    assert "call service.bat" not in lowered
    assert "status_zapret" not in lowered
    assert "load_user_lists" not in lowered
    assert "check_updates" not in lowered
    assert "\npause" not in lowered


def test_sanitize_inlines_game_filter(tmp_path):
    result = _sanitize_bat_for_run(SERVICE_BAT, str(tmp_path))
    assert 'set "GameFilter=12"' in result
    assert "game_filter.enabled" in result
    assert "1024-65535" in result


def test_sanitize_keeps_winws_command(tmp_path):
    result = _sanitize_bat_for_run(SERVICE_BAT, str(tmp_path))
    assert "winws2.exe" in result
    assert result.startswith('@cd /d "')


def test_zapret2_template_is_self_contained():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "templates", "general (ZAPRET2).bat")
    content = open(path, encoding="utf-8").read()
    lines = [line.strip() for line in content.splitlines()]
    code = [
        line
        for line in lines
        if line and not line.lower().startswith("::") and not line.lower().startswith("rem ")
    ]
    joined = "\n".join(code)
    lowered = joined.lower()

    assert "service.bat" not in lowered
    assert "load_user_lists" not in lowered
    assert "gamefiltertcp" not in lowered
    assert "gamefilterudp" not in lowered
    assert "%GameFilter%" in joined
    assert 'set "GameFilter=' in joined
