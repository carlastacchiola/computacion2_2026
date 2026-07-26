from __future__ import annotations

import json
import os
import signal
import time


class ManejadorSenales:

    def __init__(self) -> None:
        self._read_fd, self._write_fd = os.pipe()
        os.set_blocking(self._read_fd, False)
        os.set_blocking(self._write_fd, False)

        signal.set_wakeup_fd(self._write_fd)

        self._shutdown_requested = False
        self._reload_requested = False
        self._dump_requested = False
        self._toggle_verbose_requested = False
        self._repaint_requested = False

    def instalar_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._marcar_shutdown)
        signal.signal(signal.SIGTERM, self._marcar_shutdown)
        signal.signal(signal.SIGHUP, self._marcar_reload)
        signal.signal(signal.SIGUSR1, self._marcar_dump)
        signal.signal(signal.SIGUSR2, self._marcar_toggle_verbose)

        if hasattr(signal, "SIGWINCH"):
            signal.signal(signal.SIGWINCH, self._marcar_repaint)


    def _marcar_shutdown(self, signum, frame) -> None:
        self._shutdown_requested = True

    def _marcar_reload(self, signum, frame) -> None:
        self._reload_requested = True

    def _marcar_dump(self, signum, frame) -> None:
        self._dump_requested = True

    def _marcar_toggle_verbose(self, signum, frame) -> None:
        self._toggle_verbose_requested = True

    def _marcar_repaint(self, signum, frame) -> None:
        self._repaint_requested = True

    def drenar_pipe(self) -> None:
        """Vacia el pipe del self-pipe"""
        try:
            while os.read(self._read_fd, 4096):
                pass
        except BlockingIOError:
            pass

    def hay_shutdown_pendiente(self) -> bool:
        return self._shutdown_requested

    def consumir_reload(self) -> bool:
        if self._reload_requested:
            self._reload_requested = False
            return True
        return False

    def consumir_dump(self) -> bool:
        if self._dump_requested:
            self._dump_requested = False
            return True
        return False

    def consumir_toggle_verbose(self) -> bool:
        if self._toggle_verbose_requested:
            self._toggle_verbose_requested = False
            return True
        return False

    def consumir_repaint(self) -> bool:
        if self._repaint_requested:
            self._repaint_requested = False
            return True
        return False


def ignorar_senales_de_control() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    signal.signal(signal.SIGUSR1, signal.SIG_DFL)
    signal.signal(signal.SIGUSR2, signal.SIG_DFL)

    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)

    try:
        signal.set_wakeup_fd(-1)
    except (ValueError, OSError):
        pass


def cargar_config(path: str = "config.json") -> dict:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def volcar_snapshot(snapshot, directorio: str = ".") -> str:
    timestamp = int(time.time())
    ruta = os.path.join(directorio, f"dump_{timestamp}.json")

    datos_planos = _a_estructura_nativa(snapshot)

    with open(ruta, "w", encoding="utf-8") as file:
        json.dump(datos_planos, file, indent=2, ensure_ascii=False, default=str)

    return ruta


def _a_estructura_nativa(valor):
    if hasattr(valor, "items"):
        return {clave: _a_estructura_nativa(v) for clave, v in valor.items()}

    if isinstance(valor, (list, tuple)):
        return [_a_estructura_nativa(v) for v in valor]

    return valor