import asyncio
import statistics
import time

import httpx

URL = "http://localhost:9000/demora/1"
N = 20
REPETICIONES = 3


async def secuencial() -> float:
    async with httpx.AsyncClient() as cliente:
        t0 = time.perf_counter()
        for _ in range(N):
            await cliente.get(URL)  # cada await espera a que termine el anterior
        return time.perf_counter() - t0


async def concurrente() -> float:
    async with httpx.AsyncClient() as cliente:
        t0 = time.perf_counter()
        await asyncio.gather(*(cliente.get(URL) for _ in range(N)))
        return time.perf_counter() - t0


async def main() -> None:
    seq, con = [], []
    for i in range(REPETICIONES):
        seq.append(await secuencial())
        print(f"  secuencial  {i + 1}/{REPETICIONES}: {seq[-1]:.2f} s", flush=True)
    for i in range(REPETICIONES):
        con.append(await concurrente())
        print(f"  concurrente {i + 1}/{REPETICIONES}: {con[-1]:.2f} s", flush=True)
    print(f"secuencial:  mediana {statistics.median(seq):.2f} s")
    print(f"concurrente: mediana {statistics.median(con):.2f} s")
    print(f"speedup: {statistics.median(seq) / statistics.median(con):.1f}x")


asyncio.run(main())