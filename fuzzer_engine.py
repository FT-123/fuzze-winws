"""Движок подбора параметров winws (zapret).

Модуль умеет:
* читать базовые параметры из выбранного .bat;
* генерировать мутации стратегии;
* аккуратно править только нужные секции ``--new`` (TCP/UDP), не ломая
  остальные флаги и не превращая ``--dpi-desync-any-protocol`` в мусор;
* запускать winws и проверять доступность доменов через curl/TLS.
"""
import codecs
import concurrent.futures
import copy
import ipaddress
import itertools
import math
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from typing import Callable, Generator, List, Optional, Set, Tuple

from validators import is_valid_domain, is_valid_public_ip  # noqa: F401 (реэкспорт)
from models import WinwsParams, validate_params  # noqa: F401 (реэкспорт для совместимости)
from diagnostics import DiagnosticsReport, candidate_time_budget, run_diagnostics
from search_planner import (
    SearchCandidate,
    minimize_winws1_candidates,
    minimize_winws2_candidates,
    winws1_candidates,
    winws2_candidates,
)
from strategy_model import detect_engine, parse_winws2
from user_lists import EXCLUDE, INCLUDE, UserLists

# Один "токен" командной строки winws. Кавычки внутри значения сохраняются,
# символ продолжения строки ^ токеном не считается.
_TOKEN = r'(?:"[^"]*"|[^\s^]+)'
_NOT_FLAG_START = r'(?<![\w-])'
_NEW_SPLIT_RE = re.compile(r'((?<![\w-])--new(?![-\w]))')

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Работа с текстом батника
# ---------------------------------------------------------------------------

def _value_re(flag: str) -> re.Pattern:
    return re.compile(rf'{_NOT_FLAG_START}--{re.escape(flag)}=(?:"[^"]*"|[^\s^]+)')


def _any_form_re(flag: str) -> re.Pattern:
    return re.compile(
        rf'{_NOT_FLAG_START}--{re.escape(flag)}(?:=(?:"[^"]*"|[^\s^]+))?(?![-\w])'
    )


def _get_value(section: str, flag: str) -> Optional[str]:
    match = _value_re(flag).search(section)
    if not match:
        return None
    value = match.group(0).split("=", 1)[1]
    return value.strip('"')


def _has_flag(section: str, flag: str) -> bool:
    return _any_form_re(flag).search(section) is not None


def _insert_token(section: str, token: str) -> str:
    """Вставляет токен после фильтра секции (или в конец секции)."""
    match = re.search(
        rf'{_NOT_FLAG_START}--filter-(?:tcp|udp)=(?:"[^"]*"|[^\s^]+)', section
    )
    if match:
        return section[: match.end()] + " " + token + section[match.end():]
    return section.rstrip() + " " + token


def _set_value(section: str, flag: str, value: str) -> str:
    pattern = _value_re(flag)
    token = f"--{flag}={value}"
    if pattern.search(section):
        return pattern.sub(token, section, count=1)
    return _insert_token(section, token)


def _update_if_present(section: str, flag: str, value: str) -> str:
    pattern = _value_re(flag)
    if not pattern.search(section):
        return section
    return pattern.sub(f"--{flag}={value}", section, count=1)


def _remove_flag(section: str, flag: str) -> str:
    pattern = re.compile(
        rf'[ \t]*{_NOT_FLAG_START}--{re.escape(flag)}'
        rf'(?:=(?:"[^"]*"|[^\s^]+))?(?![-\w])'
    )
    return pattern.sub("", section, count=1)


def _set_bool_flag(section: str, flag: str, enabled: bool) -> str:
    if not enabled:
        return _remove_flag(section, flag)
    pattern = _any_form_re(flag)
    if pattern.search(section):
        return pattern.sub(f"--{flag}=1", section, count=1)
    return _insert_token(section, f"--{flag}=1")


def _split_sections(content: str) -> List[str]:
    """Делит батник на секции winws по разделителю ``--new``.

    Нечётные элементы результата — сами разделители ``--new``.
    """
    return _NEW_SPLIT_RE.split(content)


def _section_protocol(section: str) -> Optional[str]:
    if re.search(rf'{_NOT_FLAG_START}--filter-tcp=', section):
        return "tcp"
    if re.search(rf'{_NOT_FLAG_START}--filter-udp=', section):
        return "udp"
    return None


def _as_int(value: Optional[str], default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _read_bat(path: str) -> Tuple[str, bool]:
    with open(path, "rb") as handle:
        raw = handle.read()
    has_bom = raw.startswith(codecs.BOM_UTF8)
    return raw.decode("utf-8-sig", errors="ignore"), has_bom


def _write_bat(path: str, content: str, has_bom: bool) -> None:
    data = content.encode("utf-8")
    if has_bom:
        data = codecs.BOM_UTF8 + data
    with open(path, "wb") as handle:
        handle.write(data)


#: Значения GameFilter, которые обычно выставляет ``service.bat load_game_filter``.
#: service.bat в неинтерактивном режиме не поддерживает часть команд и открывает
#: меню, поэтому переменные считаем сами (заодно чиним старые auto-config.bat,
#: где использовались несуществующие GameFilterTCP/GameFilterUDP).
_GAME_FILTER_BLOCK = (
    'set "GameFilter=12"\r\n'
    'if exist "%~dp0utils\\game_filter.enabled" set "GameFilter=1024-65535"\r\n'
    'set "GameFilterTCP=%GameFilter%"\r\n'
    'set "GameFilterUDP=%GameFilter%"'
)


def _sanitize_bat_for_run(content: str, bat_dir: str) -> str:
    """Убирает интерактивные вызовы service.bat/pause и фиксирует cwd.

    Любой вызов ``service.bat`` из стратегии опасен: неизвестные команды
    (например, ``load_user_lists``) не обрабатываются, и service.bat
    перезапускает себя с правами администратора, открывая меню.
    """
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("::") or lowered.startswith("rem "):
            lines.append(line)
            continue
        if "service.bat" in lowered:
            continue
        if lowered == "pause" or lowered.startswith("pause "):
            continue
        lines.append(line)

    prefix = f'@cd /d "{bat_dir}"'
    body = "\r\n".join(lines)
    return f"{prefix}\r\n{_GAME_FILTER_BLOCK}\r\n{body}\r\n"


# ---------------------------------------------------------------------------
# Проверка доступности целей
# ---------------------------------------------------------------------------

def _probe_with_python(domain: str, timeout: int = 4) -> Tuple[bool, float, str]:
    """Fallback-проверка: TLS-хендшейк с проверкой сертификата."""
    started = time.time()
    context = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=domain) as tls:
                tls.sendall(
                    (
                        f"HEAD / HTTP/1.1\r\nHost: {domain}\r\n"
                        f"User-Agent: {_USER_AGENT}\r\nConnection: close\r\n\r\n"
                    ).encode("ascii", "ignore")
                )
                tls.recv(64)
        elapsed = (time.time() - started) * 1000.0
        return True, round(elapsed, 1), "TLS OK"
    except (OSError, ssl.SSLError):
        return False, 0.0, "TLS FAIL"


