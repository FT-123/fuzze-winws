"""Диагностика блокировки до подбора стратегии.

Определяет:
* подмену DNS (системный резолв vs DoH);
* доступность без обхода по HTTP / TLS 1.2 / TLS 1.3 / QUIC;
* вероятный блок по IP;
* какой домен использовать как canary и какие семейства стратегий пробовать.
"""
import concurrent.futures
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from config import APP_DIR  # noqa: F401 (путь приложения для будущего кэша)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_DOH_SERVERS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)
_PROBE_TARGET = "iana.org"


@dataclass
class ProbeOutcome:
    ok: bool
    http_code: str = ""
    redirect: str = ""
    latency_ms: float = 0.0
    exit_code: int = -1
    error: str = ""

    def summary(self) -> str:
        if self.ok:
            code = self.http_code or "OK"
            redirect = f" -> {self.redirect}" if self.redirect else ""
            return f"{code}{redirect}"
        if self.exit_code >= 0:
            return f"fail (curl {self.exit_code})"
        return self.error or "fail"


@dataclass
class DiagnosticsReport:
    domains: List[str]
    dns_ips: Dict[str, Set[str]] = field(default_factory=dict)
    doh_ips: Dict[str, Set[str]] = field(default_factory=dict)
    dns_poisoned: List[str] = field(default_factory=list)
    http_ok: bool = False
    tls12_ok: bool = False
    tls13_ok: bool = False
    tls13_supported: bool = True
    quic_ok: bool = False
    quic_supported: bool = False
    ip_block: str = "unknown"
    canary: str = ""
    bypass_needed: bool = True
    block_type: str = "unknown"
    notes: List[str] = field(default_factory=list)
    probe_ip: Optional[str] = None

    def summary_lines(self) -> List[str]:
        lines = ["", "=== Диагностика блокировки ==="]
        if self.dns_poisoned:
            lines.append(
                "  [!] Похоже на подмену DNS: "
                + ", ".join(self.dns_poisoned[:5])
            )
            lines.append("      DNS-подмену winws не исправляет — нужен DoH/DoT или hosts.")
        else:
            lines.append("  [i] Подмена DNS не обнаружена.")

        lines.append(
            f"  [i] Без обхода: HTTP={'OK' if self.http_ok else 'FAIL'}, "
            f"TLS1.2={'OK' if self.tls12_ok else 'FAIL'}, "
            f"TLS1.3={'OK' if self.tls13_ok else ('FAIL' if self.tls13_supported else 'н/д')}, "
            f"QUIC={'OK' if self.quic_ok else ('FAIL' if self.quic_supported else 'н/д')}"
        )
        if self.probe_ip:
            lines.append(f"  [i] IP для проверок (DoH): {self.probe_ip}")
        lines.append(f"  [i] Вероятный тип блока: {self.block_type}, canary: {self.canary}")
        if self.ip_block != "unknown":
            lines.append(f"  [i] IP-блок: {self.ip_block}")
        for note in self.notes:
            lines.append(f"  [i] {note}")
        return lines


def curl_path() -> Optional[str]:
    import shutil

    return shutil.which("curl.exe") or shutil.which("curl")


