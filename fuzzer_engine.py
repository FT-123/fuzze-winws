import subprocess
import time
import socket
import re
import shutil
import os
import copy
import ssl
import random
import concurrent.futures
from dataclasses import dataclass
from typing import List, Generator, Callable, Optional


@dataclass
class WinwsParams:
    tcp_split: int = 1
    tcp_seqovl: int = 664
    tcp_ttl: int = 0
    udp_repeats: int = 8
    udp_cutoff: str = "n4"


class FuzzerEngine:
    def __init__(self,
                 bat_path: str = "general (ALT11).bat",
                 log_callback: Optional[Callable[[str], None]] = None,
                 status_callback: Optional[Callable[[dict], None]] = None):
        self.bat_path = bat_path
        self.log_callback = log_callback or print
        self.status_callback = status_callback
        self.is_running = False
        self.target_hosts: List[str] = []

    def log(self, text: str):
        if self.log_callback:
            self.log_callback(text)

    def set_status(self, **kwargs):
        if self.status_callback:
            self.status_callback(kwargs)

    def extract_baseline(self) -> WinwsParams:
        if not os.path.exists(self.bat_path):
            raise FileNotFoundError(f"Файл '{self.bat_path}' не найден!")

        with open(self.bat_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        def get_val(pattern: str, default: int | str):
            match = re.search(pattern, content)
            return type(default)(match.group(1)) if match else default

        return WinwsParams(
            tcp_split=get_val(r'--dpi-desync-split-pos=(\d+)', 1),
            tcp_seqovl=get_val(r'--dpi-desync-split-seqovl=(\d+)', 664),
            tcp_ttl=get_val(r'--dpi-desync-ttl=(\d+)', 0),
            udp_repeats=get_val(r'--dpi-desync-repeats=(\d+)', 8),
            udp_cutoff=get_val(r'--dpi-desync-cutoff=([a-z0-9]+)', 'n4')
        )

    def generate_mutations(self, baseline: WinwsParams) -> Generator[WinwsParams, None, None]:
        for seq in [100, 300, 500, 681, 800, 1000, 1200]:
            if seq != baseline.tcp_seqovl:
                mutated = copy.copy(baseline)
                mutated.tcp_seqovl = seq
                yield mutated

        for pos in [2, 3, 4]:
            if pos != baseline.tcp_split:
                mutated = copy.copy(baseline)
                mutated.tcp_split = pos
                yield mutated

        for ttl in [3, 4, 5, 7, 8]:
            if ttl != baseline.tcp_ttl:
                mutated = copy.copy(baseline)
                mutated.tcp_ttl = ttl
                yield mutated

        for cutoff in ["n2", "n3", "d2", "d3", "d4"]:
            if cutoff != baseline.udp_cutoff:
                mutated = copy.copy(baseline)
                mutated.udp_cutoff = cutoff
                yield mutated

        for repeats in [4, 6, 10, 12, 15]:
            if repeats != baseline.udp_repeats:
                mutated = copy.copy(baseline)
                mutated.udp_repeats = repeats
                yield mutated

    @staticmethod
    def is_winws_alive() -> bool:
        try:
            output = subprocess.check_output('tasklist /FI "IMAGENAME eq winws.exe"', shell=True, stderr=subprocess.DEVNULL)
            return b"winws.exe" in output
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def stop_winws():
        os.system("taskkill /F /IM winws.exe >nul 2>&1")

    @staticmethod
    def probe_tls_connection(host: str, port: int = 443, packets: int = 3, timeout: int = 5) -> bool:
        success_count = 0
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        for _ in range(packets):
            try:
                with socket.create_connection((host, port), timeout=timeout) as sock:
                    with context.wrap_socket(sock, server_hostname=host) as ssock:
                        success_count += 1
            except (socket.timeout, ConnectionResetError, OSError, ssl.SSLError):
                pass

        return success_count == packets

    def create_and_run_temp_bat(self, params: WinwsParams) -> str:
        temp_bat = "_fuzzer_temp.bat"

        with open(self.bat_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        clean_content = ""
        for line in lines:
            line_lower = line.strip().lower()
            if line_lower.startswith("call service.bat status_zapret") or \
                    line_lower.startswith("call service.bat check_updates"):
                continue
            clean_content += line

        clean_content = re.sub(r'--dpi-desync-split-seqovl=\d+', f'--dpi-desync-split-seqovl={params.tcp_seqovl}', clean_content)
        clean_content = re.sub(r'--dpi-desync-split-pos=\d+', f'--dpi-desync-split-pos={params.tcp_split}', clean_content)
        clean_content = re.sub(r'--dpi-desync-repeats=\d+', f'--dpi-desync-repeats={params.udp_repeats}', clean_content)
        clean_content = re.sub(r'--dpi-desync-cutoff=[a-z0-9]+', f'--dpi-desync-cutoff={params.udp_cutoff}', clean_content)

        if params.tcp_ttl > 0 and "--dpi-desync-ttl" not in clean_content:
            clean_content = re.sub(r'(--dpi-desync-split-pos=\d+)', rf'\1 --dpi-desync-ttl={params.tcp_ttl}', clean_content)
        elif params.tcp_ttl > 0:
            clean_content = re.sub(r'--dpi-desync-ttl=\d+', f'--dpi-desync-ttl={params.tcp_ttl}', clean_content)

        with open(temp_bat, 'w', encoding='utf-8') as f:
            f.write(clean_content)

        subprocess.run(["cmd.exe", "/c", temp_bat], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return temp_bat

    def evaluate_config(self, params: WinwsParams, target_domains: List[str], label: str = "МУТАЦИЯ") -> bool:
        self.log(f"\n[*] ТЕСТИРУЕМ: {label}")
        self.log(f"    TCP: split={params.tcp_split}, seqovl={params.tcp_seqovl}, ttl={params.tcp_ttl}")
        self.log(f"    UDP: repeats={params.udp_repeats}, cutoff={params.udp_cutoff}")
        self.log(f"    Цели ({len(target_domains)}): {', '.join(target_domains[:4])}{'...' if len(target_domains)>4 else ''}")

        self.set_status(params=params, current_step=label)

        temp_bat = self.create_and_run_temp_bat(params)
        time.sleep(2.5)

        if not self.is_winws_alive():
            self.log("  [!] ОШИБКА: Процесс winws.exe мгновенно завершился.")
            if os.path.exists(temp_bat): os.remove(temp_bat)
            return False

        is_success = True
        self.log("  [~] Многопоточный пробив целей запущен...")

        start_time = time.time()
        max_workers = min(len(target_domains), 16) if target_domains else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_domain = {executor.submit(self.probe_tls_connection, dom): dom for dom in target_domains}

            for future in concurrent.futures.as_completed(future_to_domain):
                if not self.is_running:
                    self.log("  [!] Тестирование прервано пользователем.")
                    is_success = False
                    break
                domain = future_to_domain[future]
                try:
                    passed = future.result()
                    status_str = "[O] Доступен" if passed else "[X] Заблокирован"
                    self.log(f"      -> {domain:35} {status_str}")
                    if not passed:
                        is_success = False
                except Exception:
                    self.log(f"      -> {domain:35} [!] Ошибка подключения")
                    is_success = False

        elapsed = time.time() - start_time
        self.log(f"  [*] Проверка завершена за {elapsed:.1f} сек.")

        self.log("  [*] Очистка среды...")
        self.stop_winws()
        time.sleep(1.0)
        if os.path.exists(temp_bat): os.remove(temp_bat)

        return is_success

    def patch_original_bat(self, params: WinwsParams):
        backup_path = self.bat_path + ".bak"
        if not os.path.exists(backup_path):
            shutil.copy2(self.bat_path, backup_path)
            self.log(f"\n  [i] Создан бэкап: {backup_path}")

        with open(self.bat_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        content = re.sub(r'--dpi-desync-split-seqovl=\d+', f'--dpi-desync-split-seqovl={params.tcp_seqovl}', content)
        content = re.sub(r'--dpi-desync-split-pos=\d+', f'--dpi-desync-split-pos={params.tcp_split}', content)
        content = re.sub(r'--dpi-desync-repeats=\d+', f'--dpi-desync-repeats={params.udp_repeats}', content)
        content = re.sub(r'--dpi-desync-cutoff=[a-z0-9]+', f'--dpi-desync-cutoff={params.udp_cutoff}', content)

        if params.tcp_ttl > 0 and "--dpi-desync-ttl" not in content:
            content = re.sub(r'(--dpi-desync-split-pos=\d+)', rf'\1 --dpi-desync-ttl={params.tcp_ttl}', content)
        elif params.tcp_ttl > 0:
            content = re.sub(r'--dpi-desync-ttl=\d+', f'--dpi-desync-ttl={params.tcp_ttl}', content)

        with open(self.bat_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log(f"  [+] Конфиг '{os.path.basename(self.bat_path)}' успешно обновлен рабочими параметрами!")

    def run_fuzzing(self, target_domains: List[str]):
        self.is_running = True
        self.target_hosts = target_domains

        try:
            self.log("=== Zapret Fuzzer Engine ===")
            self.log(f"Целевые домены/хосты ({len(target_domains)}): {', '.join(target_domains)}")

            baseline = self.extract_baseline()
            self.log(f"Базовый конфиг извлекается из '{self.bat_path}'...")

            sample_size = min(4, len(target_domains))
            current_targets = random.sample(target_domains, sample_size) if target_domains else []

            if self.evaluate_config(baseline, current_targets, label="БАЗОВЫЙ КОНФИГ"):
                self.log("\n[+] Базовый конфиг РАБОТАЕТ. Мутации не требуются.")
                self.set_status(state="SUCCESS", message="Базовый конфиг работает!")
                return True

            self.log("\n[-] Базовый конфиг не сработал. Запуск подбора мутаций...")

            for i, mutation in enumerate(self.generate_mutations(baseline), 1):
                if not self.is_running:
                    self.log("\n[!] Подбор остановлен пользователем.")
                    self.set_status(state="STOPPED", message="Остановлено пользователем")
                    return False

                current_targets = random.sample(target_domains, sample_size) if target_domains else []
                if self.evaluate_config(mutation, current_targets, label=f"МУТАЦИЯ #{i}"):
                    self.log("\n[+] УСПЕХ! Найден оптимальный профиль параметров.")
                    self.patch_original_bat(mutation)
                    self.set_status(state="SUCCESS", message="Рабочая стратегия найдена и сохранена!", params=mutation)
                    return True

            self.log("\n[-] Все возможные мутации проверены. Рабочая стратегия не найдена.")
            self.set_status(state="FAILED", message="Мутации исчерпаны")
            return False

        except Exception as e:
            self.log(f"\n[!] Ошибка во время фуззинга: {e}")
            self.set_status(state="ERROR", message=str(e))
            return False
        finally:
            self.is_running = False

    def stop(self):
        self.is_running = False
        self.stop_winws()