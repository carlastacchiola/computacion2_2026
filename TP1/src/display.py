from __future__ import annotations

import os
import queue
import select
import sys
import threading
import time

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.vistas import TECLA_A_VISTA, VISTA_POR_ID, VISTAS

ROW_LIMIT = 20
ORDEN_SIGUIENTE = {"cpu": "rss", "rss": "pid", "pid": "cpu"}



def _leer_teclado(cola: queue.Queue, stop_flag: threading.Event) -> None:
    import termios
    import tty

    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
       
        return

    config_original = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)

        while not stop_flag.is_set():
            listos, _, _ = select.select([fd], [], [], 0.2)
            if not listos:
                continue

            char = os.read(fd, 1).decode(errors="ignore")

            if char == "\x1b":
                listos2, _, _ = select.select([fd], [], [], 0.05)
                if not listos2:
                    cola.put("ESC")
                    continue

                char2 = os.read(fd, 1).decode(errors="ignore")
                if char2 != "[":
                    cola.put("ESC")
                    continue

                listos3, _, _ = select.select([fd], [], [], 0.05)
                if not listos3:
                    continue

                char3 = os.read(fd, 1).decode(errors="ignore")
                if char3 == "A":
                    cola.put("UP")
                elif char3 == "B":
                    cola.put("DOWN")
                continue

            if char in ("\r", "\n"):
                cola.put("ENTER")
            elif char in ("\x7f", "\b"):
                cola.put("BACKSPACE")
            else:
                cola.put(char)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, config_original)
        os.close(fd)


def _ajustar_intervalo(vista_id: str, interval_values: dict, delta: float) -> None:
    definicion = VISTA_POR_ID[vista_id]
    value = interval_values[vista_id]
    nuevo = round(value.value + delta, 2)
    value.value = max(definicion["intervalo_minimo"], nuevo)


def _procesar_tecla(tecla: str, estado: dict, interval_values: dict, verbose_value, stop_event) -> None:
    if estado["editando"] is not None:
        if tecla == "ENTER":
            valor = estado["buffer_edicion"].strip()
            if estado["editando"] == "comando":
                estado["filtro_comando"] = valor or None
            else:
                estado["filtro_usuario"] = valor or None
            estado["editando"] = None
            estado["buffer_edicion"] = ""
        elif tecla == "ESC":
            estado["editando"] = None
            estado["buffer_edicion"] = ""
        elif tecla == "BACKSPACE":
            estado["buffer_edicion"] = estado["buffer_edicion"][:-1]
        elif len(tecla) == 1 and tecla.isprintable():
            estado["buffer_edicion"] += tecla
        return

    if tecla in TECLA_A_VISTA:
        estado["vista"] = TECLA_A_VISTA[tecla]
        estado["indice_seleccionado"] = 0
        return

    if tecla == "UP":
        estado["indice_seleccionado"] = max(0, estado["indice_seleccionado"] - 1)
    elif tecla == "DOWN":
        estado["indice_seleccionado"] += 1
    elif tecla == "ENTER":
        lista = estado.get("_visible_cache", [])
        idx = estado["indice_seleccionado"]
        if 0 <= idx < len(lista):
            pid = lista[idx]["pid"]
            estado["pid_fijado"] = None if estado["pid_fijado"] == pid else pid
    elif tecla == "/":
        estado["editando"] = "comando"
        estado["buffer_edicion"] = ""
    elif tecla == "u":
        estado["editando"] = "usuario"
        estado["buffer_edicion"] = ""
    elif tecla == "c":
        estado["orden"] = ORDEN_SIGUIENTE[estado["orden"]]
    elif tecla in ("+", "="):
        _ajustar_intervalo(estado["vista"], interval_values, 0.5)
    elif tecla == "-":
        _ajustar_intervalo(estado["vista"], interval_values, -0.5)
    elif tecla == "q":
        stop_event.set()
    elif tecla in ("h", "?"):
        estado["mostrar_ayuda"] = not estado["mostrar_ayuda"]


