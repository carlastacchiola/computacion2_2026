from __future__ import annotations

import time
from multiprocessing import Event, Manager, Process, Queue

from rich.console import Console
from rich.table import Table
from rich.live import Live

from src.agregador import run_aggregator
from src.recolector import run_collector
from src.senales import ManejadorSenales, cargar_config, volcar_snapshot
from src.analizadores.resumen import run_summary_analyzer
from src.analizadores.memoria import run_memory_analyzer
from src.analizadores.fds import run_fds_analyzer
from src.analizadores.threads import run_threads_analyzer
from src.analizadores.senales import run_signals_analyzer
from src.analizadores.scheduling import run_scheduling_analyzer
from src.analizadores.sistema import run_system_analyzer


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
    table.add_row("Esperando datos del recolector y los analizadores...")
    return table


def main() -> None:
    console = Console()
    stop_event = Event()
    output_queue = Queue()
    senales = ManejadorSenales()
    senales.instalar_handlers()

    config = cargar_config()
    verbose = bool(config.get("verbose", False))

    with Manager() as manager:
        snapshot = manager.dict()
        shared_pids = manager.list()

        collector_process = Process(
            target=run_collector,
            args=(shared_pids, stop_event),
            kwargs={"interval_seconds": 1.0},
            name="recolector",
        )

        analyzer_specs = [
            (run_summary_analyzer, "analizador-resumen", 2.0),
            (run_memory_analyzer, "analizador-memoria", 3.0),
            (run_fds_analyzer, "analizador-fds", 5.0),
            (run_threads_analyzer, "analizador-threads", 2.0),
            (run_signals_analyzer, "analizador-senales", 10.0),
            (run_scheduling_analyzer, "analizador-scheduling", 10.0),
            (run_system_analyzer, "analizador-sistema", 2.0),
        ]

        analyzer_processes = [
            Process(
                target=func,
                args=(shared_pids, output_queue, stop_event),
                kwargs={"interval_seconds": interval},
                name=name,
            )
            for func, name, interval in analyzer_specs
        ]

        aggregator_process = Process(
            target=run_aggregator,
            args=(output_queue, snapshot, stop_event),
            name="agregador",
        )

        
        processes = [collector_process, aggregator_process, *analyzer_processes]

        for process in processes:
            process.start()

        try:
            with Live(build_loading_table(), console=console, refresh_per_second=2) as live:
                while not senales.hay_shutdown_pendiente():
                    if senales.consumir_reload():
                        config = cargar_config()
                        live.console.print(
                            f"[cyan]SIGHUP: config.json recargado -> {config}[/cyan]"
                        )

                    if senales.consumir_dump():
                        ruta = volcar_snapshot(snapshot)
                        live.console.print(f"[green]SIGUSR1: snapshot volcado en {ruta}[/green]")

                    if senales.consumir_toggle_verbose():
                        verbose = not verbose
                        estado = "activado" if verbose else "desactivado"
                        live.console.print(f"[magenta]SIGUSR2: modo verbose {estado}[/magenta]")

                    
                    senales.consumir_repaint()
                    senales.drenar_pipe()

                    resumen = snapshot.get("resumen")

                    if resumen is not None:
                        live.update(build_summary_table(resumen["data"]["processes"]))
                    else:
                        live.update(build_loading_table())

                    time.sleep(0.5)

            console.print("\n[yellow]Señal de shutdown recibida, cerrando monitor...[/yellow]")

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