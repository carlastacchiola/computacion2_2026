import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .modelos import Estado, NuevaTarea
from .workers import Plataforma

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

plataforma = Plataforma(n_workers=3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Antes del yield: arranque
    plataforma.iniciar()
    yield
    # Después del yield: apagado
    await plataforma.detener()


app = FastAPI(title="Plataforma de Tareas Distribuidas", lifespan=lifespan)


@app.post("/tareas", status_code=202)
async def crear_tarea(nueva: NuevaTarea):
    if not plataforma.aceptando:
        raise HTTPException(status_code=503, detail="Apagando: no se aceptan tareas")
    tarea = plataforma.encolar(nueva)
    return {"id": tarea.id, "estado": tarea.estado.value}


@app.get("/tareas")
async def listar_tareas(estado: Estado | None = None):
    tareas = plataforma.tareas.values()
    if estado:
        tareas = [t for t in tareas if t.estado == estado]
    return [t.a_dict() for t in tareas]


@app.get("/tareas/{tarea_id}")
async def obtener_tarea(tarea_id: str):
    tarea = plataforma.tareas.get(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return tarea.a_dict()


@app.delete("/tareas/{tarea_id}")
async def cancelar_tarea(tarea_id: str):
    tarea = plataforma.cancelar(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    if tarea.estado != Estado.CANCELADA:
        raise HTTPException(
            status_code=409, detail=f"La tarea ya terminó ({tarea.estado.value})"
        )
    return tarea.a_dict()


@app.get("/estadisticas")
async def estadisticas():
    return plataforma.estadisticas()