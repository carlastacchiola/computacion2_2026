from __future__ import annotations

import os
import signal
import time

from src.procfs import parse_status, read_text


def parse_thread_stat(text: str) -> dict | None:
    close = text.rfind(")")
    fields = text[close + 2:].split()
    if len(fields) < 15:
        return None
    return {"state": fields[0], "utime": int(fields[11]), "stime": int(fields[12])}


def collect_threads(pids: list[int], limit: int | None = 30, per_process_limit: int = 8) -> list[dict]:
    target_pids = pids[:limit] if limit is not None else pids
    result = []

    for pid in target_pids:
        task_dir = f"/proc/{pid}/task"

        try:
            tids = sorted([int(x) for x in os.listdir(task_dir) if x.isdigit()])
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue

        threads = []

        for tid in tids[:per_process_limit]:
            base = f"/proc/{pid}/task/{tid}"
            comm = read_text(f"{base}/comm")
            stat = read_text(f"{base}/stat")
            status_text = read_text(f"{base}/status")

            parsed_stat = parse_thread_stat(stat) if stat else None
            parsed_status = parse_status(status_text) if status_text else {}

            threads.append({
                "tid": tid,
                "name": comm.strip() if comm else "",
                "state": parsed_stat["state"] if parsed_stat else "",
                "cpu_ticks": (parsed_stat["utime"] + parsed_stat["stime"]) if parsed_stat else None,
                "voluntary_ctxt_switches": parsed_status.get("voluntary_ctxt_switches"),
                "nonvoluntary_ctxt_switches": parsed_status.get("nonvoluntary_ctxt_switches"),
            })

        result.append({"pid": pid, "threads": threads})

    return result


def run_threads_analyzer(shared_pids, output_queue, stop_event, interval_seconds=2.0):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not stop_event.is_set():
        pids = list(shared_pids)
        output_queue.put({
            "type": "threads",
            "timestamp": time.time(),
            "processes": collect_threads(pids),
        })
        stop_event.wait(interval_seconds)