from __future__ import annotations

import time
from multiprocessing import Event, Manager, Process, Queue

from rich.console import Console
from rich.live import Live
from rich.table import Table

from src.agregador import run_aggregator
from src.analizadores.resumen import run_summary_analyzer


def build_summary_table(processes: list[dict]) -> Table:
    table = Table(title="Monitor multiproceso - vista resumen")
    table.add_column("PID", justify="right")
    table.add_column("Nombre")
    table.add_column("Estado")
    table.add_column("PPID", justify="right")
    table.add_column("Threads", justify="right")
    table.add_column("VmRSS", justify="right")
    table.add_column("CPU%", justify="right")
    table.add_column("Comando")

    for proc in processes:
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


def build_loading_table() -> Table:
    table = Table(title="Monitor multiproceso")
    table.add_column("Estado")
    table.add_row("Esperando datos del analizador resumen...")
    return table


def main() -> None:
    console = Console()
    stop_event = Event()
    output_queue = Queue()

    with Manager() as manager:
        snapshot = manager.dict()

        summary_process = Process(
            target=run_summary_analyzer,
            args=(output_queue, stop_event),
            name="analizador-resumen",
        )

        aggregator_process = Process(
            target=run_aggregator,
            args=(output_queue, snapshot, stop_event),
            name="agregador",
        )

        processes = [summary_process, aggregator_process]

        for process in processes:
            process.start()

        try:
            with Live(build_loading_table(), console=console, refresh_per_second=2) as live:
                while True:
                    resumen = snapshot.get("resumen")

                    if resumen is None:
                        live.update(build_loading_table())
                    else:
                        data = resumen["data"]
                        live.update(build_summary_table(data["processes"]))

                    time.sleep(0.5)

        except KeyboardInterrupt:
            console.print("\n[yellow]Cerrando monitor...[/yellow]")

        finally:
            stop_event.set()

            for process in processes:
                process.join(timeout=3)

            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()


if __name__ == "__main__":
    main()