import asyncio
import logging
import time
from . import tareas as modulo_tareas

from .modelos import Estado, NuevaTarea, Tarea
from .tareas import EJECUTORES

log = logging.getLogger("plataforma")


class Plataforma:
    def __init__(self, n_workers: int = 3):
        self.n_workers = n_workers
        self.tareas: dict[str, Tarea] = {}
        self.cola: asyncio.Queue[str] = asyncio.Queue()  # guarda ids
        self._workers: list[asyncio.Task] = []

    # ---------- ciclo de vida ----------
    def iniciar(self) -> None:
        for n in range(self.n_workers):
            t = asyncio.create_task(self._worker(n), name=f"worker-{n}")
            self._workers.append(t)
        log.info("Pool iniciado con %d workers", self.n_workers)

    async def detener(self) -> None:
        for w in self._workers:
            w.cancel()
        # return_exceptions=True: esperamos a que terminen de cancelarse
        # sin que el CancelledError rompa el gather.
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        modulo_tareas.POOL_CPU.shutdown(wait=False, cancel_futures=True)
        log.info("Pool detenido")

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

    
    async def _worker(self, n: int) -> None:
        while True:
            tarea_id = await self.cola.get()
            tarea = self.tareas[tarea_id]
            try:
                if tarea.estado != Estado.PENDIENTE:
                    continue  # la cancelaron mientras esperaba en la cola

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
                # wait_for ya canceló la task interna y esperó a que termine
                tarea.estado = Estado.FALLIDA
                tarea.error = f"Timeout: superó los {tarea.timeout} s"
                log.warning("Tarea %s: timeout", tarea.id)
            except asyncio.CancelledError:
                if tarea.estado == Estado.CANCELADA:
                    log.info("Tarea %s cancelada", tarea.id)  # DELETE: el worker sigue vivo
                else:
                    raise  # cancelaron al worker (apagado): que se propague
            except Exception as e:
                tarea.estado = Estado.FALLIDA
                tarea.error = f"{type(e).__name__}: {e}"
                log.exception("Tarea %s falló", tarea.id)
            finally:
                if tarea.fin is None:
                    tarea.fin = time.time()
                tarea._ejecucion = None
                self.cola.task_done()    