# --------------------------------------------------------------------
# Construccion de la lista de procesos 
# --------------------------------------------------------------------
def _filtrar_y_ordenar(procesos: list[dict], estado: dict) -> list[dict]:
    resultado = procesos

    if estado["filtro_comando"]:
        needle = estado["filtro_comando"].lower()
        resultado = [
            p for p in resultado
            if needle in (p.get("command") or "").lower() or needle in (p.get("name") or "").lower()
        ]

    if estado["filtro_usuario"]:
        needle = estado["filtro_usuario"].lower()
        resultado = [p for p in resultado if needle in (p.get("user") or "").lower()]

    orden = estado["orden"]
    if orden == "cpu":
        resultado = sorted(resultado, key=lambda p: (p.get("cpu_percent") is None, -(p.get("cpu_percent") or 0)))
    elif orden == "rss":
        resultado = sorted(resultado, key=lambda p: (p.get("vmrss_kb") is None, -(p.get("vmrss_kb") or 0)))
    else:
        resultado = sorted(resultado, key=lambda p: p.get("pid", 0))

    return resultado


def _armar_lista_visible(procesos_completos: list[dict], estado: dict) -> list[dict]:
    ordenados = _filtrar_y_ordenar(procesos_completos, estado)
    visibles = ordenados[:ROW_LIMIT]

    pid_fijado = estado["pid_fijado"]
    if pid_fijado is not None and pid_fijado not in [p["pid"] for p in visibles]:
        fijado = next((p for p in ordenados if p["pid"] == pid_fijado), None)
        if fijado is not None:
            visibles = [fijado] + visibles[: ROW_LIMIT - 1]

    return visibles


def _tabla_procesos(visibles: list[dict], estado: dict) -> Table:
    tabla = Table(expand=True)
    tabla.add_column(" ", width=2)
    tabla.add_column("PID", justify="right")
    tabla.add_column("Usuario")
    tabla.add_column("Estado", justify="center")
    tabla.add_column("CPU%", justify="right")
    tabla.add_column("RSS", justify="right")
    tabla.add_column("Nombre")

    idx_sel = estado["indice_seleccionado"]

    for i, proc in enumerate(visibles):
        marca = "*" if proc["pid"] == estado["pid_fijado"] else ""
        estilo = "reverse" if i == idx_sel else ""

        cpu = "" if proc.get("cpu_percent") is None else f"{proc['cpu_percent']:.1f}"
        rss = "" if proc.get("vmrss_kb") is None else f"{proc['vmrss_kb']} kB"

        tabla.add_row(
            marca,
            str(proc["pid"]),
            proc.get("user", ""),
            proc.get("state", ""),
            cpu,
            rss,
            proc.get("name", ""),
            style=estilo,
        )

    if not visibles:
        tabla.add_row("", "-", "-", "-", "-", "-", "(sin procesos que coincidan con el filtro)")

    return tabla


# --------------------------------------------------------------------
# Paneles de detalle por vista 
# --------------------------------------------------------------------
def _buscar_por_pid(lista: list[dict] | None, pid: int | None) -> dict | None:
    if not lista or pid is None:
        return None
    for item in lista:
        if item.get("pid") == pid:
            return item
    return None


def _panel_memoria(snapshot, pid: int | None) -> Table:
    entrada = snapshot.get("memoria")
    tabla = Table(title="Memoria del proceso seleccionado", expand=True)
    tabla.add_column("Campo")
    tabla.add_column("Valor", justify="right")

    if entrada is None:
        tabla.add_row("(esperando datos del analizador de memoria)", "")
        return tabla

    item = _buscar_por_pid(entrada.get("processes"), pid)
    if item is None:
        tabla.add_row("(proceso no encontrado en el muestreo actual)", "")
        return tabla

    campos = [
        ("VmSize", "vmsize_kb"), ("VmRSS", "vmrss_kb"), ("VmData", "vmdata_kb"),
        ("VmStk", "vmstk_kb"), ("VmExe", "vmexe_kb"), ("VmLib", "vmlib_kb"),
        ("VmHWM", "vmhwm_kb"), ("VmSwap", "vmswap_kb"),
    ]
    for etiqueta, clave in campos:
        valor = item.get(clave)
        tabla.add_row(etiqueta, "-" if valor is None else f"{valor} kB")

    tabla.add_row("Minor faults", str(item.get("minor_faults", "-")))
    tabla.add_row("Major faults", str(item.get("major_faults", "-")))
    return tabla


