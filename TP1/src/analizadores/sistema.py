from __future__ import annotations

import time

from src.procfs import parse_status, read_process_stat, read_text
from src.senales import ignorar_senales_de_control


def leer_cpu_global() -> dict[str, int] | None:
    text = read_text("/proc/stat") or ""

    for line in text.splitlines():
        if line.startswith("cpu "):
            partes = line.split()[1:]
            claves = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal"]
            valores: dict[str, int] = {}
            for i, clave in enumerate(claves):
                if i < len(partes):
                    try:
                        valores[clave] = int(partes[i])
                    except ValueError:
                        valores[clave] = 0
            return valores

    return None


def calcular_cpu_global_percent(
    anterior: dict[str, int] | None,
    actual: dict[str, int] | None,
) -> dict[str, float] | None:
    if anterior is None or actual is None:
        return None

    delta = {clave: actual.get(clave, 0) - anterior.get(clave, 0) for clave in actual}
    total = sum(delta.values())

    if total <= 0:
        return {"user": 0.0, "system": 0.0, "idle": 0.0, "iowait": 0.0}

    return {
        "user": 100.0 * delta.get("user", 0) / total,
        "system": 100.0 * delta.get("system", 0) / total,
        "idle": 100.0 * delta.get("idle", 0) / total,
        "iowait": 100.0 * delta.get("iowait", 0) / total,
    }


def parse_meminfo() -> dict:
    text = read_text("/proc/meminfo") or ""
    data = {}

    for line in text.splitlines():
        key, value = line.split(":", 1)
        parts = value.strip().split()
        data[key] = int(parts[0]) if parts else 0

    return data


def parse_loadavg() -> dict:
    text = read_text("/proc/loadavg") or ""
    parts = text.split()
    return {
        "load_1": parts[0] if len(parts) > 0 else "",
        "load_5": parts[1] if len(parts) > 1 else "",
        "load_15": parts[2] if len(parts) > 2 else "",
    }


def parse_boot_time() -> int | None:
    text = read_text("/proc/stat") or ""
    for line in text.splitlines():
        if line.startswith("btime"):
            partes = line.split()
            if len(partes) > 1:
                try:
                    return int(partes[1])
                except ValueError:
                    return None
    return None


def parse_uptime() -> dict:
    text = read_text("/proc/uptime") or ""
    parts = text.split()
    return {
        "uptime_seconds": float(parts[0]) if len(parts) > 0 else 0.0,
        "idle_seconds": float(parts[1]) if len(parts) > 1 else 0.0,
    }


def collect_system(pids: list[int], cpu_global_percent: dict[str, float] | None = None) -> dict:
   

    states = {}
    total_threads = 0

    for pid in pids:
        stat = read_process_stat(pid)
        status_text = read_text(f"/proc/{pid}/status")

        if stat:
            state = stat.get("state", "?")
            states[state] = states.get(state, 0) + 1

        if status_text:
            status = parse_status(status_text)
            try:
                total_threads += int(status.get("Threads", "0"))
            except ValueError:
                pass

    meminfo = parse_meminfo()

    return {
        "loadavg": parse_loadavg(),
        "uptime": parse_uptime(),
        "boot_time": parse_boot_time(),
        "cpu_global": cpu_global_percent,
        "memory": {
            "mem_total_kb": meminfo.get("MemTotal"),
            "mem_available_kb": meminfo.get("MemAvailable"),
            "mem_free_kb": meminfo.get("MemFree"),
            "buffers_kb": meminfo.get("Buffers"),
            "cached_kb": meminfo.get("Cached"),
            "swap_total_kb": meminfo.get("SwapTotal"),
            "swap_free_kb": meminfo.get("SwapFree"),
        },
        "process_count": len(pids),
        "states": states,
        "total_threads": total_threads,
        "zombies": states.get("Z", 0),
    }


def run_system_analyzer(shared_pids, output_queue, stop_event, interval_value):
    ignorar_senales_de_control()
    lectura_anterior = leer_cpu_global()

    while not stop_event.is_set():
        pids = list(shared_pids)

        lectura_actual = leer_cpu_global()
        cpu_global_percent = calcular_cpu_global_percent(lectura_anterior, lectura_actual)
        lectura_anterior = lectura_actual

        output_queue.put({
            "type": "sistema",
            "timestamp": time.time(),
            "data": collect_system(pids, cpu_global_percent),
        })
        stop_event.wait(interval_value.value)