def probe_target_with_curl(
    domain: str,
    timeout: int = 4,
    resolve_ip: Optional[str] = None,
    tls_version: Optional[str] = None,
) -> Tuple[bool, float, str]:
    """Проверяет доступность домена через HTTPS (curl, без обхода проверки TLS)."""
    started = time.time()
    url = f"https://{domain}/"
    if "googlevideo" in domain:
        url = f"https://{domain}/generate_204"

    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return _probe_with_python(domain, timeout)

    output_target = "NUL" if os.name == "nt" else "/dev/null"
    command = [
        curl,
        "-4",
        "-sS",
        "-o",
        output_target,
        "-w",
        "%{http_code}",
        "--connect-timeout",
        "3",
        "--max-time",
        str(timeout),
        "--noproxy",
        "*",
        "-A",
        _USER_AGENT,
    ]
    if resolve_ip:
        command += ["--resolve", f"{domain}:443:{resolve_ip}"]
    if tls_version == "1.2":
        command += ["--tls-max", "1.2"]
    elif tls_version == "1.3":
        command += ["--tlsv1.3"]
    command.append(url)

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_NO_WINDOW,
            timeout=timeout + 2,
        )
    except (OSError, subprocess.SubprocessError):
        return _probe_with_python(domain, timeout)

    elapsed = (time.time() - started) * 1000.0
    http_code = (result.stdout or "").strip()
    if result.returncode == 0:
        if http_code.isdigit() and http_code != "000":
            return True, round(elapsed, 1), f"HTTP {http_code}"
        return True, round(elapsed, 1), "CURL OK"
    return False, 0.0, f"FAIL (exit {result.returncode})"


# ---------------------------------------------------------------------------
# Движок
# ---------------------------------------------------------------------------

