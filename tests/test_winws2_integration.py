from fuzzer_engine import FuzzerEngine

WINWS2_SAMPLE = r'''@echo off
start "zapret" /min "%~dp0bin\winws2.exe" --wf-tcp-out=80,443 ^
--lua-init=@"%~dp0lua\zapret-lib.lua" --lua-init=@"%~dp0lua\zapret-antidpi.lua" ^
--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello ^
  --lua-desync=fake:blob=fake_default_tls:repeats=11 ^
  --lua-desync=multidisorder:pos=1,midsld ^
  --new ^
--filter-udp=443 --filter-l7=quic --payload=quic_initial ^
  --lua-desync=fake:blob=fake_default_quic:repeats=11
'''


def test_build_winws2_candidates(tmp_path):
    bat = tmp_path / "winws2.bat"
    bat.write_text(WINWS2_SAMPLE, encoding="utf-8")

    engine = FuzzerEngine(bat_path=str(bat))
    engine.log_callback = lambda _message: None
    engine_type, model, candidates = engine._build_candidates("quick")

    assert engine_type == "winws2"
    assert model is not None
    assert candidates
    assert any("TLS" in candidate.label for candidate in candidates)
    assert any("QUIC" in candidate.label for candidate in candidates)


def test_write_auto_config_for_winws2(tmp_path):
    bat = tmp_path / "winws2.bat"
    bat.write_text(WINWS2_SAMPLE, encoding="utf-8")

    engine = FuzzerEngine(bat_path=str(bat))
    engine.log_callback = lambda _message: None
    _engine_type, _model, candidates = engine._build_candidates("quick")
    winner = next(candidate for candidate in candidates if "TLS" in candidate.label)

    auto_path = engine._write_auto_config(winner, "winws2")
    assert auto_path
    content = open(auto_path, encoding="utf-8").read()
    assert "winws2.exe" in content
    assert "--lua-init=@" in content
    assert "--lua-desync=" in content
    assert "auto-config.bat" in auto_path
