import asyncio

from fastapi import FastAPI

app = FastAPI(title="Servidor de prueba (demora fija)")


@app.get("/demora/{segundos}")
async def demora(segundos: float):
    await asyncio.sleep(segundos)
    return {"demora": segundos}