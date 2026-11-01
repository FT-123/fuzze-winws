from strategy_model import LuaInstance, detect_engine, parse_winws2

SAMPLE = r'''@echo off
start "zapret: winws2" /min "%~dp0bin\winws2.exe" --wf-tcp-out=80,443 ^
--lua-init=@"%~dp0lua\zapret-lib.lua" --lua-init=@"%~dp0lua\zapret-antidpi.lua" ^
--filter-tcp=443 --filter-l7=tls --hostlist="%~dp0lists\list-youtube.txt" ^
  --out-range=-d10 ^
  --payload=tls_client_hello ^
   --lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=11 ^
   --lua-desync=multidisorder:pos=1,midsld ^
  --payload=empty --out-range=s1<d1 ^
   --lua-desync=pktmod:ip_ttl=1 ^
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


def test_parse_groups_and_instances():
    model = parse_winws2(SAMPLE)
    assert model.is_winws2
    assert len(model.groups) == 4

    first = model.groups[0]
    assert first.protocol == "tcp"
    assert first.l7 == "tls"
    assert first.payloads == ("tls_client_hello",)
    assert [inst.function for inst in first.instances] == ["fake", "multidisorder"]
    assert first.instances[0].get("blob") == "fake_default_tls"
    assert first.instances[0].has("tcp_md5")
    assert first.instances[1].get("pos") == "1,midsld"
    assert first.out_range == "-d10"
    assert first.editable

    empty_group = model.groups[1]
    assert empty_group.payloads == ("empty",)
    assert empty_group.instances[0].function == "pktmod"

    quic = model.groups[3]
    assert quic.protocol == "udp"
    assert quic.payloads == ("quic_initial",)
    assert quic.instances[0].get("blob") == "quic_google"


def test_groups_for_payload():
    model = parse_winws2(SAMPLE)
    tls_groups = model.groups_for("tcp", ["tls_client_hello"])
    assert len(tls_groups) == 2
    quic_groups = model.groups_for("udp", ["quic_initial"])
    assert len(quic_groups) == 1


def test_replace_instances_roundtrip():
    model = parse_winws2(SAMPLE)
    group = model.groups[0]
    new_instances = [
        LuaInstance.parse("--lua-desync=multisplit:pos=1,midsld"),
    ]
    updated = model.replace_groups({group.key: new_instances})

    reparsed = parse_winws2(updated)
    first = reparsed.groups[0]
    assert [inst.function for inst in first.instances] == ["multisplit"]
    assert first.instances[0].get("pos") == "1,midsld"

    # Всё, что не относилось к инстансам, сохранено.
    assert updated.count("--new") == SAMPLE.count("--new")
    assert "--lua-init=@" in updated
    assert "--payload=empty" in updated
    assert "pktmod:ip_ttl=1" in updated
    assert "quic_google" in updated


def test_replace_all_tls_groups():
    model = parse_winws2(SAMPLE)
    replacements = {}
    for group in model.groups_for("tcp", ["tls_client_hello"]):
        replacements[group.key] = [LuaInstance.parse("--lua-desync=fake:blob=fake_default_tls:ip_ttl=4")]
    updated = model.replace_groups(replacements)
    reparsed = parse_winws2(updated)
    tls_groups = reparsed.groups_for("tcp", ["tls_client_hello"])
    assert len(tls_groups) == 2
    for group in tls_groups:
        assert [inst.function for inst in group.instances] == ["fake"]
        assert group.instances[0].get("ip_ttl") == "4"


def test_instance_param_editing_preserves_order():
    instance = LuaInstance.parse(
        "--lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=11"
    )
    assert instance.to_token() == "--lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=11"

    instance.set_param("repeats", "3")
    instance.remove_param("tcp_md5")
    instance.set_param("ip_ttl", "4")
    assert instance.to_token() == "--lua-desync=fake:blob=fake_default_tls:repeats=3:ip_ttl=4"

    clone = instance.clone()
    clone.set_param("repeats", "1")
    assert instance.get("repeats") == "3"
    assert clone.get("repeats") == "1"


def test_detect_engine():
    assert detect_engine(SAMPLE) == "winws2"
    assert detect_engine("winws.exe --dpi-desync=split") == "winws1"
