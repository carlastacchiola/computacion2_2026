from __future__ import annotations

import os
import time

from rich.console import Console
from rich.table import Table

from src.procfs import list_process_summaries


def get_cpu_ticks(proc) -> int | None:
    if proc.utime is None or proc.stime is None:
        return None

    return proc.utime + proc.stime


def take_cpu_snapshot() -> dict[int, int]:
    snapshot = {}

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


def build_table(sample_seconds: float = 1.0) -> Table:
    first_snapshot = take_cpu_snapshot()

    start = time.monotonic()
    time.sleep(sample_seconds)
    elapsed = time.monotonic() - start

    clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    table = Table(title="Monitor de procesos - resumen inicial")
    table.add_column("PID", justify="right")
    table.add_column("Nombre")
    table.add_column("Estado")
    table.add_column("PPID", justify="right")
    table.add_column("Threads", justify="right")
    table.add_column("VmRSS", justify="right")
    table.add_column("CPU%", justify="right")
    table.add_column("Comando")

    for proc in list_process_summaries(limit=30):
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

        table.add_row(
            str(proc.pid),
            proc.name,
            proc.state,
            "" if proc.ppid is None else str(proc.ppid),
            "" if proc.threads is None else str(proc.threads),
            "" if proc.vmrss_kb is None else f"{proc.vmrss_kb} kB",
            "" if cpu_percent is None else f"{cpu_percent:.1f}",
            proc.command or proc.name,
        )

    return table


def main() -> None:
    console = Console()
    console.print(build_table())


if __name__ == "__main__":
    main()