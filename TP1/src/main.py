from __future__ import annotations

import os
import time
from multiprocessing import Event, Manager, Process, Queue, Value

from src.agregador import run_aggregator
from src.recolector import run_collector
from src.display import run_display
from src.senales import ManejadorSenales, cargar_config, volcar_snapshot
from src.vistas import VISTAS
from src.analizadores.resumen import run_summary_analyzer
from src.analizadores.memoria import run_memory_analyzer
from src.analizadores.fds import run_fds_analyzer
from src.analizadores.threads import run_threads_analyzer
from src.analizadores.senales import run_signals_analyzer
from src.analizadores.scheduling import run_scheduling_analyzer
from src.analizadores.sistema import run_system_analyzer


PID_FILE = "monitor.pid"


def _reportar_estado(snapshot, texto: str, estilo: str = "cyan") -> None:
    snapshot["_status"] = {"texto": texto, "estilo": estilo, "ts": time.time()}


def main() -> None:
    stop_event = Event()
    output_queue = Queue()

    with open(PID_FILE, "w", encoding="utf-8") as pid_file:
        pid_file.write(str(os.getpid()))

   
    senales = ManejadorSenales()
    senales.instalar_handlers()

    config = cargar_config()
    verbose_value = Value("b", 1 if config.get("verbose") else 0)

    with Manager() as manager:
        snapshot = manager.dict()
        shared_pids = manager.list()
        interval_values = {v["id"]: Value("d", v["intervalo_default"]) for v in VISTAS}

        collector_process = Process(
            target=run_collector,
            args=(shared_pids, stop_event),
            kwargs={"interval_seconds": 1.0},
            name="recolector",
        )

        analyzer_processes = [
            Process(
                target=run_summary_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["resumen"]),
                name="analizador-resumen",
            ),
            Process(
                target=run_memory_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["memoria"]),
                name="analizador-memoria",
            ),
            Process(
                target=run_fds_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["fds"], verbose_value),
                name="analizador-fds",
            ),
            Process(
                target=run_threads_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["threads"], verbose_value),
                name="analizador-threads",
            ),
            Process(
                target=run_signals_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["senales"]),
                name="analizador-senales",
            ),
            Process(
                target=run_scheduling_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["scheduling"]),
                name="analizador-scheduling",
            ),
            Process(
                target=run_system_analyzer,
                args=(shared_pids, output_queue, stop_event, interval_values["sistema"]),
                name="analizador-sistema",
            ),
        ]

        aggregator_process = Process(
            target=run_aggregator,
            args=(output_queue, snapshot, stop_event),
            name="agregador",
        )

        display_process = Process(
            target=run_display,
            args=(snapshot, interval_values, verbose_value, stop_event),
            name="display",
        )

       
        processes = [
            collector_process,
            aggregator_process,
            *analyzer_processes,
            display_process,
        ]

        for process in processes:
            process.start()

        try:
            while not senales.hay_shutdown_pendiente() and not stop_event.is_set():
                if senales.consumir_reload():
                    config = cargar_config()
                    _reportar_estado(snapshot, f"SIGHUP: config.json recargado -> {config}", "cyan")

                if senales.consumir_dump():
                    ruta = volcar_snapshot(snapshot)
                    _reportar_estado(snapshot, f"SIGUSR1: snapshot volcado en {ruta}", "green")

                if senales.consumir_toggle_verbose():
                    verbose_value.value = 0 if verbose_value.value else 1
                    estado_txt = "activado" if verbose_value.value else "desactivado"
                    _reportar_estado(snapshot, f"SIGUSR2: modo verbose {estado_txt}", "magenta")

                senales.consumir_repaint()
                senales.drenar_pipe()

                time.sleep(0.2)

        finally:
            stop_event.set()

            for process in processes:
                process.join(timeout=3)

            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()

            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)


if __name__ == "__main__":
    main()