def _panel_fds(snapshot, pid: int | None) -> Table:
    entrada = snapshot.get("fds")
    tabla = Table(title="File descriptors del proceso seleccionado", expand=True)
    tabla.add_column("FD")
    tabla.add_column("Tipo")
    tabla.add_column("Destino")

    if entrada is None:
        tabla.add_row("(esperando datos)", "", "")
        return tabla

    item = _buscar_por_pid(entrada.get("processes"), pid)
    if item is None or not item.get("fds"):
        tabla.add_row("(sin FDs visibles para este proceso)", "", "")
        return tabla

    for fd in item["fds"]:
        tabla.add_row(fd["fd"], fd["type"], fd["target"])

    return tabla


def _panel_threads(snapshot, pid: int | None) -> Table:
    entrada = snapshot.get("threads")
    tabla = Table(title="Threads (LWPs) del proceso seleccionado", expand=True)
    tabla.add_column("TID", justify="right")
    tabla.add_column("Nombre")
    tabla.add_column("Estado", justify="center")
    tabla.add_column("Vol.", justify="right")
    tabla.add_column("Invol.", justify="right")

    if entrada is None:
        tabla.add_row("(esperando datos)", "", "", "", "")
        return tabla

    item = _buscar_por_pid(entrada.get("processes"), pid)
    if item is None or not item.get("threads"):
        tabla.add_row("(sin threads visibles para este proceso)", "", "", "", "")
        return tabla

    for th in item["threads"]:
        tabla.add_row(
            str(th["tid"]), th.get("name", ""), th.get("state", ""),
            str(th.get("voluntary_ctxt_switches", "-")),
            str(th.get("nonvoluntary_ctxt_switches", "-")),
        )

    return tabla


def _panel_senales(snapshot, pid: int | None) -> Table:
    entrada = snapshot.get("senales")
    tabla = Table(title="Mascaras de senales del proceso seleccionado", expand=True)
    tabla.add_column("Categoria")
    tabla.add_column("Senales")

    if entrada is None:
        tabla.add_row("(esperando datos)", "")
        return tabla

    item = _buscar_por_pid(entrada.get("processes"), pid)
    if item is None:
        tabla.add_row("(proceso no encontrado en el muestreo actual)", "")
        return tabla

    etiquetas = [
        ("Bloqueadas (SigBlk)", "sigblk"), ("Ignoradas (SigIgn)", "sigign"),
        ("Con handler (SigCgt)", "sigcgt"), ("Pendientes proceso (SigPnd)", "sigpnd"),
        ("Pendientes grupo (ShdPnd)", "shdpnd"),
    ]
    for etiqueta, clave in etiquetas:
        nombres = item.get(clave) or []
        tabla.add_row(etiqueta, ", ".join(nombres) if nombres else "(ninguna)")

    return tabla


def _panel_scheduling(snapshot, pid: int | None) -> Table:
    entrada = snapshot.get("scheduling")
    tabla = Table(title="Scheduling del proceso seleccionado", expand=True)
    tabla.add_column("Campo")
    tabla.add_column("Valor", justify="right")

    if entrada is None:
        tabla.add_row("(esperando datos)", "")
        return tabla

    item = _buscar_por_pid(entrada.get("processes"), pid)
    if item is None:
        tabla.add_row("(proceso no encontrado en el muestreo actual)", "")
        return tabla

    tabla.add_row("Nice", str(item.get("nice", "-")))
    tabla.add_row("Priority", str(item.get("priority", "-")))
    tabla.add_row("Policy", str(item.get("policy", "-")))
    tabla.add_row("RT Priority", str(item.get("rt_priority", "-")))
    tabla.add_row("CPU Affinity", str(item.get("affinity", "-")))
    tabla.add_row("Voluntary ctxt switches", str(item.get("voluntary_ctxt_switches", "-")))
    tabla.add_row("Nonvoluntary ctxt switches", str(item.get("nonvoluntary_ctxt_switches", "-")))
    tabla.add_row("SID", str(item.get("sid", "-")))
    tabla.add_row("PGID", str(item.get("pgid", "-")))
    return tabla


