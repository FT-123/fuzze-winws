import pytest

from fuzzer_engine import (
    FuzzerEngine,
    WinwsParams,
    is_valid_domain,
    validate_params,
)

SAMPLE_BAT = """@echo off
chcp 65001 > nul
cd /d "%~dp0"
set "BIN=%~dp0bin\\"
set "LISTS=%~dp0lists\\"
start "zapret" /min "%BIN%winws.exe" --wf-tcp=80,443 --wf-udp=443 ^
--filter-udp=443 --hostlist="%LISTS%list-general.txt" --dpi-desync=fake --dpi-desync-repeats=8 --dpi-desync-cutoff=n3 --new ^
--filter-tcp=2053,2083 --hostlist-domains=discord.media --dpi-desync=fake,disorder2 --dpi-desync-split-seqovl=681 --dpi-desync-split-pos=3 --dpi-desync-ttl=4 --dpi-desync-fooling=badsum --dpi-desync-repeats=8 --new ^
--filter-tcp=80,443 --hostlist="%LISTS%list-general.txt" --hostlist="%LISTS%list-general-user.txt" --dpi-desync=fake,disorder2 --dpi-desync-split-seqovl=681 --dpi-desync-split-pos=3 --dpi-desync-ttl=4 --dpi-desync-fooling=badsum --dpi-desync-any-protocol=1 --dpi-desync-cutoff=d2 --dpi-desync-repeats=8
"""


def make_engine(tmp_path, content: str = SAMPLE_BAT) -> FuzzerEngine:
    bat = tmp_path / "strategy.bat"
    bat.write_text(content, encoding="utf-8")
    return FuzzerEngine(bat_path=str(bat))


def test_is_valid_domain():
    assert is_valid_domain("youtube.com") is True
    assert is_valid_domain("sub.domain.co.uk") is True
    assert is_valid_domain("xn--80ak6aa92e.com") is True

    assert is_valid_domain("") is False
    assert is_valid_domain(".invalid.com") is False
    assert is_valid_domain("invalid.com.") is False
    assert is_valid_domain("invalid_ip") is False
    assert is_valid_domain("8.8.8.8") is False
    assert is_valid_domain("https://youtube.com/watch") is False
    assert is_valid_domain("hello world.com") is False


def test_winws_params_defaults():
    params = WinwsParams()
    assert params.tcp_split == 1
    assert params.tcp_seqovl == 664
    assert params.tcp_ttl == 0
    assert params.udp_repeats == 8
    assert params.udp_cutoff == "n4"
    assert params.to_key() == (1, 664, 0, "split", "none", 8, "n4", False)


def test_sanitize_and_filter_targets():
    raw_targets = [
        "  YOUTUBE.COM  ",
        "youtube.com",       # дубликат
        "127.0.0.1",         # локальный IP
        "8.8.8.8",           # IP-адрес
        "https://discord.gg/invite",
        "discord.gg",
    ]

    cleaned = FuzzerEngine.sanitize_and_filter_targets(raw_targets)

    assert "youtube.com" in cleaned
    assert "discord.gg" in cleaned
    assert "8.8.8.8" not in cleaned
    assert "127.0.0.1" not in cleaned
    assert "https://discord.gg/invite" not in cleaned
    assert len(cleaned) == len(set(cleaned))


def test_generate_mutations_no_duplicates():
    engine = FuzzerEngine()
    baseline = WinwsParams()
    mutations = list(engine.generate_mutations(baseline))

    assert mutations
    keys = [mutation.to_key() for mutation in mutations]
    assert len(keys) == len(set(keys))
    for mutation in mutations:
        assert mutation.to_key() != baseline.to_key()


def test_extract_baseline_is_section_aware(tmp_path):
    engine = make_engine(tmp_path)
    baseline = engine.extract_baseline()

    # Значения берутся из "общей" TCP-секции, а не из UDP.
    assert baseline.desync_mode == "fake,disorder2"
    assert baseline.tcp_split == 3
    assert baseline.tcp_seqovl == 681
    assert baseline.tcp_ttl == 4
    assert baseline.fooling_mode == "badsum"
    assert baseline.udp_repeats == 8
    assert baseline.udp_cutoff == "d2"
    assert baseline.any_protocol is True


