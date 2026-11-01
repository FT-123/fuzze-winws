import os

import fuzzer_engine as fe
from diagnostics import DiagnosticsReport
from fuzzer_engine import FuzzerEngine

SAMPLE = """@echo off
start "zapret" /min "%~dp0bin\\winws.exe" --wf-tcp=80,443 ^
--filter-tcp=80,443 --hostlist="%LISTS%list-general.txt" --dpi-desync=fake,disorder2 --dpi-desync-split-seqovl=681 --dpi-desync-split-pos=3 --dpi-desync-ttl=4 --dpi-desync-fooling=badsum --dpi-desync-repeats=8
"""


def make_engine(tmp_path):
    bat = tmp_path / "strategy.bat"
    bat.write_text(SAMPLE, encoding="utf-8")
    engine = FuzzerEngine(bat_path=str(bat))
    engine.log_callback = lambda _msg: None
    engine.search_mode = "quick"
    return engine


def patch_common(monkeypatch, engine, report, evaluate_result):
    monkeypatch.setattr(engine, "_check_assets", lambda: True)
    monkeypatch.setattr(engine, "_prepare_targets", lambda targets: list(targets))
    monkeypatch.setattr(engine, "detect_engine_type", lambda: "winws1")
    monkeypatch.setattr(engine, "stop_winws", lambda: None)
    monkeypatch.setattr(engine, "_stop_windivert", lambda: None)
    monkeypatch.setattr(fe.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        fe, "run_diagnostics", lambda domains, log, **kwargs: report
    )

    calls = []

    def fake_evaluate(candidate, targets, label, attempts=1,
                      min_success_ratio=None, apply_params=True):
        calls.append((label, list(targets), candidate))
        engine.last_result = (len(targets), len(targets))
        return evaluate_result(label, candidate, len(targets))

    monkeypatch.setattr(engine, "evaluate_candidate", fake_evaluate)
    monkeypatch.setattr(engine, "_record_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_restore_original", lambda: None)
    return calls


def test_auto_flow_success(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    report = DiagnosticsReport(
        domains=["youtube.com"], canary="youtube.com", bypass_needed=True,
        block_type="tls12_server_hello", tls12_ok=False, http_ok=True,
    )
    calls = patch_common(
        monkeypatch, engine, report,
        evaluate_result=lambda label, candidate, count: label != "БАЗОВЫЙ КОНФИГ",
    )
    auto_path = tmp_path / "auto-config.bat"
    monkeypatch.setattr(engine, "_write_auto_config", lambda candidate, engine_name: str(auto_path))
    monkeypatch.setattr(engine, "_start_and_verify", lambda path, canary: True)

    assert engine.run_fuzzing(["youtube.com"]) is True
    assert engine.last_result == (1, 1)
    # Базовая проверка + canary + подтверждение + финальная проверка.
    assert len(calls) >= 4
    assert calls[0][0] == "БАЗОВЫЙ КОНФИГ"
    assert any("CANARY" in call[0] for call in calls)


def test_auto_flow_failure_restores_original(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    report = DiagnosticsReport(
        domains=["youtube.com"], canary="youtube.com", bypass_needed=True,
        block_type="unknown", tls12_ok=False,
    )
    patch_common(
        monkeypatch, engine, report,
        evaluate_result=lambda label, candidate, count: False,
    )
    restored = []
    monkeypatch.setattr(engine, "_restore_original", lambda: restored.append(True))

    assert engine.run_fuzzing(["youtube.com"]) is False
    assert restored == [True]


def test_auto_flow_skips_when_already_working(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    report = DiagnosticsReport(
        domains=["youtube.com"], canary="youtube.com", bypass_needed=False,
        block_type="none", tls12_ok=True, http_ok=True, tls13_ok=True,
    )
    patch_common(
        monkeypatch, engine, report,
        evaluate_result=lambda label, candidate, count: False,
    )
    assert engine.run_fuzzing(["youtube.com"]) is True