def _panel_sistema(snapshot) -> Table:
    entrada = snapshot.get("sistema")
    tabla = Table(title="Sistema global", expand=True)
    tabla.add_column("Campo")
    tabla.add_column("Valor", justify="right")

    if entrada is None:
        tabla.add_row("(esperando datos)", "")
        return tabla

    data = entrada["data"]
    load = data.get("loadavg", {})
    mem = data.get("memory", {})
    uptime = data.get("uptime", {})

    tabla.add_row("Load average (1/5/15)", f"{load.get('load_1', '-')} / {load.get('load_5', '-')} / {load.get('load_15', '-')}")
    tabla.add_row("Uptime (s)", f"{uptime.get('uptime_seconds', '-'):.0f}" if uptime.get("uptime_seconds") is not None else "-")
    tabla.add_row("Memoria total", f"{mem.get('mem_total_kb', '-')} kB")
    tabla.add_row("Memoria disponible", f"{mem.get('mem_available_kb', '-')} kB")
    tabla.add_row("Buffers / Cached", f"{mem.get('buffers_kb', '-')} / {mem.get('cached_kb', '-')} kB")
    tabla.add_row("Swap total / libre", f"{mem.get('swap_total_kb', '-')} / {mem.get('swap_free_kb', '-')} kB")
    tabla.add_row("Procesos totales", str(data.get("process_count", "-")))
    tabla.add_row("Threads totales", str(data.get("total_threads", "-")))
    tabla.add_row("Zombies", str(data.get("zombies", "-")))
    tabla.add_row("Por estado", ", ".join(f"{k}={v}" for k, v in (data.get("states") or {}).items()))

    resumen = snapshot.get("resumen")
    if resumen is not None:
        procesos = resumen["processes"]
        top_cpu = sorted(procesos, key=lambda p: p.get("cpu_percent") or 0, reverse=True)[:3]
        top_mem = sorted(procesos, key=lambda p: p.get("vmrss_kb") or 0, reverse=True)[:3]
        tabla.add_row("Top 3 CPU", ", ".join(f"{p['name']}({p['pid']})" for p in top_cpu))
        tabla.add_row("Top 3 RSS", ", ".join(f"{p['name']}({p['pid']})" for p in top_mem))

    return tabla


def _panel_resumen(pid: int | None) -> Table:
    tabla = Table(title="Resumen", expand=True)
    tabla.add_column("Info")
    tabla.add_row(
        "Datos basicos por proceso en la tabla de arriba. "
        "Cambia de vista (1-7) para ver memoria, FDs, threads, senales o scheduling "
        "del proceso seleccionado."
    )
    return tabla


DETALLE_POR_VISTA = {
    "resumen": lambda snap, pid: _panel_resumen(pid),
    "memoria": lambda snap, pid: _panel_memoria(snap, pid),
    "fds": lambda snap, pid: _panel_fds(snap, pid),
    "threads": lambda snap, pid: _panel_threads(snap, pid),
    "senales": lambda snap, pid: _panel_senales(snap, pid),
    "scheduling": lambda snap, pid: _panel_scheduling(snap, pid),
    "sistema": lambda snap, pid: _panel_sistema(snap),
}


def _tabla_ayuda() -> Table:
    tabla = Table(title="Ayuda - Keybindings")
    tabla.add_column("Tecla")
    tabla.add_column("Accion")

    filas = [
        ("1-7 / r m f t s p g", "Cambiar de vista"),
        ("Flechas arriba/abajo", "Navegar la lista de procesos"),
        ("Enter", "Fijar (pin) / soltar el proceso seleccionado"),
        ("/", "Filtrar por nombre de comando"),
        ("u", "Filtrar por usuario"),
        ("c", "Cambiar orden: CPU% -> RSS -> PID"),
        ("+ / -", "Ajustar el intervalo de refresco de la vista activa"),
        ("q", "Salir del monitor"),
        ("h / ?", "Mostrar/ocultar esta ayuda"),
    ]
    for tecla, accion in filas:
        tabla.add_row(tecla, accion)

    return tabla


