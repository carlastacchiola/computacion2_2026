import asyncio
import sys
import time

import httpx

API = "http://localhost:8000"


async def medir(n: int, segundos: float) -> None:
    limites = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(timeout=300, limits=limites) as c:
        cuerpo = {"tipo": "esperar", "parametros": {"segundos": segundos}}
        sem = asyncio.Semaphore(50)

        async def enviar() -> int:
            async with sem:
                return (await c.post(f"{API}/tareas", json=cuerpo)).status_code

        t0 = time.perf_counter()
        codigos = await asyncio.gather(*(enviar() for _ in range(n)))
        t_envio = time.perf_counter() - t0
        ok = codigos.count(202)

        lat = {}
        for ruta in ("/estadisticas", "/tareas"):
            t1 = time.perf_counter()
            await c.get(API + ruta)
            lat[ruta] = time.perf_counter() - t1

        while True:
            e = (await c.get(API + "/estadisticas")).json()
            if e["por_estado"]["pendiente"] == 0 and e["por_estado"]["ejecutando"] == 0:
                break
            await asyncio.sleep(0.5)
        total = time.perf_counter() - t0

    print(f"tareas: {n} ({ok} aceptadas, {n - ok} con error)  duración c/u: {segundos} s")
    print(f"  envío de las {n} tareas: {t_envio:.2f} s  ({n / t_envio:.0f} POST/s)")
    print(f"  GET /estadisticas con carga: {lat['/estadisticas'] * 1000:.0f} ms")
    print(f"  GET /tareas con carga:       {lat['/tareas'] * 1000:.0f} ms")
    print(f"  total hasta terminar todas:  {total:.2f} s  ({n / total:.1f} tareas/s)")


n = int(sys.argv[1])
segundos = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
asyncio.run(medir(n, segundos))