from __future__ import annotations

import time

from src.procfs import read_process_stat, read_process_status
from src.senales import ignorar_senales_de_control


POLICIES = {
    0: "OTHER",
    1: "FIFO",
    2: "RR",
    3: "BATCH",
    5: "IDLE",
    6: "DEADLINE",
}


def collect_scheduling(pids: list[int], limit: int | None = 30) -> list[dict]:
    target_pids = pids[:limit] if limit is not None else pids
    result = []

    for pid in target_pids:
        status = read_process_status(pid)
        stat = read_process_stat(pid)

        if status is None or stat is None:
            continue

        result.append({
            "pid": pid,
            "name": status.get("Name", ""),
            "nice": stat.get("nice"),
            "priority": stat.get("priority"),
            "policy": POLICIES.get(stat.get("policy"), str(stat.get("policy"))),
            "rt_priority": stat.get("rt_priority"),
            "affinity": status.get("Cpus_allowed_list", ""),
            "voluntary_ctxt_switches": status.get("voluntary_ctxt_switches"),
            "nonvoluntary_ctxt_switches": status.get("nonvoluntary_ctxt_switches"),
            "sid": stat.get("session"),
            "pgid": stat.get("pgrp"),
            "utime": stat.get("utime"),
            "stime": stat.get("stime"),
        })

    return result


def run_scheduling_analyzer(shared_pids, output_queue, stop_event, interval_value):
    ignorar_senales_de_control()

    while not stop_event.is_set():
        pids = list(shared_pids)
        output_queue.put({
            "type": "scheduling",
            "timestamp": time.time(),
            "processes": collect_scheduling(pids),
        })
        stop_event.wait(interval_value.value)