class FuzzerEngine:
    def __init__(
        self,
        bat_path: str = "general (ALT11).bat",
        log_callback: Optional[Callable[[str], None]] = None,
        status_callback: Optional[Callable[[dict], None]] = None,
        require_100_percent: bool = False,
    ):
        self.bat_path = bat_path
        self.log_callback = log_callback or print
        self.status_callback = status_callback
        self.require_100_percent = require_100_percent
        self.min_success_ratio = 1.0 if require_100_percent else 0.5
        self.is_running = False
        self.target_hosts: List[str] = []
        self.last_result: Tuple[int, int] = (0, 0)
        self.search_mode = "standard"
        self.last_diagnostics: Optional[DiagnosticsReport] = None
        self.resolve_override: dict = {}
        self.probe_tls_version: Optional[str] = None
        self._current_step = 0
        self._total_steps = 0

    def log(self, text: str) -> None:
        if self.log_callback:
            self.log_callback(text)

    def set_status(self, **kwargs) -> None:
        if self.status_callback:
            self.status_callback(kwargs)

    # -- окружение ---------------------------------------------------------

    @staticmethod
    def check_engine_assets(bat_path: str) -> List[str]:
        """Возвращает список отсутствующих файлов движка zapret."""
        if not os.path.isfile(bat_path):
            return [f"Файл стратегии не найден: {bat_path}"]

        bat_dir = os.path.dirname(os.path.abspath(bat_path))
        issues: List[str] = []

        try:
            content, _ = _read_bat(bat_path)
        except OSError as error:
            return [f"Не удалось прочитать {bat_path}: {error}"]

        if "service.bat" in content and not os.path.isfile(os.path.join(bat_dir, "service.bat")):
            issues.append("service.bat — возьмите из архива zapret-discord-youtube")

        engine = detect_engine(content)
        if engine == "winws2":
            required_groups = [
                ("bin/winws2.exe", "winws2.exe"),
                ("bin/WinDivert.dll", "WinDivert.dll"),
                ("bin/WinDivert64.sys", "WinDivert64.sys"),
                ("lua/zapret-lib.lua", "bin/lua/zapret-lib.lua"),
                ("lua/zapret-antidpi.lua", "bin/lua/zapret-antidpi.lua"),
            ]
            for group in required_groups:
                if not any(os.path.isfile(os.path.join(bat_dir, item)) for item in group):
                    issues.append(group[0])
        else:
            for relative in (
                os.path.join("bin", "winws.exe"),
                os.path.join("bin", "WinDivert.dll"),
                os.path.join("bin", "WinDivert64.sys"),
            ):
                if not os.path.isfile(os.path.join(bat_dir, relative)):
                    issues.append(relative)

        lists_dir = os.path.join(bat_dir, "lists")
        if not os.path.isdir(lists_dir):
            issues.append("lists/")
        elif not os.path.isfile(os.path.join(lists_dir, "list-general.txt")):
            issues.append(os.path.join("lists", "list-general.txt"))

        return issues

    @staticmethod
    def flush_dns_cache() -> None:
        try:
            subprocess.run(
                ["ipconfig", "/flushdns"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    @staticmethod
    def is_winws_alive() -> bool:
        for image in ("winws.exe", "winws2.exe"):
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    creationflags=_NO_WINDOW,
                    timeout=10,
                )
                if image in (result.stdout or "").lower():
                    return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False

    @staticmethod
    def stop_winws() -> None:
        for image in ("winws.exe", "winws2.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", image],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_NO_WINDOW,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError):
                pass

    @staticmethod
    def _stop_windivert() -> None:
        if os.name != "nt":
            return
        for command in (["net", "stop", "WinDivert"], ["sc", "stop", "WinDivert"]):
            try:
                subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_NO_WINDOW,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError):
                pass

    @staticmethod
    def reset_windivert() -> None:
        FuzzerEngine.stop_winws()
        FuzzerEngine._stop_windivert()

    def _start_bat_process(self, bat_path: str) -> bool:
        bat_dir = os.path.dirname(os.path.abspath(bat_path))
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["cmd.exe", "/c", os.path.abspath(bat_path)],
                    cwd=bat_dir,
                    creationflags=_NO_WINDOW,
                )
            else:
                subprocess.Popen(["/bin/sh", os.path.abspath(bat_path)], cwd=bat_dir)
        except OSError:
            return False
        return True

    def _wait_until_alive(self, timeout: float = 6.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running:
                return False
            if self.is_winws_alive():
                return True
            time.sleep(0.25)
        return False

    @classmethod
    def start_winws(cls, bat_path: str) -> bool:
        """Запускает стратегию как отдельный процесс winws.exe."""
        if not os.path.isfile(bat_path):
            return False

        content, has_bom = _read_bat(bat_path)
        bat_dir = os.path.dirname(os.path.abspath(bat_path))
        temp_bat = os.path.join(bat_dir, "_fuzzer_run.bat")

        try:
            _write_bat(temp_bat, _sanitize_bat_for_run(content, bat_dir), has_bom)
        except OSError:
            return False

        cls.stop_winws()
        cls._stop_windivert()
        time.sleep(0.8)

        process = cls()
        if not process._start_bat_process(temp_bat):
            return False

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if cls.is_winws_alive():
                return True
            time.sleep(0.25)
        return False

    # -- списки хостов -----------------------------------------------------

    def sync_hosts_to_user_list(self, hosts: List[str]) -> None:
        """Добавляет целевые домены в list-general-user.txt, уважая исключения."""
        bat_dir = os.path.dirname(os.path.abspath(self.bat_path))
        lists_dir = os.path.join(bat_dir, "lists")
        store = UserLists(lists_dir)

        try:
            store.ensure()
        except OSError as error:
            self.log(f"  [!] Не удалось создать {lists_dir}: {error}")
            return

        excluded = set(store.load(EXCLUDE))
        allowed = [host for host in hosts if host.lower() not in excluded]
        skipped = len(hosts) - len(allowed)
        if skipped:
            self.log(
                f"  [i] Пропущено {skipped} доменов из list-exclude-user.txt "
                "(исключения имеют приоритет)."
            )

        try:
            added, invalid = store.add(INCLUDE, allowed)
        except OSError as error:
            self.log(f"  [!] Ошибка записи пользовательского списка: {error}")
            return

        if added:
            self.log(
                f"  [+] Добавлено {added} доменов в "
                f"'{os.path.basename(store.path(INCLUDE))}'."
            )
        if invalid:
            self.log(f"  [!] Пропущено некорректных строк: {len(invalid)}")

    @classmethod
    def sanitize_and_filter_targets(cls, targets: List[str]) -> List[str]:
        valid: List[str] = []
        seen: Set[str] = set()

        for raw in targets:
            cleaned = str(raw).strip().lower()
            if not cleaned or cleaned in seen:
                continue
            try:
                ipaddress.ip_address(cleaned)
                continue
            except ValueError:
                pass
            if is_valid_domain(cleaned):
                valid.append(cleaned)
                seen.add(cleaned)
        return valid

    # -- чтение/запись параметров -----------------------------------------

    def extract_baseline(self) -> WinwsParams:
        if not os.path.isfile(self.bat_path):
            raise FileNotFoundError(f"Файл '{self.bat_path}' не найден!")

        content, _ = _read_bat(self.bat_path)
        parts = _split_sections(content)
        tcp_sections = [
            parts[index]
            for index in range(0, len(parts), 2)
            if _section_protocol(parts[index]) == "tcp"
        ]
        if not tcp_sections:
            return WinwsParams()

        preferred = next(
            (section for section in tcp_sections if "list-general" in section),
            tcp_sections[0],
        )

        def first_tcp_value(flag: str) -> Optional[str]:
            for section in tcp_sections:
                value = _get_value(section, flag)
                if value is not None:
                    return value
            return None

        return WinwsParams(
            tcp_split=_as_int(_get_value(preferred, "dpi-desync-split-pos"), 1),
            tcp_seqovl=_as_int(_get_value(preferred, "dpi-desync-split-seqovl"), 664),
            tcp_ttl=_as_int(_get_value(preferred, "dpi-desync-ttl"), 0),
            desync_mode=_get_value(preferred, "dpi-desync") or "split",
            fooling_mode=_get_value(preferred, "dpi-desync-fooling") or "none",
            udp_repeats=_as_int(first_tcp_value("dpi-desync-repeats"), 8),
            udp_cutoff=first_tcp_value("dpi-desync-cutoff") or "n4",
            any_protocol=any(
                _has_flag(section, "dpi-desync-any-protocol") for section in tcp_sections
            ),
        )

    def generate_mutations(self, baseline: WinwsParams) -> Generator[WinwsParams, None, None]:
        """Генерирует набор мутаций стратегии (без повторов)."""
        visited: Set[Tuple] = {baseline.to_key()}

        priority_combos = [
            WinwsParams(tcp_split=2, tcp_seqovl=681, tcp_ttl=3, desync_mode="fake,split2", fooling_mode="md5sig", udp_repeats=6, udp_cutoff="n3", any_protocol=True),
            WinwsParams(tcp_split=3, tcp_seqovl=681, tcp_ttl=4, desync_mode="fake,disorder2", fooling_mode="badsum", udp_repeats=8, udp_cutoff="d2", any_protocol=True),
            WinwsParams(tcp_split=2, tcp_seqovl=500, tcp_ttl=3, desync_mode="split2", fooling_mode="none", udp_repeats=10, udp_cutoff="n2", any_protocol=False),
            WinwsParams(tcp_split=4, tcp_seqovl=800, tcp_ttl=5, desync_mode="disorder2", fooling_mode="md5sig", udp_repeats=6, udp_cutoff="d3", any_protocol=True),
            WinwsParams(tcp_split=1, tcp_seqovl=300, tcp_ttl=3, desync_mode="fake", fooling_mode="badseq", udp_repeats=12, udp_cutoff="n4", any_protocol=False),
            WinwsParams(tcp_split=3, tcp_seqovl=1000, tcp_ttl=7, desync_mode="syndata", fooling_mode="none", udp_repeats=8, udp_cutoff="d4", any_protocol=True),
            WinwsParams(tcp_split=2, tcp_seqovl=664, tcp_ttl=4, desync_mode="oob", fooling_mode="md5sig", udp_repeats=6, udp_cutoff="n3", any_protocol=True),
        ]

        def emit(params: WinwsParams):
            key = params.to_key()
            if key not in visited:
                visited.add(key)
                return params
            return None

        for combo in priority_combos:
            if emit(combo):
                yield combo

        for mode in ["split", "split2", "disorder", "disorder2", "fake,split2", "fake,disorder2", "oob", "syndata"]:
            if mode != baseline.desync_mode:
                mutated = copy.copy(baseline)
                mutated.desync_mode = mode
                if emit(mutated):
                    yield mutated

        for fooling in ["none", "md5sig", "badsum", "badseq"]:
            if fooling != baseline.fooling_mode:
                mutated = copy.copy(baseline)
                mutated.fooling_mode = fooling
                if emit(mutated):
                    yield mutated

        for pos in [2, 3, 4]:
            for ttl in [3, 4, 5, 7]:
                mutated = copy.copy(baseline)
                mutated.tcp_split = pos
                mutated.tcp_ttl = ttl
                if emit(mutated):
                    yield mutated

        for seqovl in [681, 500, 300, 800, 1000, 1200, 0]:
            if seqovl != baseline.tcp_seqovl:
                mutated = copy.copy(baseline)
                mutated.tcp_seqovl = seqovl
                if emit(mutated):
                    yield mutated

        for any_protocol in [True, False]:
            if any_protocol != baseline.any_protocol:
                mutated = copy.copy(baseline)
                mutated.any_protocol = any_protocol
                if emit(mutated):
                    yield mutated

        for cutoff in ["n2", "n3", "n4", "d2", "d3", "d4"]:
            if cutoff != baseline.udp_cutoff:
                mutated = copy.copy(baseline)
                mutated.udp_cutoff = cutoff
                if emit(mutated):
                    yield mutated

        for repeats in [6, 10, 12, 15, 4]:
            if repeats != baseline.udp_repeats:
                mutated = copy.copy(baseline)
                mutated.udp_repeats = repeats
                if emit(mutated):
                    yield mutated

    def _apply_params_to_cmdline(self, content: str, params: WinwsParams) -> str:
        """Правит только релевантные секции, сохраняя остальные флаги."""
        validate_params(params)
        parts = _split_sections(content)

        for index in range(0, len(parts), 2):
            section = parts[index]
            protocol = _section_protocol(section)
            if protocol is None:
                continue

            if protocol == "tcp":
                section = _set_value(section, "dpi-desync", params.desync_mode)
                section = _set_value(section, "dpi-desync-split-pos", str(params.tcp_split))

                if params.tcp_seqovl > 0:
                    section = _set_value(section, "dpi-desync-split-seqovl", str(params.tcp_seqovl))
                else:
                    section = _remove_flag(section, "dpi-desync-split-seqovl")

                if params.tcp_ttl > 0:
                    section = _set_value(section, "dpi-desync-ttl", str(params.tcp_ttl))
                else:
                    section = _remove_flag(section, "dpi-desync-ttl")

                if params.fooling_mode and params.fooling_mode != "none":
                    section = _set_value(section, "dpi-desync-fooling", params.fooling_mode)
                else:
                    section = _remove_flag(section, "dpi-desync-fooling")

                section = _set_bool_flag(
                    section, "dpi-desync-any-protocol", params.any_protocol
                )

            # Repeats/cutoff есть и в TCP-, и в UDP-секциях; обновляем там,
            # где они уже используются, не добавляя UDP-специфичных флагов в TCP.
            section = _update_if_present(section, "dpi-desync-repeats", str(params.udp_repeats))
            section = _update_if_present(section, "dpi-desync-cutoff", params.udp_cutoff)
            parts[index] = section

        return "".join(parts)

    def create_and_run_temp_bat(
        self,
        params: Optional[WinwsParams] = None,
        content: Optional[str] = None,
    ) -> str:
        original, has_bom = _read_bat(self.bat_path)
        bat_dir = os.path.dirname(os.path.abspath(self.bat_path))
        temp_bat = os.path.join(bat_dir, "_fuzzer_temp.bat")

        if content is not None:
            prepared = _sanitize_bat_for_run(content, bat_dir)
        else:
            prepared = _sanitize_bat_for_run(original, bat_dir)
            if params is not None:
                prepared = self._apply_params_to_cmdline(prepared, params)

        _write_bat(temp_bat, prepared, has_bom)

        self.stop_winws()
        self._stop_windivert()
        time.sleep(0.5)

        self._start_bat_process(temp_bat)
        return temp_bat

    # -- оценка стратегий --------------------------------------------------

    def _evaluate_config_sync(
        self, target_domains: List[str], attempts: int = 1
    ) -> Tuple[int, List[Tuple[str, bool, float, str]]]:
        passed = 0
        results: List[Tuple[str, bool, float, str]] = []

        if not target_domains:
            return 0, results

        attempts = max(1, attempts)
        jobs = [(domain, number) for domain in target_domains for number in range(attempts)]
        collected: dict[str, List[Tuple[bool, float, str]]] = {
            domain: [] for domain in target_domains
        }
        workers = min(12, max(1, len(jobs)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    probe_target_with_curl,
                    domain,
                    4,
                    self.resolve_override.get(domain),
                    self.probe_tls_version,
                ): (domain, number)
                for domain, number in jobs
            }
            for future in concurrent.futures.as_completed(futures):
                domain, _number = futures[future]
                try:
                    collected[domain].append(future.result())
                except Exception:
                    collected[domain].append((False, 0.0, "FAIL"))
                if not self.is_running:
                    for pending in futures:
                        pending.cancel()
                    break

        for domain in target_domains:
            outcomes = collected[domain]
            if not outcomes:
                continue
            ok = all(item[0] for item in outcomes)
            latency = max((item[1] for item in outcomes), default=0.0)
            proto = outcomes[-1][2]
            if attempts > 1:
                proto = f"{proto} [{sum(1 for item in outcomes if item[0])}/{attempts}]"
            if ok:
                passed += 1
            results.append((domain, ok, latency, proto))

        return passed, results

    def evaluate_config(
        self,
        params: WinwsParams,
        target_domains: List[str],
        label: str = "МУТАЦИЯ",
        min_success_ratio: Optional[float] = None,
        apply_params: bool = True,
        attempts: int = 1,
    ) -> bool:
        self.log(f"\n[*] ТЕСТИРУЕМ: {label}")
        self.log(f"    {params.describe()}")

        self.set_status(params=params, current_step=label)

        temp_bat = self.create_and_run_temp_bat(params if apply_params else None)
        started = time.monotonic()

        if not self._wait_until_alive(6.0):
            if self.is_running:
                self.log("  [!] ОШИБКА: процесс winws.exe не запустился или завершился.")
            if os.path.exists(temp_bat):
                try:
                    os.remove(temp_bat)
                except OSError:
                    pass
            self.last_result = (0, len(target_domains))
            return False

        if min_success_ratio is None:
            min_success_ratio = self.min_success_ratio
        total_hosts = len(target_domains)
        required_success = max(1, int(math.ceil(total_hosts * min_success_ratio)))

        self.log(
            f"  [~] Проверка через HTTPS (нужно: {required_success}/{total_hosts}, "
            f"попыток на домен: {attempts})..."
        )
        try:
            passed_count, results = self._evaluate_config_sync(target_domains, attempts)
        except Exception as error:  # защита от неожиданностей в пуле потоков
            self.log(f"  [!] Ошибка проверки: {error}")
            passed_count, results = 0, []

        for domain, ok, latency, proto in results:
            status_str = (
                f"[O] Доступен ({proto}, {latency:.0f} ms)" if ok else "[X] Заблокирован"
            )
            self.log(f"      -> {domain:35} {status_str}")

        elapsed = time.monotonic() - started
        is_success = passed_count >= required_success
        icon = "[+]" if is_success else "[-]"
        self.log(
            f"  {icon} Результат: {passed_count}/{total_hosts} за {elapsed:.1f} сек. "
            f"(порог: {required_success})"
        )

        self.last_result = (passed_count, total_hosts)
        self.set_status(
            params=params,
            passed=passed_count,
            total_hosts=total_hosts,
            elapsed_sec=int(elapsed),
        )

        self.stop_winws()
        time.sleep(0.5)
        if os.path.exists(temp_bat):
            try:
                os.remove(temp_bat)
            except OSError:
                pass

        return is_success

    # -- сценарии ----------------------------------------------------------

    def _record_session(
        self,
        params: Optional[WinwsParams],
        targets: List[str],
        success: bool,
        extra: Optional[dict] = None,
    ) -> None:
        try:
            from presets import add_session

            passed, total = self.last_result
            record = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "strategy_file": os.path.basename(self.bat_path),
                "params": asdict(params) if params is not None else {},
                "target_hosts": list(targets),
                "passed_count": passed,
                "total_count": total,
                "success": bool(success),
            }
            if extra:
                record.update(extra)
            add_session(record)
        except Exception as error:
            self.log(f"  [!] Не удалось сохранить сессию в историю: {error}")

    def patch_original_bat(self, params: WinwsParams) -> None:
        backup_path = self.bat_path + ".bak"
        if not os.path.exists(backup_path):
            shutil.copy2(self.bat_path, backup_path)
            self.log(f"\n[i] Создан бэкап: {backup_path}")

        content, has_bom = _read_bat(self.bat_path)
        updated = self._apply_params_to_cmdline(content, params)
        _write_bat(self.bat_path, updated, has_bom)
        self.log(
            f"  [+] Конфиг '{os.path.basename(self.bat_path)}' обновлён рабочей стратегией."
        )

    def _prepare_targets(self, target_domains: List[str]) -> Optional[List[str]]:
        cleaned = self.sanitize_and_filter_targets(target_domains)
        if not cleaned:
            self.log("[!] Ошибка: передан пустой или некорректный список хостов.")
            self.set_status(state="FAILED", message="Некорректные цели")
            return None

        self.log("[*] Синхронизация доменов с lists/list-general-user.txt...")
        self.sync_hosts_to_user_list(cleaned)

        self.log("[*] Очистка кэша DNS...")
        self.flush_dns_cache()
        return cleaned

    def _check_assets(self) -> bool:
        issues = self.check_engine_assets(self.bat_path)
        if not issues:
            return True
        self.log("[!] Не хватает файлов движка zapret рядом с приложением:")
        for issue in issues:
            self.log(f"      - {issue}")
        self.log("    Возьмите полный архив zapret-discord-youtube (bin/, lists/, service.bat).")
        self.set_status(state="ERROR", message="Комплект движка zapret не найден")
        return False

    def run_single_test(self, params: WinwsParams, target_domains: List[str]) -> bool:
        """Разовый тест пользовательских параметров."""
        self.is_running = True
        try:
            self.log("=== Zapret Fuzzer: разовый тест параметров ===")
            if not self._check_assets():
                return False

            cleaned = self._prepare_targets(target_domains)
            if cleaned is None:
                return False

            self.target_hosts = cleaned
            success = self.evaluate_config(params, cleaned, label="РАЗОВЫЙ ТЕСТ")
            self._record_session(params, cleaned, success)

            if success:
                self.set_status(state="SUCCESS", message="Разовый тест прошёл успешно!", params=params)
            else:
                self.set_status(state="FAILED", message="Разовый тест не прошёл порог")
            return success
        except Exception as error:
            self.log(f"[!] Ошибка во время разового теста: {error}")
            self.set_status(state="ERROR", message=str(error))
            return False
        finally:
            self.is_running = False

    def detect_engine_type(self) -> str:
        content, _ = _read_bat(self.bat_path)
        return detect_engine(content)

    def _candidate_description(self, candidate: Optional[SearchCandidate]) -> str:
        if candidate is None:
            return "исходный конфиг"
        if candidate.params is not None:
            return candidate.params.describe()
        return candidate.label

    def evaluate_candidate(
        self,
        candidate: Optional[SearchCandidate],
        target_domains: List[str],
        label: str,
        attempts: int = 1,
        min_success_ratio: Optional[float] = None,
        apply_params: bool = True,
    ) -> bool:
        params = candidate.params if candidate is not None else None
        content = candidate.content if candidate is not None else None

        self.log(f"\n[*] {label}")
        self.log(f"    {self._candidate_description(candidate)}")
        self.set_status(
            params=params,
            current_step=label,
            step=self._current_step,
            total_steps=self._total_steps,
        )

        if candidate is None:
            temp_bat = self.create_and_run_temp_bat()
        elif content is not None:
            temp_bat = self.create_and_run_temp_bat(content=content)
        else:
            temp_bat = self.create_and_run_temp_bat(params if apply_params else None)

        started = time.monotonic()
        if not self._wait_until_alive(6.0):
            if self.is_running:
                self.log("  [!] ОШИБКА: winws не запустился или завершился.")
            self._cleanup_temp(temp_bat)
            self.last_result = (0, len(target_domains))
            return False

        if min_success_ratio is None:
            min_success_ratio = self.min_success_ratio
        total_hosts = len(target_domains)
        required_success = max(1, int(math.ceil(total_hosts * min_success_ratio)))

        self.log(
            f"  [~] Проверка HTTPS: нужно {required_success}/{total_hosts}, "
            f"попыток на домен: {attempts}"
        )
        try:
            passed_count, results = self._evaluate_config_sync(target_domains, attempts)
        except Exception as error:
            self.log(f"  [!] Ошибка проверки: {error}")
            passed_count, results = 0, []

        for domain, ok, latency, proto in results:
            status_str = (
                f"[O] {proto}, {latency:.0f} ms" if ok else "[X] заблокирован"
            )
            self.log(f"      -> {domain:35} {status_str}")

        elapsed = time.monotonic() - started
        is_success = passed_count >= required_success
        icon = "[+]" if is_success else "[-]"
        self.log(
            f"  {icon} {passed_count}/{total_hosts} за {elapsed:.1f} сек."
        )

        self.last_result = (passed_count, total_hosts)
        self.set_status(
            params=params,
            passed=passed_count,
            total_hosts=total_hosts,
            elapsed_sec=int(elapsed),
        )

        self.stop_winws()
        time.sleep(0.4)
        self._cleanup_temp(temp_bat)
        return is_success

    @staticmethod
    def _cleanup_temp(temp_bat: str) -> None:
        if temp_bat and os.path.exists(temp_bat):
            try:
                os.remove(temp_bat)
            except OSError:
                pass

    def _build_candidates(
        self, mode: str
    ) -> Tuple[str, Optional[object], List[SearchCandidate]]:
        engine = self.detect_engine_type()
        cap = {"quick": 120, "standard": 350, "deep": 1000}.get(mode, 350)

        if engine == "winws2":
            content, _ = _read_bat(self.bat_path)
            model = parse_winws2(content)
            self.log(f"  [i] winws2: {model.describe()}")
            if not model.groups:
                self.log("  [!] В батнике не найдены Lua-профили.")
                return engine, model, []
            quotas = {
                "quick": {"tls": 70, "http": 25, "quic": 25},
                "standard": {"tls": 220, "http": 60, "quic": 40},
                "deep": {"tls": 500, "http": 120, "quic": 80},
            }.get(mode, {"tls": 220, "http": 60, "quic": 40})
            candidates: List[SearchCandidate] = []
            for family, quota in quotas.items():
                candidates.extend(
                    itertools.islice(winws2_candidates(model, mode, family), quota)
                )
            return engine, model, candidates

        baseline = self.extract_baseline()
        self.log(f"  [i] winws1: {baseline.describe()}")
        generator = winws1_candidates(baseline, mode)
        return engine, None, list(itertools.islice(generator, cap))

    def _minimize_candidate(
        self,
        winner: SearchCandidate,
        targets: List[str],
        engine: str,
        model,
        mode: str,
    ) -> SearchCandidate:
        if mode == "quick":
            return winner

        self.log("\n[*] Минимизация найденной стратегии...")
        if engine == "winws1" and winner.params is not None:
            generator = minimize_winws1_candidates(winner.params, mode)
        elif engine == "winws2" and model is not None and winner.edits:
            generator = minimize_winws2_candidates(model, winner, mode)
        else:
            return winner

        best = winner
        for index, variant in enumerate(itertools.islice(generator, 14), 1):
            if not self.is_running:
                break
            self.log(f"  [~] Вариант {index}: {variant.label}")
            if self.evaluate_candidate(variant, targets, "МИНИМИЗАЦИЯ", attempts=1):
                best = variant
                self.log(f"  [+] Оставлено: {variant.label}")
            else:
                self.log("  [-] Не подошло, возвращаем предыдущий вариант.")
        return best

    def _write_auto_config(self, candidate: Optional[SearchCandidate], engine: str) -> Optional[str]:
        original, has_bom = _read_bat(self.bat_path)
        bat_dir = os.path.dirname(os.path.abspath(self.bat_path))

        if engine == "winws2":
            content = candidate.content if candidate is not None and candidate.content else original
        elif candidate is not None and candidate.params is not None:
            content = self._apply_params_to_cmdline(original, candidate.params)
        else:
            content = original

        prepared = _sanitize_bat_for_run(content, bat_dir)
        auto_path = os.path.join(bat_dir, "auto-config.bat")
        try:
            _write_bat(auto_path, prepared, has_bom)
        except OSError as error:
            self.log(f"  [!] Не удалось записать auto-config.bat: {error}")
            return None
        return auto_path

    def _start_and_verify(self, auto_path: str, canary: str) -> bool:
        if not auto_path or not os.path.isfile(auto_path):
            return False
        self.log(f"  [*] Запуск {os.path.basename(auto_path)}...")
        if not self.start_winws(auto_path):
            self.log("  [!] winws не запустился с новым конфигом.")
            return False
        ok, _, proto = probe_target_with_curl(
            canary, 4, self.resolve_override.get(canary), self.probe_tls_version
        )
        if ok:
            self.log(f"  [+] Проверка после запуска: {canary} -> {proto}")
            return True
        self.log("  [!] После запуска canary не открылся.")
        self.stop_winws()
        return False

    def _finish_success(
        self,
        candidate: Optional[SearchCandidate],
        engine: str,
        targets: List[str],
        report: Optional[DiagnosticsReport],
    ) -> bool:
        auto_path = self._write_auto_config(candidate, engine)
        if not auto_path:
            self.set_status(state="ERROR", message="Не удалось записать конфиг")
            return False

        canary = (report.canary if report else targets[0]) or targets[0]
        if not self._start_and_verify(auto_path, canary):
            self.set_status(state="ERROR", message="Конфиг записан, но winws не запустился")
            return False

        self.log(f"\n[+] ГОТОВО. Рабочий конфиг: {auto_path}")
        self.log("    winws запущен и проверен. Можно пользоваться.")
        extra = {
            "engine": engine,
            "strategy_label": candidate.label if candidate else "базовый конфиг",
            "auto_config": os.path.basename(auto_path),
            "diagnostics": report.summary_lines() if report else [],
        }
        self._record_session(
            candidate.params if candidate is not None else None,
            targets,
            True,
            extra,
        )
        self.set_status(
            state="SUCCESS",
            message="Готово: стратегия подобрана и запущена",
            params=candidate.params if candidate is not None else None,
        )
        return True

    def _restore_original(self) -> None:
        if not self.is_running:
            return
        try:
            self.start_winws(self.bat_path)
            self.log(f"  [i] Возвращён исходный конфиг: {os.path.basename(self.bat_path)}")
        except Exception:
            pass

    def run_fuzzing(self, target_domains: List[str]) -> bool:
        """Полная автонастройка: диагностика → поиск → минимизация → запуск."""
        self.is_running = True
        self._current_step = 0
        self._total_steps = 0
        self.resolve_override = {}
        self.probe_tls_version = None
        try:
            self.log("=== Автоматическая настройка Zapret ===")
            self.log(f"Целевых доменов: {len(target_domains)}")
            self.log(f"Режим поиска: {self.search_mode}")

            if not self._check_assets():
                return False

            cleaned = self._prepare_targets(target_domains)
            if cleaned is None:
                return False
            self.target_hosts = cleaned

            engine = self.detect_engine_type()
            self.log(f"Движок: {engine}")

            self.stop_winws()
            self._stop_windivert()
            time.sleep(0.5)

            self.set_status(
                state="DIAGNOSTICS", message="Диагностика сети...",
                step=0, total_steps=0,
            )
            def diagnostic_log(text: str) -> None:
                self.log(text)
                stripped = text.strip()
                if stripped.startswith(("[~]", "[i]", "[!]")):
                    message = stripped[3:].strip() or stripped
                    self.set_status(state="DIAGNOSTICS", message=message)

            try:
                report = run_diagnostics(
                    cleaned,
                    diagnostic_log,
                    should_continue=lambda: self.is_running,
                )
            except Exception as error:
                self.log(f"  [!] Диагностика не удалась: {error}")
                report = None
            self.last_diagnostics = report
            if not self.is_running:
                self.set_status(state="STOPPED", message="Остановлено пользователем")
                return False

            if report is not None:
                if report.dns_poisoned:
                    self.resolve_override = {}
                    for domain in report.dns_poisoned:
                        ip = next(
                            (item for item in sorted(report.doh_ips.get(domain, set()))
                             if ":" not in item),
                            None,
                        )
                        if ip:
                            self.resolve_override[domain] = ip
                    self.log(
                        "  [!] DNS подменён. Для проверок использую IP из DoH, "
                        "но для браузера включите DoH/DoT или hosts."
                    )

                if report.block_type == "tls13":
                    self.probe_tls_version = "1.3"
                elif report.block_type == "tls12_server_hello":
                    self.probe_tls_version = "1.2"

                if report.dns_poisoned and not report.bypass_needed:
                    self.log("\n[!] Подменён DNS, но DPI не мешает.")
                    self.log("    winws здесь не поможет: включите DoH/DoT или пропишите IP в hosts.")
                    self._restore_original()
                    self.set_status(
                        state="FAILED",
                        message="DNS подменён — настройте DoH/DoT",
                    )
                    return False

                if not report.bypass_needed:
                    self.log("\n[+] Все выбранные сервисы уже доступны без обхода. Конфиг не меняю.")
                    self._restore_original()
                    self.set_status(
                        state="SUCCESS",
                        message="Обход не требуется — сервисы доступны",
                    )
                    return True

                if report.block_type == "ip" or report.ip_block in (
                    "full",
                    "full_or_partial",
                ):
                    self.log("\n[!] Похоже на полный блок по IP/порту.")
                    self.log("    Стратегии zapret такой блок не обходят — нужен прокси/VPN.")
                    self._restore_original()
                    self.set_status(
                        state="FAILED",
                        message="Блок по IP: обход стратегией невозможен",
                    )
                    return False

            canary = (report.canary if report else cleaned[0]) or cleaned[0]
            self.log(f"  [i] Canary-домен для быстрой проверки: {canary}")

            engine, model, candidates = self._build_candidates(self.search_mode)
            baseline_params = None
            if engine == "winws1":
                baseline_params = self.extract_baseline()

            self._total_steps = len(candidates) + 1
            self._current_step = 1
            self.log("\n[*] Проверка исходного конфига без изменений...")
            if engine == "winws1" and baseline_params is not None:
                baseline_candidate = SearchCandidate(
                    label="БАЗОВЫЙ КОНФИГ", stage=0, engine="winws1",
                    params=baseline_params,
                )
                baseline_ok = self.evaluate_candidate(
                    baseline_candidate, cleaned, "БАЗОВЫЙ КОНФИГ",
                    attempts=1, apply_params=False,
                )
            else:
                baseline_ok = self.evaluate_candidate(
                    None, cleaned, "БАЗОВЫЙ КОНФИГ", attempts=1
                )

            if baseline_ok:
                self.log("\n[+] Исходный конфиг уже работает.")
                return self._finish_success(None, engine, cleaned, report)

            if not candidates:
                self.log("\n[-] Нет кандидатов для выбранного движка/конфига.")
                self._restore_original()
                self.set_status(state="FAILED", message="Нет кандидатов для поиска")
                return False

            self.log(
                f"\n[-] Исходный конфиг не сработал. Кандидатов: {len(candidates)}. "
                f"Сначала canary, затем все домены."
            )

            search_attempts = {"quick": 1, "standard": 2, "deep": 2}.get(
                self.search_mode, 2
            )
            final_attempts = 3 if self.search_mode == "deep" else 2
            budget = candidate_time_budget(self.search_mode)
            search_started = time.monotonic()

            for index, candidate in enumerate(candidates, 1):
                if not self.is_running:
                    self.log("\n[!] Остановлено пользователем.")
                    self.set_status(state="STOPPED", message="Остановлено пользователем")
                    return False

                if time.monotonic() - search_started > budget:
                    self.log(
                        f"\n[!] Лимит времени поиска ({budget // 60} мин) исчерпан."
                    )
                    break

                self._current_step = index + 1
                self.set_status(
                    step=self._current_step,
                    total_steps=self._total_steps,
                    current_step=candidate.label,
                )
                self.log(f"\n[{index}/{len(candidates)}] {candidate.label}")

                if not self.evaluate_candidate(
                    candidate, [canary], f"CANARY: {candidate.label}",
                    attempts=1, min_success_ratio=1.0,
                ):
                    continue

                self.log("  [~] Canary пройден — подтверждаю на всех доменах...")
                if not self.evaluate_candidate(
                    candidate, cleaned, f"ПОДТВЕРЖДЕНИЕ: {candidate.label}",
                    attempts=search_attempts,
                ):
                    continue

                winner = candidate
                if self.search_mode != "quick":
                    winner = self._minimize_candidate(
                        candidate, cleaned, engine, model, self.search_mode
                    )

                self.log("\n[*] Финальная проверка стабильности...")
                if not self.evaluate_candidate(
                    winner, cleaned, "ФИНАЛЬНАЯ ПРОВЕРКА",
                    attempts=final_attempts,
                ):
                    self.log("  [-] Стратегия нестабильна, продолжаю поиск.")
                    continue

                return self._finish_success(winner, engine, cleaned, report)

            self.log("\n[-] Рабочая стратегия не найдена.")
            if report is not None:
                self.log(
                    "    Диагноз: "
                    + report.block_type
                    + ". Попробуйте режим «Глубокий» или другие домены."
                )
            self._record_session(
                baseline_params, cleaned, False,
                {
                    "engine": engine,
                    "strategy_label": "не найдено",
                    "diagnostics": report.summary_lines() if report else [],
                },
            )
            self._restore_original()
            self.set_status(state="FAILED", message="Стратегия не найдена")
            return False
        except Exception as error:
            self.log(f"\n[!] Ошибка автонастройки: {error}")
            self.set_status(state="ERROR", message=str(error))
            return False
        finally:
            self.is_running = False

    def stop(self) -> None:
        self.is_running = False
        self.stop_winws()
