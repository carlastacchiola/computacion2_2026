from __future__ import annotations

import os
import time

from src.procfs import list_process_summaries


def get_cpu_ticks(proc) -> int | None:
    if proc.utime is None or proc.stime is None:
        return None

    return proc.utime + proc.stime


def take_cpu_snapshot() -> dict[int, int]:
    snapshot: dict[int, int] = {}

    for proc in list_process_summaries():
        ticks = get_cpu_ticks(proc)
        if ticks is not None:
            snapshot[proc.pid] = ticks

    return snapshot


def calculate_cpu_percent(
    old_ticks: int,
    new_ticks: int,
    elapsed_seconds: float,
    clock_ticks: int,
) -> float:
    if elapsed_seconds <= 0:
        return 0.0

    delta_ticks = max(0, new_ticks - old_ticks)
    cpu_seconds = delta_ticks / clock_ticks

    return (cpu_seconds / elapsed_seconds) * 100.0


def collect_summary(sample_seconds: float = 1.0, limit: int | None = 30) -> list[dict]:
    first_snapshot = take_cpu_snapshot()

    start = time.monotonic()
    time.sleep(sample_seconds)
    elapsed = time.monotonic() - start

    clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    processes = []

    for proc in list_process_summaries(limit=limit):
        current_ticks = get_cpu_ticks(proc)
        old_ticks = first_snapshot.get(proc.pid)

        cpu_percent = None
        if current_ticks is not None and old_ticks is not None:
            cpu_percent = calculate_cpu_percent(
                old_ticks,
                current_ticks,
                elapsed,
                clock_ticks,
            )

        processes.append(
            {
                "pid": proc.pid,
                "name": proc.name,
                "command": proc.command or proc.name,
                "state": proc.state,
                "ppid": proc.ppid,
                "threads": proc.threads,
                "vmrss_kb": proc.vmrss_kb,
                "cpu_percent": cpu_percent,
            }
        )

    return processes

def run_summary_analyzer(output_queue, stop_event, interval_seconds=2.0):
    while not stop_event.is_set():
        processes = collect_summary(sample_seconds=1.0, limit=30)

        message = {
            "type": "resumen",
            "timestamp": time.time(),
            "processes": processes,
        }

        output_queue.put(message)

        stop_event.wait(interval_seconds)