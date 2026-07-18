from __future__ import annotations

from rich.console import Console
from rich.table import Table

from src.analizadores.resumen import collect_summary


def build_table() -> Table:
    table = Table(title="Monitor de procesos - vista resumen")
    table.add_column("PID", justify="right")
    table.add_column("Nombre")
    table.add_column("Estado")
    table.add_column("PPID", justify="right")
    table.add_column("Threads", justify="right")
    table.add_column("VmRSS", justify="right")
    table.add_column("CPU%", justify="right")
    table.add_column("Comando")

    for proc in collect_summary(sample_seconds=1.0, limit=30):
        table.add_row(
            str(proc["pid"]),
            proc["name"],
            proc["state"],
            "" if proc["ppid"] is None else str(proc["ppid"]),
            "" if proc["threads"] is None else str(proc["threads"]),
            "" if proc["vmrss_kb"] is None else f"{proc['vmrss_kb']} kB",
            "" if proc["cpu_percent"] is None else f"{proc['cpu_percent']:.1f}",
            proc["command"],
        )

    return table


def main() -> None:
    console = Console()
    console.print(build_table())


if __name__ == "__main__":
    main()