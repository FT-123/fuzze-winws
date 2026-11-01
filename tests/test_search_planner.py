from models import WinwsParams
from search_planner import (
    SearchCandidate,
    minimize_winws1_candidates,
    minimize_winws2_candidates,
    winws1_candidates,
    winws2_candidates,
)
from strategy_model import LuaInstance, parse_winws2

SAMPLE = r'''start "zapret" /min "%~dp0bin\winws2.exe" --wf-tcp-out=80,443 ^
--lua-init=@"%~dp0lua\zapret-lib.lua" --lua-init=@"%~dp0lua\zapret-antidpi.lua" ^
--filter-tcp=443 --filter-l7=tls --hostlist="%~dp0lists\list-youtube.txt" ^
  --out-range=-d10 --payload=tls_client_hello ^
   --lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=11 ^
   --lua-desync=multidisorder:pos=1,midsld ^
  --new ^
--filter-tcp=443 --filter-l7=tls ^
  --payload=tls_client_hello ^
   --lua-desync=fake:blob=fake_default_tls:tcp_seq=-10000:repeats=6 ^
   --lua-desync=multidisorder:pos=midsld ^
  --new ^
--filter-udp=443 --filter-l7=quic --hostlist="%~dp0lists\list-youtube.txt" ^
  --payload=quic_initial ^
   --lua-desync=fake:blob=quic_google:repeats=11
'''


def test_winws1_candidates_are_unique_and_ordered():
    baseline = WinwsParams(desync_mode="fake,disorder2", tcp_split=3, tcp_ttl=4,
                           fooling_mode="badsum", udp_repeats=8, any_protocol=True)
    quick = list(winws1_candidates(baseline, "quick"))
    standard = list(winws1_candidates(baseline, "standard"))

    assert quick
    assert standard
    assert len(quick) < len(standard)
    assert all(candidate.params is not None for candidate in standard)
    keys = [candidate.params.to_key() for candidate in standard]
    assert baseline.to_key() not in keys
    assert len(keys) == len(set(keys))
    assert standard[0].stage == 1
    assert standard[0].params.desync_mode in ("split", "split2", "disorder", "disorder2")


def test_winws1_minimizer():
    winner = WinwsParams(tcp_split=3, tcp_seqovl=681, tcp_ttl=4,
                         desync_mode="fake,disorder2", fooling_mode="badsum",
                         udp_repeats=8, any_protocol=True)
    variants = list(minimize_winws1_candidates(winner, "standard"))
    labels = [variant.label for variant in variants]
    assert any("fooling" in label for label in labels)
    assert any("ttl" in label for label in labels)
    assert any("any-protocol" in label for label in labels)
    for variant in variants:
        assert variant.params.to_key() != winner.to_key()


def test_winws2_candidates_and_content():
    model = parse_winws2(SAMPLE)
    candidates = []
    for candidate in winws2_candidates(model, "quick"):
        candidates.append(candidate)
        if len(candidates) >= 40:
            break

    assert candidates
    first = candidates[0]
    assert first.engine == "winws2"
    assert first.content
    assert first.edits

    # Контент остаётся валидным winws2-батником.
    reparsed = parse_winws2(first.content)
    assert reparsed.is_winws2
    assert reparsed.groups_for("tcp", ["tls_client_hello"])
    assert "lua-init" in first.content

    labels = " ".join(candidate.label for candidate in candidates)
    assert "TLS" in labels


def test_winws2_candidate_preserves_custom_blob_and_flags():
    model = parse_winws2(SAMPLE)
    candidates = list(winws2_candidates(model, "quick"))

    quic = next(candidate for candidate in candidates if "QUIC" in candidate.label)
    reparsed = parse_winws2(quic.content)
    quic_groups = reparsed.groups_for("udp", ["quic_initial"])
    assert quic_groups
    blob = quic_groups[0].instances[0].get("blob")
    assert blob is not None
    # Кастомный блоб `quic_google` должен пережить замену стратегии.
    assert blob in ("quic_google", "0x00000000000000000000000000000000")

    # Флаги вне инстансов не тронуты.
    assert "--wf-tcp-out=80,443" in quic.content
    assert "--lua-init=@" in quic.content
    assert "--payload=quic_initial" in quic.content


def test_winws2_minimizer():
    model = parse_winws2(SAMPLE)
    winner = next(c for c in winws2_candidates(model, "standard") if len(c.edits) > 0)
    # Сделаем вид, что нашли стратегию с двумя инстансами в первой группе.
    group = next(iter(winner.edits))
    winner.edits[group] = [
        LuaInstance.parse("--lua-desync=fake:blob=fake_default_tls:ip_ttl=4:repeats=6"),
        LuaInstance.parse("--lua-desync=multidisorder:pos=midsld"),
    ]
    winner.content = model.replace_groups(winner.edits)
    variants = list(minimize_winws2_candidates(model, winner, "standard"))
    assert variants
    labels = " ".join(variant.label for variant in variants)
    assert "убрать fake" in labels or "убрать multidisorder" in labels
    assert "ip_ttl" in labels or "repeats" in labels