def _encabezado(estado: dict, interval_values: dict, verbose_value) -> Text:
    definicion = VISTA_POR_ID[estado["vista"]]
    intervalo = interval_values[estado["vista"]].value

    texto = Text()
    texto.append("Monitor multiproceso  ", style="bold")
    texto.append(f"[{definicion['titulo']}]  ", style="bold cyan")
    texto.append(f"refresco={intervalo:.1f}s (min {definicion['intervalo_minimo']}s)  ")
    texto.append(f"orden={estado['orden']}  ")
    texto.append(f"verbose={'ON' if verbose_value.value else 'OFF'}  ", style="magenta" if verbose_value.value else "")

    if estado["filtro_comando"]:
        texto.append(f"filtro_cmd='{estado['filtro_comando']}'  ", style="yellow")
    if estado["filtro_usuario"]:
        texto.append(f"filtro_user='{estado['filtro_usuario']}'  ", style="yellow")

    if estado["editando"] is not None:
        etiqueta = "comando" if estado["editando"] == "comando" else "usuario"
        texto.append(f"\n>> Filtrar por {etiqueta}: {estado['buffer_edicion']}_", style="bold yellow")

    return texto


def _pie() -> Text:
    return Text(
        "1-7 vista | flechas navegar | Enter pin | / filtro cmd | u filtro user | "
        "c orden | +/- intervalo | h ayuda | q salir",
        style="dim",
    )


def _construir_pantalla(snapshot, estado: dict, interval_values: dict, verbose_value) -> Group:
    resumen = snapshot.get("resumen")
    procesos = resumen["processes"] if resumen is not None else []

    visibles = _armar_lista_visible(procesos, estado)
    estado["indice_seleccionado"] = min(estado["indice_seleccionado"], max(0, len(visibles) - 1))
    estado["_visible_cache"] = visibles

    pid_seleccionado = estado["pid_fijado"]
    if pid_seleccionado is None and visibles:
        pid_seleccionado = visibles[estado["indice_seleccionado"]]["pid"]

    partes = [_encabezado(estado, interval_values, verbose_value)]

    status = snapshot.get("_status")
    if status is not None and (time.time() - status.get("ts", 0)) < 5:
        partes.append(Text(status.get("texto", ""), style=status.get("estilo", "cyan")))

    if estado["mostrar_ayuda"]:
        partes.append(_tabla_ayuda())
    else:
        partes.append(_tabla_procesos(visibles, estado))
        panel_fn = DETALLE_POR_VISTA[estado["vista"]]
        partes.append(panel_fn(snapshot, pid_seleccionado))

    partes.append(_pie())

    return Group(*partes)


def run_display(snapshot, interval_values: dict, verbose_value, stop_event) -> None:
    console = Console()

    estado = {
        "vista": "resumen",
        "indice_seleccionado": 0,
        "pid_fijado": None,
        "filtro_comando": None,
        "filtro_usuario": None,
        "orden": "cpu",
        "mostrar_ayuda": False,
        "editando": None,
        "buffer_edicion": "",
        "_visible_cache": [],
    }

    cola_teclas: queue.Queue = queue.Queue()
    hilo_stop = threading.Event()
    hilo = threading.Thread(target=_leer_teclado, args=(cola_teclas, hilo_stop), daemon=True)
    hilo.start()

    try:
        with Live(console=console, refresh_per_second=4, screen=True) as live:
            while not stop_event.is_set():
                while not cola_teclas.empty():
                    tecla = cola_teclas.get_nowait()
                    _procesar_tecla(tecla, estado, interval_values, verbose_value, stop_event)

                live.update(_construir_pantalla(snapshot, estado, interval_values, verbose_value))
                time.sleep(0.1)
    finally:
        hilo_stop.set()
        if hilo is not None:
            hilo.join(timeout=1)