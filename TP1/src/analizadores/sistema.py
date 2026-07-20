from __future__ import annotations

import signal
import time

from src.procfs import list_pids, parse_status, read_process_stat, read_text


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


def parse_uptime() -> dict:
    text = read_text("/proc/uptime") or ""
    parts = text.split()
    return {
        "uptime_seconds": float(parts[0]) if len(parts) > 0 else 0.0,
        "idle_seconds": float(parts[1]) if len(parts) > 1 else 0.0,
    }


def collect_system() -> dict:
    states = {}
    total_threads = 0

    for pid in list_pids():
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
        "memory": {
            "mem_total_kb": meminfo.get("MemTotal"),
            "mem_available_kb": meminfo.get("MemAvailable"),
            "mem_free_kb": meminfo.get("MemFree"),
            "buffers_kb": meminfo.get("Buffers"),
            "cached_kb": meminfo.get("Cached"),
            "swap_total_kb": meminfo.get("SwapTotal"),
            "swap_free_kb": meminfo.get("SwapFree"),
        },
        "process_count": len(list_pids()),
        "states": states,
        "total_threads": total_threads,
        "zombies": states.get("Z", 0),
    }


def run_system_analyzer(output_queue, stop_event, interval_seconds=2.0):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not stop_event.is_set():
        output_queue.put({
            "type": "sistema",
            "timestamp": time.time(),
            "data": collect_system(),
        })
        stop_event.wait(interval_seconds)