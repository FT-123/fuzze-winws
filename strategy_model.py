"""Модель Lua-стратегий winws2 и бережная правка .bat.

Стратегия winws2 состоит из профилей (секции ``--new``), внутри которых
находятся группы, ограниченные фильтрами ``--payload`` / ``--in-range`` /
``--out-range``, а в группах — упорядоченные инстансы ``--lua-desync``.

Модуль не пытается понять все параметры winws2. Он сохраняет всё незнакомое
как есть и даёт менять только последовательность инстансов выбранной группы.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

_TOKEN_RE = re.compile(r'(?:"[^"]*"|[^\s^]+)')
_NEW_RE = re.compile(r'(?<![\w-])--new(?![-\w])')
_LUA_RE = re.compile(r'(?<![\w-])--lua-desync=(?:"[^"]*"|[^\s^]+)')
_FLAG_VALUE_RE = r'(?:"[^"]*"|[^\s^]+)'


def _flag_value(text: str, flag: str) -> Optional[str]:
    match = re.search(rf'(?<![\w-])--{re.escape(flag)}=({_FLAG_VALUE_RE})', text)
    if not match:
        return None
    return match.group(1).strip('"')


def _split_quoted(value: str) -> List[str]:
    """Делит значение по ':' вне кавычек."""
    parts: List[str] = []
    current: List[str] = []
    quote = False
    for char in value:
        if char == '"':
            quote = not quote
            current.append(char)
        elif char == ":" and not quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


@dataclass
class LuaInstance:
    function: str
    params: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    raw: str = ""

    @classmethod
    def parse(cls, token: str) -> "LuaInstance":
        value = token
        if value.startswith("--lua-desync="):
            value = value[len("--lua-desync="):]
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        parts = _split_quoted(value)
        function = parts[0] if parts else ""
        params: List[Tuple[str, Optional[str]]] = []
        for part in parts[1:]:
            if not part:
                continue
            if "=" in part:
                name, param_value = part.split("=", 1)
                params.append((name, param_value))
            else:
                params.append((part, None))
        return cls(function=function, params=params, raw=value)

    def get(self, name: str) -> Optional[str]:
        for key, value in self.params:
            if key == name:
                return value
        return None

    def has(self, name: str) -> bool:
        return any(key == name for key, _ in self.params)

    def set_param(self, name: str, value: Optional[str] = None) -> None:
        for index, (key, _) in enumerate(self.params):
            if key == name:
                self.params[index] = (key, value)
                return
        self.params.append((name, value))

    def remove_param(self, *names: str) -> None:
        names_set = set(names)
        self.params = [(key, value) for key, value in self.params if key not in names_set]

    def clone(self) -> "LuaInstance":
        return LuaInstance(self.function, list(self.params), self.raw)

    def to_token(self) -> str:
        parts = [self.function]
        for key, value in self.params:
            parts.append(key if value is None else f"{key}={value}")
        body = ":".join(parts)
        if " " in body:
            body = '"' + body + '"'
        return "--lua-desync=" + body

    def signature(self) -> str:
        return self.to_token()


@dataclass
class LuaGroup:
    section_index: int
    order: int
    protocol: str
    l7: str
    payloads: Tuple[str, ...]
    in_range: Optional[str]
    out_range: Optional[str]
    instances: List[LuaInstance]
    span_start: int
    span_end: int
    editable: bool
    hostlists: Tuple[str, ...]

    @property
    def key(self) -> Tuple[int, int]:
        return self.section_index, self.order

    def describe(self) -> str:
        payload = ",".join(self.payloads) or "all"
        return f"{self.protocol}/{self.l7 or '?'} payload={payload}"


class Winws2Model:
    """Разобранный батник winws2."""

    def __init__(self, content: str, groups: List[LuaGroup]):
        self.content = content
        self.groups = groups

    @property
    def is_winws2(self) -> bool:
        return bool(self.groups) or "--lua-desync=" in self.content

    def groups_for(self, protocol: str, payloads: Iterable[str]) -> List[LuaGroup]:
        wanted = set(payloads)
        exact = [
            group
            for group in self.groups
            if group.protocol == protocol and wanted.intersection(group.payloads)
        ]
        if exact:
            return exact
        return [group for group in self.groups if group.protocol == protocol and "all" in group.payloads]

    def protocol_groups(self, protocol: str) -> List[LuaGroup]:
        return [group for group in self.groups if group.protocol == protocol]

    def replace_groups(
        self, replacements: Dict[Tuple[int, int], List[LuaInstance]]
    ) -> str:
        """Возвращает новый текст батника с заменёнными группами."""
        content = self.content
        groups = [
            group
            for group in self.groups
            if group.key in replacements and group.editable
        ]
        for group in sorted(groups, key=lambda item: item.span_start, reverse=True):
            instances = replacements[group.key]
            new_text = " ".join(instance.to_token() for instance in instances if instance.function)
            content = content[: group.span_start] + new_text + content[group.span_end:]
        return content

    def describe(self) -> str:
        if not self.groups:
            return "Lua-профили не найдены"
        by_protocol: Dict[str, int] = {}
        for group in self.groups:
            by_protocol[group.protocol] = by_protocol.get(group.protocol, 0) + 1
        return ", ".join(f"{key}: {value}" for key, value in sorted(by_protocol.items()))


def _section_bounds(content: str) -> List[Tuple[int, int]]:
    matches = list(_NEW_RE.finditer(content))
    starts = [0] + [match.end() for match in matches]
    ends = [match.start() for match in matches] + [len(content)]
    return list(zip(starts, ends))


def parse_winws2(content: str) -> Winws2Model:
    groups: List[LuaGroup] = []

    for section_index, (start, end) in enumerate(_section_bounds(content)):
        section = content[start:end]
        protocol = "tcp" if re.search(r'(?<![\w-])--filter-tcp=', section) else (
            "udp" if re.search(r'(?<![\w-])--filter-udp=', section) else "other"
        )
        l7 = _flag_value(section, "filter-l7") or ""

        hostlists = tuple(
            value.strip('"')
            for value in re.findall(
                rf'(?<![\w-])--hostlist(?:-domains)?=({_FLAG_VALUE_RE})', section
            )
        )

        payloads: Tuple[str, ...] = ("all",)
        in_range: Optional[str] = None
        out_range: Optional[str] = None

        builder: List[LuaInstance] = []
        span_start: Optional[int] = None
        span_end: Optional[int] = None
        editable = True
        order = 0

        def flush() -> None:
            nonlocal builder, span_start, span_end, editable, order, payloads, in_range, out_range
            if not builder or span_start is None or span_end is None:
                builder = []
                span_start = span_end = None
                editable = True
                return
            groups.append(
                LuaGroup(
                    section_index=section_index,
                    order=order,
                    protocol=protocol,
                    l7=l7,
                    payloads=payloads,
                    in_range=in_range,
                    out_range=out_range,
                    instances=builder,
                    span_start=span_start,
                    span_end=span_end,
                    editable=editable,
                    hostlists=hostlists,
                )
            )
            order += 1
            builder = []
            span_start = span_end = None
            editable = True

        for match in _TOKEN_RE.finditer(section):
            token = match.group(0)
            if token.startswith("--payload="):
                flush()
                value = token.split("=", 1)[1].strip('"')
                payloads = tuple(part.strip() for part in value.split(",") if part.strip()) or ("all",)
            elif token.startswith("--in-range="):
                flush()
                in_range = token.split("=", 1)[1].strip('"')
            elif token.startswith("--out-range="):
                flush()
                out_range = token.split("=", 1)[1].strip('"')
            elif token.startswith("--lua-desync="):
                instance = LuaInstance.parse(token)
                if not instance.function:
                    continue
                absolute_start = start + match.start()
                absolute_end = start + match.end()
                if span_start is None:
                    span_start = absolute_start
                    span_end = absolute_end
                else:
                    between = section[span_end - start:match.start()]
                    if between.strip(" \t\r\n^"):
                        editable = False
                    span_end = absolute_end
                builder.append(instance)

        flush()

    return Winws2Model(content, groups)


def is_winws2_content(content: str) -> bool:
    lowered = content.lower()
    return "--lua-desync=" in content and ("winws2" in lowered or "--lua-init=" in lowered)


def detect_engine(content: str) -> str:
    return "winws2" if is_winws2_content(content) else "winws1"