def curl_supports_http3() -> bool:
    curl = curl_path()
    if not curl:
        return False
    try:
        output = subprocess.check_output(
            [curl, "--version"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "HTTP3" in output or "HTTP/3" in output


def resolve_system(domain: str, timeout: float = 3.0) -> Set[str]:
    try:
        infos = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return set()
    return {info[4][0] for info in infos if info[4]}


def resolve_doh(domain: str, timeout: float = 3.0) -> Set[str]:
    query = urllib.parse.urlencode({"name": domain, "type": "A"})
    for server in _DOH_SERVERS:
        url = f"{server}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/dns-json", "User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError):
            continue
        answers = data.get("Answer") or []
        ips = {
            str(answer.get("data"))
            for answer in answers
            if answer.get("type") in (1, 28) and answer.get("data")
        }
        if ips:
            return ips
    return set()


def dns_looks_poisoned(system_ips: Set[str], doh_ips: Set[str]) -> bool:
    if not system_ips or not doh_ips:
        return False
    return not (system_ips & doh_ips)


def probe_url(
    domain: str,
    scheme: str = "https",
    port: int = 443,
    tls_version: Optional[str] = None,
    resolve_ip: Optional[str] = None,
    insecure: bool = False,
    timeout: int = 4,
    http3: bool = False,
) -> ProbeOutcome:
    """Один запрос через curl. Без -k по умолчанию проверяется сертификат."""
    curl = curl_path()
    if not curl:
        return ProbeOutcome(ok=False, error="curl не найден")

    url = f"{scheme}://{domain}/"
    if "googlevideo" in domain:
        url = f"{scheme}://{domain}/generate_204"

    output_target = "NUL" if os.name == "nt" else "/dev/null"
    command = [
        curl,
        "-4",
        "-sS",
        "-o",
        output_target,
        "-w",
        "%{http_code}\t%{redirect_url}",
        "--connect-timeout",
        "3",
        "--max-time",
        str(timeout),
        "--noproxy",
        "*",
        "-A",
        _USER_AGENT,
    ]
    if tls_version == "1.2":
        command += ["--tls-max", "1.2"]
    elif tls_version == "1.3":
        command += ["--tlsv1.3"]
    if http3:
        command += ["--http3-only"]
    if resolve_ip:
        command += ["--resolve", f"{domain}:{port}:{resolve_ip}"]
    if insecure:
        command += ["-k"]
    command.append(url)

    started = time.time()
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_NO_WINDOW,
            timeout=timeout + 2,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return ProbeOutcome(ok=False, error=str(error))

    elapsed = (time.time() - started) * 1000.0
    raw = (result.stdout or "").strip()
    http_code = ""
    redirect = ""
    if raw:
        parts = raw.split("\t")
        http_code = parts[0].strip() if parts else ""
        redirect = parts[1].strip() if len(parts) > 1 else ""

    ok = result.returncode == 0 and http_code.isdigit() and http_code != "000"
    return ProbeOutcome(
        ok=ok,
        http_code=http_code,
        redirect=redirect,
        latency_ms=round(elapsed, 1),
        exit_code=result.returncode,
    )


def classify_block(
    http_ok: bool,
    tls12_ok: bool,
    tls13_ok: bool,
    quic_ok: bool,
    quic_supported: bool,
    ip_block: str,
) -> str:
    if http_ok and tls12_ok and tls13_ok and quic_supported and not quic_ok:
        return "quic"
    if http_ok and tls12_ok and tls13_ok:
        return "none"
    if ip_block in ("full", "full_or_partial"):
        return "ip"
    if not http_ok and not tls12_ok and not tls13_ok:
        return "tcp_or_all"
    if http_ok and not tls12_ok:
        return "tls12_server_hello"
    if tls12_ok and not tls13_ok:
        return "tls13"
    if tls12_ok and tls13_ok and quic_supported and not quic_ok:
        return "quic"
    if not http_ok and tls12_ok:
        return "http"
    if tls12_ok and tls13_ok:
        return "partial"
    return "unknown"


def _pick_ipv4(ips: Set[str]) -> Optional[str]:
    for ip in sorted(ips):
        if ":" not in ip:
            return ip
    return next(iter(ips), None)


def _resolve_all(
    domains: Sequence[str],
    timeout: float,
    should_continue: Optional[Callable[[], bool]] = None,
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], List[str]]:
    """Параллельно резолвит домены через систему и DoH."""
    system_map: Dict[str, Set[str]] = {}
    doh_map: Dict[str, Set[str]] = {}
    poisoned: List[str] = []

    def resolve_one(domain: str):
        return (
            domain,
            resolve_system(domain, timeout=timeout),
            resolve_doh(domain, timeout=timeout),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(domains)))) as executor:
        futures = {executor.submit(resolve_one, domain): domain for domain in domains}
        for future in concurrent.futures.as_completed(futures):
            if should_continue is not None and not should_continue():
                for pending in futures:
                    pending.cancel()
                break
            domain = futures[future]
            try:
                domain, system_ips, doh_ips = future.result()
            except Exception:
                continue
            system_map[domain] = system_ips
            doh_map[domain] = doh_ips
            if dns_looks_poisoned(system_ips, doh_ips):
                poisoned.append(domain)

    return system_map, doh_map, poisoned


