"""Генераторы кандидатов для умного подбора стратегий.

Кандидаты упорядочены по семействам и стоимости: сначала простые split-стратегии,
затем fake с TTL/фулингами, faked, hostfake, комбинированные и QUIC.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from models import WinwsParams
from strategy_model import LuaGroup, LuaInstance, Winws2Model

Fooling = Tuple[str, ...]

FOOLINGS: List[Fooling] = [
    (),
    ("tcp_md5",),
    ("badsum",),
    ("tcp_seq=-3000",),
    ("tcp_seq=1000000",),
    ("tcp_ack=-66000", "tcp_ts_up"),
    ("tcp_ts=-1000",),
    ("tcp_flags_unset=ACK",),
    ("tcp_flags_set=SYN",),
]

WINWS1_FOOLINGS = ["none", "md5sig", "badsum", "badseq", "ts"]

TTL_ORDER = [3, 4, 6, 5, 7, 2, 8, 9, 10, 11, 12, 1]
WINWS1_TTLS = [3, 4, 6, 5, 7, 2]

POSITIONS_TLS = [
    "1",
    "2",
    "sniext+1",
    "sniext+4",
    "host+1",
    "midsld",
    "1,midsld",
    "1,midsld,1220",
    "1,sniext+1,host+1,midsld-2,midsld,midsld+2,endhost-1",
]
POSITIONS_HTTP = ["method+2", "midsld", "method+2,midsld"]


@dataclass
class SearchCandidate:
    label: str
    stage: int
    engine: str
    params: Optional[WinwsParams] = None
    content: Optional[str] = None
    cost: int = 0
    edits: Dict[Tuple[int, int], List[LuaInstance]] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def _mode_settings(mode: str) -> dict:
    if mode == "quick":
        return {
            "positions_tls": POSITIONS_TLS[:5],
            "positions_http": POSITIONS_HTTP[:2],
            "ttls": [3, 4, 6],
            "autottls": [],
            "foolings": FOOLINGS[:3],
            "repeats": [1, 6],
            "tls_mods": ["", "rnd,dupsid"],
            "split_modes": ["multisplit", "multidisorder"],
            "faked_modes": ["fakedsplit"],
            "combos": False,
            "hostfake": False,
            "wssize": False,
            "syndata": False,
            "quic_ttls": [3, 6],
        }
    if mode == "deep":
        return {
            "positions_tls": POSITIONS_TLS
            + ["2,1", "sniext+1,host+1", "midsld-2,midsld,midsld+2", "endhost-1"],
            "positions_http": POSITIONS_HTTP + ["method+2,midsld,1"],
            "ttls": TTL_ORDER,
            "autottls": [1, 2, 3, 4, 5],
            "foolings": FOOLINGS,
            "repeats": [1, 2, 6, 11],
            "tls_mods": ["", "rnd,dupsid", "rnd,rndsni,dupsid", "rnd,dupsid,padencap"],
            "split_modes": ["multisplit", "multidisorder", "multidisorder_legacy"],
            "faked_modes": ["fakedsplit", "fakeddisorder"],
            "combos": True,
            "hostfake": True,
            "wssize": True,
            "syndata": True,
            "quic_ttls": [1, 3, 6, 11],
        }
    return {
        "positions_tls": POSITIONS_TLS,
        "positions_http": POSITIONS_HTTP,
        "ttls": TTL_ORDER,
        "autottls": [1, 2, 3],
        "foolings": FOOLINGS,
        "repeats": [1, 6, 11],
        "tls_mods": ["", "rnd,dupsid"],
        "split_modes": ["multisplit", "multidisorder"],
        "faked_modes": ["fakedsplit", "fakeddisorder"],
        "combos": True,
        "hostfake": True,
        "wssize": False,
        "syndata": False,
        "quic_ttls": [1, 3, 6, 11],
    }


# ---------------------------------------------------------------------------
# winws1
# ---------------------------------------------------------------------------

def winws1_candidates(baseline: WinwsParams, mode: str = "standard") -> Iterator[SearchCandidate]:
    settings = _mode_settings(mode)
    seen = {baseline.to_key()}
    stage = 1

    def emit(label: str, params: WinwsParams, stage_no: int) -> Optional[SearchCandidate]:
        key = params.to_key()
        if key in seen:
            return None
        seen.add(key)
        return SearchCandidate(
            label=label,
            stage=stage_no,
            engine="winws1",
            params=params,
            cost=_param_cost(params),
        )

    def variant(**kwargs) -> WinwsParams:
        values = {
            "tcp_split": baseline.tcp_split,
            "tcp_seqovl": baseline.tcp_seqovl,
            "tcp_ttl": baseline.tcp_ttl,
            "desync_mode": baseline.desync_mode,
            "fooling_mode": baseline.fooling_mode,
            "udp_repeats": baseline.udp_repeats,
            "udp_cutoff": baseline.udp_cutoff,
            "any_protocol": baseline.any_protocol,
        }
        values.update(kwargs)
        return WinwsParams(**values)

    # 1. Простые split/disorder.
    for split_mode in ["split", "split2", "disorder", "disorder2"]:
        for position in [1, 2, 3, 4]:
            for seqovl in [0, 300, 681]:
                candidate = emit(
                    f"split {split_mode} pos={position} seqovl={seqovl}",
                    variant(
                        desync_mode=split_mode,
                        tcp_split=position,
                        tcp_seqovl=seqovl,
                        tcp_ttl=0,
                        fooling_mode="none",
                    ),
                    stage,
                )
                if candidate:
                    yield candidate
    stage += 1

    # 2. Fake + TTL / fooling.
    for desync in ["fake", "fake,split2", "fake,disorder2"]:
        for ttl in WINWS1_TTLS:
            for fooling_value in WINWS1_FOOLINGS:
                candidate = emit(
                    f"{desync} ttl={ttl} fooling={fooling_value}",
                    variant(
                        desync_mode=desync,
                        tcp_ttl=ttl,
                        fooling_mode=fooling_value,
                        tcp_split=baseline.tcp_split,
                        tcp_seqovl=baseline.tcp_seqovl,
                    ),
                    stage,
                )
                if candidate:
                    yield candidate
    stage += 1

    # 3. Faked split / syndata / oob.
    for desync in ["fakedsplit", "fakeddisorder", "multisplit", "multidisorder", "syndata", "oob"]:
        for position in [1, 2, 3]:
            for ttl in ([0] if desync in ("syndata", "oob") else TTL_ORDER[:4]):
                candidate = emit(
                    f"{desync} pos={position} ttl={ttl}",
                    variant(
                        desync_mode=desync,
                        tcp_split=position,
                        tcp_ttl=ttl,
                        fooling_mode="none",
                        tcp_seqovl=baseline.tcp_seqovl,
                    ),
                    stage,
                )
                if candidate:
                    yield candidate
    stage += 1

    # 4. Комбинации.
    if settings["combos"]:
        for desync in ["fake,split2", "fake,disorder2", "fake,multisplit", "fake,fakeddisorder"]:
            for ttl in WINWS1_TTLS:
                for fooling_value in WINWS1_FOOLINGS[:4]:
                    candidate = emit(
                        f"{desync} ttl={ttl} fooling={fooling_value}",
                        variant(
                            desync_mode=desync,
                            tcp_ttl=ttl,
                            fooling_mode=fooling_value,
                            tcp_split=2,
                            tcp_seqovl=681,
                        ),
                        stage,
                    )
                    if candidate:
                        yield candidate
    stage += 1

    # 5. Повторы/cutoff/any-protocol.
    for repeats in [1, 2, 4, 6, 10]:
        candidate = emit(
            f"repeats={repeats}",
            variant(udp_repeats=repeats),
            stage,
        )
        if candidate:
            yield candidate
    for any_protocol in [False, True]:
        candidate = emit(
            f"any_protocol={any_protocol}",
            variant(any_protocol=any_protocol),
            stage,
        )
        if candidate:
            yield candidate


def _param_cost(params: WinwsParams) -> int:
    cost = 1
    if params.tcp_ttl:
        cost += 1
    if params.fooling_mode and params.fooling_mode != "none":
        cost += 1
    if params.tcp_seqovl:
        cost += 1
    if params.any_protocol:
        cost += 1
    if params.udp_repeats > 1:
        cost += 1
    return cost


def minimize_winws1_candidates(
    winner: WinwsParams, mode: str = "standard"
) -> Iterator[SearchCandidate]:
    if mode == "quick":
        return

    variants: List[Tuple[str, WinwsParams]] = []
    base = dict(
        tcp_split=winner.tcp_split,
        tcp_seqovl=winner.tcp_seqovl,
        tcp_ttl=winner.tcp_ttl,
        desync_mode=winner.desync_mode,
        fooling_mode=winner.fooling_mode,
        udp_repeats=winner.udp_repeats,
        udp_cutoff=winner.udp_cutoff,
        any_protocol=winner.any_protocol,
    )

    if winner.fooling_mode != "none":
        values = dict(base, fooling_mode="none")
        variants.append(("убрать fooling", WinwsParams(**values)))
    if winner.tcp_ttl:
        values = dict(base, tcp_ttl=0)
        variants.append(("убрать ttl", WinwsParams(**values)))
    if winner.any_protocol:
        values = dict(base, any_protocol=False)
        variants.append(("убрать any-protocol", WinwsParams(**values)))
    if winner.udp_repeats > 1:
        values = dict(base, udp_repeats=1)
        variants.append(("repeats=1", WinwsParams(**values)))
    if winner.tcp_seqovl:
        values = dict(base, tcp_seqovl=0)
        variants.append(("убрать seqovl", WinwsParams(**values)))
    if "," in winner.desync_mode:
        simple = winner.desync_mode.split(",")[-1]
        values = dict(base, desync_mode=simple)
        variants.append((f"упростить desync до {simple}", WinwsParams(**values)))

    seen = {winner.to_key()}
    for label, params in variants:
        key = params.to_key()
        if key in seen:
            continue
        seen.add(key)
        yield SearchCandidate(
            label="min: " + label,
            stage=99,
            engine="winws1",
            params=params,
            cost=_param_cost(params),
        )


# ---------------------------------------------------------------------------
# winws2
# ---------------------------------------------------------------------------

def _instance(text: str) -> LuaInstance:
    token = text if text.startswith("--lua-desync=") else "--lua-desync=" + text
    return LuaInstance.parse(token)


def _fooling_params(fooling: Fooling) -> List[str]:
    return [item for item in fooling]


def _fake_instance(
    blob: str,
    ttl: Optional[int] = None,
    autottl: Optional[int] = None,
    fooling: Fooling = (),
    repeats: int = 1,
    tls_mod: str = "",
) -> LuaInstance:
    instance = _instance(f"fake:blob={blob}")
    if tls_mod:
        instance.set_param("tls_mod", tls_mod)
    for param in _fooling_params(fooling):
        if "=" in param:
            name, value = param.split("=", 1)
            instance.set_param(name, value)
        else:
            instance.set_param(param)
    if ttl is not None:
        instance.set_param("ip_ttl", str(ttl))
        instance.set_param("ip6_ttl", str(ttl))
    if autottl is not None:
        instance.set_param("ip_autottl", f"-{autottl},3-20")
        instance.set_param("ip6_autottl", f"-{autottl},3-20")
    if repeats > 1:
        instance.set_param("repeats", str(repeats))
    return instance


def _split_instance(function: str, positions: str, ttl: Optional[int] = None) -> LuaInstance:
    instance = _instance(f"{function}:pos={positions}")
    if ttl is not None:
        instance.set_param("ip_ttl", str(ttl))
        instance.set_param("ip6_ttl", str(ttl))
    return instance


def _adapt_to_baseline(
    template: List[LuaInstance], baseline: LuaGroup, family: str
) -> List[LuaInstance]:
    """Сохраняет сервисные особенности (blob, tls_mod, sni) базовой группы."""
    baseline_fake = next(
        (instance for instance in baseline.instances if instance.function == "fake"), None
    )
    result: List[LuaInstance] = []
    for instance in template:
        clone = instance.clone()
        if clone.function == "fake" and baseline_fake is not None:
            blob = clone.get("blob")
            if blob in (None, "fake_default_tls", "fake_default_http", "fake_default_quic"):
                baseline_blob = baseline_fake.get("blob")
                if baseline_blob and baseline_blob.startswith("0x") is False and baseline_blob not in (
                    "fake_default_tls",
                    "fake_default_http",
                    "fake_default_quic",
                ):
                    clone.set_param("blob", baseline_blob)
            if family == "tls" and not clone.has("tls_mod"):
                baseline_mod = baseline_fake.get("tls_mod")
                if baseline_mod:
                    clone.set_param("tls_mod", baseline_mod)
        result.append(clone)
    return result


def _winws2_candidate(
    model: Winws2Model,
    groups: List[LuaGroup],
    templates: List[List[LuaInstance]],
    label: str,
    stage: int,
    family: str,
) -> SearchCandidate:
    edits: Dict[Tuple[int, int], List[LuaInstance]] = {}
    for group in groups:
        template = templates[0]
        edits[group.key] = _adapt_to_baseline(template, group, family)

    content = model.replace_groups(edits)
    cost = sum(len(instances) + sum(len(inst.params) for inst in instances) for instances in edits.values())
    return SearchCandidate(
        label=label,
        stage=stage,
        engine="winws2",
        content=content,
        cost=cost,
        edits=edits,
        meta={"family": family},
    )


def winws2_candidates(
    model: Winws2Model, mode: str = "standard", only_family: Optional[str] = None
) -> Iterator[SearchCandidate]:
    settings = _mode_settings(mode)
    seen = set()

    families = [
        ("tls", "tcp", ["tls_client_hello"], "fake_default_tls", settings["positions_tls"]),
        ("http", "tcp", ["http_req"], "fake_default_http", settings["positions_http"]),
        ("quic", "udp", ["quic_initial"], "fake_default_quic", []),
    ]

    for family, protocol, payloads, blob, positions in families:
        if only_family and family != only_family:
            continue
        groups = model.groups_for(protocol, payloads)
        if not groups:
            continue

        def emit(
            label: str,
            templates: List[List[LuaInstance]],
            stage: int,
        ) -> Optional[SearchCandidate]:
            candidate = _winws2_candidate(model, groups, templates, label, stage, family)
            key = tuple(
                sorted(
                    (group_key, tuple(instance.signature() for instance in instances))
                    for group_key, instances in candidate.edits.items()
                )
            )
            if key in seen:
                return None
            seen.add(key)
            return candidate

        if family == "quic":
            for fake_blob in [blob, "0x00000000000000000000000000000000"]:
                for ttl in settings["quic_ttls"]:
                    for repeats in settings["repeats"]:
                        candidate = emit(
                            f"QUIC fake ttl={ttl} repeats={repeats}",
                            [[_fake_instance(fake_blob, ttl=ttl, repeats=repeats)]],
                            1,
                        )
                        if candidate:
                            yield candidate
            continue

        # 1. Split/disorder.
        tls_mods = settings["tls_mods"] if family == "tls" else [""]
        if mode == "quick":
            tls_mods = tls_mods[:1]
        elif mode == "standard":
            tls_mods = tls_mods[:2]

        fake_ttls = settings["ttls"] if mode == "deep" else settings["ttls"][:4]
        fake_foolings = settings["foolings"] if mode == "deep" else settings["foolings"][:5]
        faked_positions = positions if mode == "deep" else positions[:4]
        faked_ttls = settings["ttls"] if mode == "deep" else settings["ttls"][:4]
        faked_foolings = settings["foolings"] if mode == "deep" else settings["foolings"][:3]

        for function in settings["split_modes"]:
            for position in positions:
                candidate = emit(
                    f"{family.upper()} {function} pos={position}",
                    [[_split_instance(function, position)]],
                    1,
                )
                if candidate:
                    yield candidate

        # 2. Fake + TTL / autottl / fooling.
        for ttl in fake_ttls:
            for fooling in fake_foolings:
                for repeats in settings["repeats"][:2]:
                    for tls_mod in tls_mods:
                        candidate = emit(
                            f"{family.upper()} fake ttl={ttl} repeats={repeats}"
                            + (f" {','.join(fooling)}" if fooling else "")
                            + (f" tls_mod={tls_mod}" if tls_mod else ""),
                            [[_fake_instance(blob, ttl=ttl, fooling=fooling, repeats=repeats, tls_mod=tls_mod)]],
                            2,
                        )
                        if candidate:
                            yield candidate
        for autottl in settings["autottls"]:
            for fooling in fake_foolings[:4]:
                for tls_mod in tls_mods:
                    candidate = emit(
                        f"{family.upper()} fake autottl={autottl} {','.join(fooling)}"
                        + (f" tls_mod={tls_mod}" if tls_mod else ""),
                        [[_fake_instance(blob, autottl=autottl, fooling=fooling, tls_mod=tls_mod)]],
                        2,
                    )
                    if candidate:
                        yield candidate

        # 3. Faked split / disorder.
        for function in settings["faked_modes"]:
            for position in faked_positions:
                for ttl in faked_ttls:
                    candidate = emit(
                        f"{family.upper()} {function} pos={position} ttl={ttl}",
                        [[_split_instance(function, position, ttl=ttl)]],
                        3,
                    )
                    if candidate:
                        yield candidate
                for fooling in faked_foolings:
                    candidate = emit(
                        f"{family.upper()} {function} pos={position} {','.join(fooling)}",
                        [[_split_instance_with_fooling(function, position, fooling)]],
                        3,
                    )
                    if candidate:
                        yield candidate

        # 4. Hostfake (TLS/HTTP).
        if settings["hostfake"]:
            for position in positions[:4]:
                candidate = emit(
                    f"{family.upper()} hostfakesplit pos={position}",
                    [[_instance(f"hostfakesplit:host=www.google.com:pos={position}")]],
                    4,
                )
                if candidate:
                    yield candidate

        # 5. Комбинации fake + split.
        if settings["combos"]:
            for split_function in ["multisplit", "multidisorder"]:
                for position in positions[:4]:
                    for ttl in [3, 4, 6]:
                        fake = _fake_instance(blob, ttl=ttl, repeats=1)
                        split = _split_instance(split_function, position)
                        candidate = emit(
                            f"{family.upper()} fake+{split_function} pos={position} ttl={ttl}",
                            [[fake, split]],
                            5,
                        )
                        if candidate:
                            yield candidate

        # 6. wssize / syndata (только без hostlist).
        has_hostlist = any(group.hostlists for group in groups)
        if settings["wssize"] and not has_hostlist:
            for position in positions[:3]:
                candidate = emit(
                    f"{family.upper()} wssize + {settings['split_modes'][0]} pos={position}",
                    [[_instance("wssize:wsize=1:scale=6"), _split_instance(settings["split_modes"][0], position)]],
                    6,
                )
                if candidate:
                    yield candidate
        if settings["syndata"]:
            for position in positions[:3]:
                candidate = emit(
                    f"{family.upper()} syndata + multidisorder pos={position}",
                    [[_instance("syndata"), _split_instance("multidisorder", position)]],
                    6,
                )
                if candidate:
                    yield candidate


def _split_instance_with_fooling(function: str, position: str, fooling: Fooling) -> LuaInstance:
    instance = _instance(f"{function}:pos={position}")
    for param in _fooling_params(fooling):
        if "=" in param:
            name, value = param.split("=", 1)
            instance.set_param(name, value)
        else:
            instance.set_param(param)
    return instance


def minimize_winws2_candidates(
    model: Winws2Model,
    winner: SearchCandidate,
    mode: str = "standard",
) -> Iterator[SearchCandidate]:
    if mode == "quick" or not winner.edits:
        return

    optional_params = (
        "ip_ttl",
        "ip6_ttl",
        "ip_autottl",
        "ip6_autottl",
        "repeats",
        "tcp_md5",
        "badsum",
        "tcp_seq",
        "tcp_ack",
        "tcp_ts",
        "tcp_ts_up",
        "tcp_flags_unset",
        "tcp_flags_set",
        "tls_mod",
        "seqovl",
        "seqovl_pattern",
    )

    # Удаление целых инстансов.
    for group_key, instances in winner.edits.items():
        if len(instances) < 2:
            continue
        for index in range(len(instances)):
            reduced = list(instances)
            removed = reduced.pop(index)
            edits = dict(winner.edits)
            edits[group_key] = reduced
            content = model.replace_groups(edits)
            yield SearchCandidate(
                label=f"min: убрать {removed.function}",
                stage=99,
                engine="winws2",
                content=content,
                cost=max(1, winner.cost - 1),
                edits=edits,
                meta=dict(winner.meta),
            )

    # Удаление необязательных параметров.
    for group_key, instances in winner.edits.items():
        for index, instance in enumerate(instances):
            for param in optional_params:
                if not instance.has(param):
                    continue
                edits = {
                    key: [item.clone() for item in values]
                    for key, values in winner.edits.items()
                }
                edits[group_key][index].remove_param(param)
                content = model.replace_groups(edits)
                yield SearchCandidate(
                    label=f"min: убрать {param}",
                    stage=99,
                    engine="winws2",
                    content=content,
                    cost=max(1, winner.cost - 1),
                    edits=edits,
                    meta=dict(winner.meta),
                )
