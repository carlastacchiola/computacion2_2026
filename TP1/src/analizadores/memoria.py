from __future__ import annotations

import signal
import time

from src.procfs import list_pids, parse_kb, read_process_stat, read_process_status


MEMORY_FIELDS = [
    "VmSize",
    "VmRSS",
    "VmData",
    "VmStk",
    "VmExe",
    "VmLib",
    "VmHWM",
    "VmSwap",
]


def collect_memory(limit: int | None = 30) -> list[dict]:
    processes = []

    for pid in list_pids():
        status = read_process_status(pid)
        if status is None:
            continue

        stat = read_process_stat(pid)

        item = {
            "pid": pid,
            "name": status.get("Name", ""),
        }

        for field in MEMORY_FIELDS:
            item[field.lower() + "_kb"] = parse_kb(status.get(field))

        if stat is None:
            item["minor_faults"] = None
            item["major_faults"] = None
        else:
            item["minor_faults"] = stat.get("minflt")
            item["major_faults"] = stat.get("majflt")

        processes.append(item)

        if limit is not None and len(processes) >= limit:
            break

    return processes


def run_memory_analyzer(output_queue, stop_event, interval_seconds=3.0):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not stop_event.is_set():
        processes = collect_memory(limit=30)

        message = {
            "type": "memoria",
            "timestamp": time.time(),
            "processes": processes,
        }

        output_queue.put(message)

        stop_event.wait(interval_seconds)