def run_diagnostics(
    domains: Sequence[str],
    log: Callable[[str], None] = print,
    timeout: int = 4,
    should_continue: Optional[Callable[[], bool]] = None,
) -> DiagnosticsReport:
    targets = [domain for domain in domains if domain]
    report = DiagnosticsReport(domains=targets)
    if not targets:
        return report

    def can_continue() -> bool:
        return should_continue is None or should_continue()

    # 1. DNS: системный vs DoH, параллельно.
    log(f"  [~] Проверка DNS для {len(targets)} доменов (система + DoH)...")
    report.dns_ips, report.doh_ips, report.dns_poisoned = _resolve_all(
        targets, timeout=min(2, timeout), should_continue=should_continue
    )
    log(f"  [i] DNS готово. Подозрение на подмену: {len(report.dns_poisoned)}.")
    if not can_continue():
        return report

    # 2. Есть ли в curl поддержка TLS 1.3 вообще.
    log("  [~] Проверка поддержки TLS 1.3...")
    report.tls13_supported = probe_url(
        _PROBE_TARGET, "https", 443, "1.3", timeout=min(3, timeout)
    ).ok
    if not can_continue():
        return report

    # 3. Быстрая параллельная проверка TLS по всем доменам:
    #    выбираем canary и понимаем, нужен ли обход вообще.
    log(f"  [~] Проверка TLS 1.2/1.3 по {len(targets)} доменам...")

    def check_domain(domain: str):
        if domain in report.dns_poisoned:
            ips = report.doh_ips.get(domain, set())
        else:
            ips = report.dns_ips.get(domain, set()) or report.doh_ips.get(domain, set())
        ip = _pick_ipv4(ips)
        tls12 = probe_url(domain, "https", 443, "1.2", resolve_ip=ip, timeout=timeout)
        tls13 = (
            probe_url(domain, "https", 443, "1.3", resolve_ip=ip, timeout=timeout)
            if report.tls13_supported
            else ProbeOutcome(ok=True)
        )
        ok = tls12.ok and tls13.ok
        return domain, ip, ok

    working: Set[str] = set()
    domain_ips: Dict[str, Optional[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
        futures = {executor.submit(check_domain, domain): domain for domain in targets}
        for future in concurrent.futures.as_completed(futures):
            if not can_continue():
                for pending in futures:
                    pending.cancel()
                break
            try:
                domain, ip, ok = future.result()
            except Exception:
                continue
            domain_ips[domain] = ip
            if ok:
                working.add(domain)
            log(f"      · {domain}: {'OK' if ok else 'FAIL'}")

    report.bypass_needed = len(working) < len(targets)
    failing = [domain for domain in targets if domain not in working]
    canary = failing[0] if failing else targets[0]
    report.canary = canary
    report.probe_ip = domain_ips.get(canary)
    log(
        f"  [i] Без обхода доступно {len(working)}/{len(targets)} доменов. "
        f"canary: {canary}."
    )
    if not can_continue():
        return report

    # 4. Матрица протоколов на canary без обхода.
    log(f"  [~] Проверка HTTP/TLS/QUIC на {canary}...")
    probe_ip = report.probe_ip
    http_outcome = probe_url(canary, "http", 80, resolve_ip=probe_ip, timeout=timeout)
    tls12_outcome = probe_url(canary, "https", 443, "1.2", resolve_ip=probe_ip, timeout=timeout)
    report.http_ok = http_outcome.ok
    report.tls12_ok = tls12_outcome.ok
    if report.tls13_supported:
        tls13_outcome = probe_url(
            canary, "https", 443, "1.3", resolve_ip=probe_ip, timeout=timeout
        )
        report.tls13_ok = tls13_outcome.ok
    else:
        report.tls13_ok = True

    report.quic_supported = curl_supports_http3()
    if report.quic_supported:
        quic_outcome = probe_url(
            canary, "https", 443, resolve_ip=probe_ip, timeout=timeout, http3=True
        )
        report.quic_ok = quic_outcome.ok

    # 5. IP-блок (только если иначе всё глухо).
    if not report.http_ok and not report.tls12_ok and not report.tls13_ok:
        good_ips = resolve_doh(_PROBE_TARGET, timeout=timeout) or resolve_system(_PROBE_TARGET)
        good_ip = _pick_ipv4(good_ips)
        canary_ips = (
            report.doh_ips.get(canary, set())
            if canary in report.dns_poisoned
            else (report.dns_ips.get(canary, set()) or report.doh_ips.get(canary, set()))
        )
        canary_ip = _pick_ipv4(canary_ips)
        if good_ip and canary_ip:
            # Известный домен на IP цели: если не проходит — вероятен блок по IP.
            on_blocked_ip = probe_url(
                _PROBE_TARGET, "https", 443, "1.2",
                resolve_ip=canary_ip, insecure=True, timeout=timeout,
            )
            # Цель на заведомо хорошем IP: если проходит, блок не по IP.
            on_good_ip = probe_url(
                canary, "https", 443, "1.2",
                resolve_ip=good_ip, insecure=True, timeout=timeout,
            )
            if not on_blocked_ip.ok and not on_good_ip.ok:
                report.ip_block = "full_or_partial"
            elif not on_blocked_ip.ok:
                report.ip_block = "ip_of_target"
            elif not on_good_ip.ok:
                report.ip_block = "sni_or_domain"
            else:
                report.ip_block = "none"
        else:
            report.notes.append("Не удалось получить IP для проверки IP-блока.")

    report.block_type = classify_block(
        report.http_ok,
        report.tls12_ok,
        report.tls13_ok,
        report.quic_ok,
        report.quic_supported,
        report.ip_block,
    )

    for line in report.summary_lines():
        log(line)
    return report


def candidate_time_budget(mode: str) -> int:
    """Сколько секунд поиска разумно дать режиму (не включая подтверждение)."""
    return {"quick": 300, "standard": 1200, "deep": 3600}.get(mode, 1200)
