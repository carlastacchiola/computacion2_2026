from __future__ import annotations

from multiprocessing import Event, Process, Queue
from queue import Empty

from rich.console import Console
from rich.table import Table

from src.analizadores.resumen import run_summary_analyzer


def build_table(processes: list[dict]) -> Table:
    table = Table(title="Monitor de procesos - vista resumen")
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


def main() -> None:
    console = Console()
    output_queue = Queue()
    stop_event = Event()

    analyzer = Process(
        target=run_summary_analyzer,
        args=(output_queue, stop_event),
        name="analizador-resumen",
    )

    analyzer.start()

    try:
        message = output_queue.get(timeout=5)

        if message["type"] == "resumen":
            console.print(build_table(message["processes"]))

    except Empty:
        console.print("[red]No llegaron datos del analizador resumen.[/red]")

    finally:
        stop_event.set()
        analyzer.join(timeout=3)

        if analyzer.is_alive():
            analyzer.terminate()
            analyzer.join()


if __name__ == "__main__":
    main()