def test_patch_does_not_corrupt_any_protocol(tmp_path):
    engine = make_engine(tmp_path)
    params = WinwsParams(tcp_split=4, tcp_seqovl=777, tcp_ttl=9,
                         desync_mode="split2", fooling_mode="md5sig",
                         udp_repeats=2, udp_cutoff="n9", any_protocol=False)

    content = (tmp_path / "strategy.bat").read_text(encoding="utf-8")
    patched = engine._apply_params_to_cmdline(content, params)

    assert " =1" not in patched
    assert "--dpi-desync-any-protocol" not in patched
    assert "--dpi-desync=split2" in patched
    assert "--dpi-desync-split-pos=4" in patched
    assert "--dpi-desync-split-seqovl=777" in patched
    assert "--dpi-desync-ttl=9" in patched
    assert "--dpi-desync-fooling=md5sig" in patched


def test_patch_leaves_udp_and_header_intact(tmp_path):
    engine = make_engine(tmp_path)
    params = WinwsParams(tcp_split=4, tcp_seqovl=777, tcp_ttl=9,
                         desync_mode="split2", fooling_mode="md5sig",
                         udp_repeats=2, udp_cutoff="n9", any_protocol=True)

    content = (tmp_path / "strategy.bat").read_text(encoding="utf-8")
    patched = engine._apply_params_to_cmdline(content, params)
    udp_section = next(
        line for line in patched.splitlines() if line.startswith("--filter-udp=443")
    )

    # UDP-стратегия (fake) не переделывается под TCP-десинк.
    assert "--dpi-desync=fake" in udp_section
    assert "--dpi-desync-split-pos" not in udp_section
    assert "--dpi-desync-ttl" not in udp_section
    assert "--dpi-desync-fooling" not in udp_section
    # А общие repeats/cutoff обновляются.
    assert "--dpi-desync-repeats=2" in udp_section
    assert "--dpi-desync-cutoff=n9" in udp_section

    assert "--wf-tcp=80,443" in patched


def test_patch_original_bat_creates_backup_and_roundtrip(tmp_path):
    engine = make_engine(tmp_path)
    params = WinwsParams(tcp_split=3, tcp_seqovl=681, tcp_ttl=4,
                         desync_mode="fake,split2", fooling_mode="badsum",
                         udp_repeats=10, udp_cutoff="d2", any_protocol=True)

    engine.patch_original_bat(params)

    assert (tmp_path / "strategy.bat.bak").exists()
    updated = FuzzerEngine(bat_path=str(tmp_path / "strategy.bat"))
    baseline = updated.extract_baseline()
    assert baseline.tcp_split == 3
    assert baseline.desync_mode == "fake,split2"
    assert baseline.udp_repeats == 10
    assert baseline.udp_cutoff == "d2"


def test_validate_params_rejects_injection():
    with pytest.raises(ValueError):
        validate_params(WinwsParams(desync_mode="split & calc"))
    with pytest.raises(ValueError):
        validate_params(WinwsParams(fooling_mode='md5sig"'))
    with pytest.raises(ValueError):
        validate_params(WinwsParams(udp_cutoff="n4; rm -rf"))
    with pytest.raises(ValueError):
        validate_params(WinwsParams(tcp_split=0))
    with pytest.raises(ValueError):
        validate_params(WinwsParams(udp_repeats=0))


def test_check_engine_assets_reports_missing(tmp_path):
    bat = tmp_path / "strategy.bat"
    bat.write_text("call service.bat status_zapret\n", encoding="utf-8")

    issues = FuzzerEngine.check_engine_assets(str(bat))
    assert any("service.bat" in issue for issue in issues)
    assert any("winws.exe" in issue for issue in issues)
    assert any("list-general.txt" in issue or "lists" in issue for issue in issues)
