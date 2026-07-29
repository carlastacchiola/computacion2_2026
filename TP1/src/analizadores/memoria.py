from __future__ import annotations

import time

from src.procfs import parse_kb, read_process_stat, read_process_status
from src.senales import ignorar_senales_de_control


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


def collect_memory(pids: list[int], limit: int | None = 30) -> list[dict]:
    target_pids = pids[:limit] if limit is not None else pids
    processes = []

    for pid in target_pids:
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

    return processes


def run_memory_analyzer(shared_pids, output_queue, stop_event, interval_value):
    ignorar_senales_de_control()

    while not stop_event.is_set():
        pids = list(shared_pids)
        processes = collect_memory(pids, limit=30)

        message = {
            "type": "memoria",
            "timestamp": time.time(),
            "processes": processes,
        }

        output_queue.put(message)

        stop_event.wait(interval_value.value)