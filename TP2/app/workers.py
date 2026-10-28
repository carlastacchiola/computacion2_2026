import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from . import tareas as modulo_tareas
from .modelos import Estado, NuevaTarea, Tarea
from .tareas import EJECUTORES

log = logging.getLogger("plataforma")

DIR_ESTADO = Path(os.environ.get("DIR_ESTADO", "."))
GRACIA_APAGADO = 10.0  # segundos que esperamos a las tareas en curso


class Plataforma:
    def __init__(self, n_workers: int = 3):
        self.n_workers = n_workers
        self.tareas: dict[str, Tarea] = {}
        self.cola: asyncio.Queue[str] = asyncio.Queue()  # guarda ids
        self._workers: list[asyncio.Task] = []
        self.aceptando = True

    # ---------- ciclo de vida ----------
    def iniciar(self) -> None:
        self.reportar_volcado_previo()
        for n in range(self.n_workers):
            t = asyncio.create_task(self._worker(n), name=f"worker-{n}")
            self._workers.append(t)
        log.info("Pool iniciado con %d workers", self.n_workers)

    async def detener(self) -> None:
        self.aceptando = False  # 1) no más tareas nuevas
        log.info("Apagado: dejo de aceptar tareas")

        # 2) esperamos (con límite) a las tareas en ejecución
        en_curso = [
            t._ejecucion
            for t in self.tareas.values()
            if t.estado == Estado.EJECUTANDO and t._ejecucion is not None
        ]
        if en_curso:
            log.info(
                "Esperando %d tareas en curso (máx %.0f s)",
                len(en_curso), GRACIA_APAGADO,
            )
            _, pendientes = await asyncio.wait(en_curso, timeout=GRACIA_APAGADO)
            for p in pendientes:
                p.cancel()  # se acabó la gracia: las cancelamos
            if pendientes:
                await asyncio.gather(*pendientes, return_exceptions=True)

        # 3) paramos los workers
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        modulo_tareas.POOL_CPU.shutdown(wait=False, cancel_futures=True)

        # 4) volcamos el estado (después de esperar, así queda actualizado)
        self.volcar_estado()
        log.info("Pool detenido")

    def volcar_estado(self) -> Path:
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = DIR_ESTADO / f"estado_{marca}.json"
        datos = {
            "guardado": marca,
            "estadisticas": self.estadisticas(),
            "tareas": [t.a_dict() for t in self.tareas.values()],
        }
        ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False))
        log.info("Estado volcado en %s (%d tareas)", ruta, len(self.tareas))
        return ruta

    def reportar_volcado_previo(self) -> None:
        volcados = sorted(DIR_ESTADO.glob("estado_*.json"))
        if volcados:
            log.info("Volcado previo encontrado: %s", volcados[-1])
        else:
            log.info("No hay volcado previo")

    # ---------- operaciones (las llama la API) ----------
    def encolar(self, nueva: NuevaTarea) -> Tarea:
        tarea = Tarea(
            tipo=nueva.tipo,
            parametros=nueva.parametros,
            timeout=nueva.timeout,
        )
        self.tareas[tarea.id] = tarea
        self.cola.put_nowait(tarea.id)  # no bloquea: la cola es ilimitada
        return tarea

    def cancelar(self, tarea_id: str) -> Tarea | None:
        tarea = self.tareas.get(tarea_id)
        if tarea is None:
            return None
        if tarea.estado == Estado.PENDIENTE:
            tarea.estado = Estado.CANCELADA
            tarea.fin = time.time()
            # sigue en la cola: el worker la va a saltear al sacarla
        elif tarea.estado == Estado.EJECUTANDO:
            if tarea._ejecucion is not None and not tarea._ejecucion.done():
                tarea.estado = Estado.CANCELADA
                tarea.fin = time.time()
                tarea._ejecucion.cancel()
        return tarea

    def estadisticas(self) -> dict:
        por_estado = {e.value: 0 for e in Estado}
        for t in self.tareas.values():
            por_estado[t.estado.value] += 1
        return {
            "por_estado": por_estado,
            "workers_total": self.n_workers,
            "workers_ocupados": por_estado["ejecutando"],
            "en_cola": self.cola.qsize(),
        }

    # ---------- el worker ----------
    async def _worker(self, n: int) -> None:
        while True:
            tarea_id = await self.cola.get()
            tarea = self.tareas[tarea_id]
            try:
                if tarea.estado != Estado.PENDIENTE or not self.aceptando:
                    continue  # cancelada en cola, o apagando: no la arranco

                tarea.estado = Estado.EJECUTANDO
                tarea.inicio = time.time()
                log.info("worker-%d ejecuta %s (%s)", n, tarea.id, tarea.tipo)

                funcion = EJECUTORES[tarea.tipo]
                tarea._ejecucion = asyncio.create_task(funcion(tarea.parametros))
                tarea.resultado = await asyncio.wait_for(
                    tarea._ejecucion, timeout=tarea.timeout
                )
                tarea.estado = Estado.COMPLETADA
            except TimeoutError:
                tarea.estado = Estado.FALLIDA
                tarea.error = f"Timeout: superó los {tarea.timeout} s"
                log.warning("Tarea %s: timeout", tarea.id)
            except asyncio.CancelledError:
                if tarea.estado == Estado.CANCELADA:
                    log.info("Tarea %s cancelada", tarea.id)  # DELETE: el worker sigue
                else:
                    tarea.estado = Estado.FALLIDA
                    tarea.error = "Interrumpida por el apagado del servicio"
                    raise  # cancelaron al worker: que se propague
            except Exception as e:
                tarea.estado = Estado.FALLIDA
                tarea.error = f"{type(e).__name__}: {e}"
                log.exception("Tarea %s falló", tarea.id)
            finally:
                if tarea.fin is None and tarea.estado != Estado.PENDIENTE:
                    tarea.fin = time.time()
                tarea._ejecucion = None
                self.cola.task_done()