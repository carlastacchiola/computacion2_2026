import asyncio
import hashlib
from concurrent.futures import ProcessPoolExecutor
import time
import httpx

# Pool de procesos para tareas CPU-bound. Se crea una vez, a nivel de módulo.
POOL_CPU = ProcessPoolExecutor(max_workers=2)


def _hash_iterado(texto: str, iteraciones: int) -> str:
    """Función COMÚN (no async). Corre en otro proceso.
    Tiene que estar a nivel de módulo para poder enviarse (pickle) al proceso hijo."""
    h = texto.encode()
    for _ in range(iteraciones):
        h = hashlib.sha256(h).digest()
    return h.hex()


async def esperar(parametros: dict) -> dict:
    segundos = float(parametros.get("segundos", 1))
    await asyncio.sleep(segundos)
    return {"durmio": segundos}


async def hashear(parametros: dict) -> dict:
    texto = str(parametros.get("texto", ""))
    iteraciones = int(parametros.get("iteraciones", 1_000_000))

    if parametros.get("bloquear"):
        # SOLO PARA LA MEDICIÓN 2: ejecuta directo en el event loop (mal a propósito).
        resultado = _hash_iterado(texto, iteraciones)
    else:
        loop = asyncio.get_running_loop()
        resultado = await loop.run_in_executor(
            POOL_CPU, _hash_iterado, texto, iteraciones
        )
    return {"hash": resultado, "iteraciones": iteraciones}

async def _descargar_una(cliente: httpx.AsyncClient, url: str) -> dict:
    inicio = time.perf_counter()
    try:
        r = await cliente.get(url)
        return {
            "url": url,
            "status": r.status_code,
            "bytes": len(r.content),
            "segundos": round(time.perf_counter() - inicio, 3),
        }
    except httpx.HTTPError as e:
        return {
            "url": url,
            "error": f"{type(e).__name__}: {e}",
            "segundos": round(time.perf_counter() - inicio, 3),
        }


async def descargar(parametros: dict) -> dict:
    urls = parametros.get("urls", [])
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cliente:
        resultados = await asyncio.gather(*(_descargar_una(cliente, u) for u in urls))
    return {"resultados": resultados}

EJECUTORES = {
    "esperar": esperar,
    "hashear": hashear,
    "descargar": descargar,
}