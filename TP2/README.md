# TP2: Plataforma de Tareas Distribuidas

**Computación II, Universidad de Mendoza, 2026**
**Alumna:** Carla Stacchiola

Servicio HTTP al que se le encargan trabajos, que los ejecuta de forma concurrente con un pool de workers asíncronos y permite consultar su estado, su resultado y cancelarlos.

| Parte | Estado |
|-------|--------|
| API HTTP (5 endpoints) | Hecho |
| Cola + pool de workers (cantidad configurable) | Hecho |
| Tareas `esperar`, `descargar`, `hashear` | Hecho |
| Cancelación y timeouts | Hecho |
| Apagado ordenado + volcado a JSON | Hecho |
| Docker (`Dockerfile`, `docker-compose.yml`) | Hecho |
| Medición 1: I/O secuencial vs concurrente | Hecha |
| Medición 2: event loop bloqueado | Hecha |
| Medición 3: techo del pool | Hecha |
| Bonus | No hechos |

---

## 1. Descripción y uso

### Cómo levantarlo

```bash
git clone https://github.com/carlastacchiola/computacion2_2026.git
cd computacion2_2026/TP2
docker compose up --build
```

La API queda en `http://localhost:8000` y la documentación interactiva en `http://localhost:8000/docs`.

Variables de entorno (opcionales):

| Variable | Por defecto | Qué hace |
|----------|-------------|----------|
| `N_WORKERS` | `3` | Cantidad de workers del pool. Ej.: `N_WORKERS=10 docker compose up --build` |
| `DIR_ESTADO` | `/data` en Docker | Carpeta donde se escriben los volcados. En Docker se monta como `./estado` |

Para apagarlo de forma ordenada: `Ctrl+C` o `docker compose stop`. El volcado queda en `TP2/estado/estado_<timestamp>.json`.

### Sin Docker (alternativa)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app
```

### Endpoints

| Método | Ruta | Qué hace |
|--------|------|----------|
| `POST` | `/tareas` | Encola una tarea. Responde `202` con `id` y estado, sin esperar a que termine (`503` si se está apagando) |
| `GET` | `/tareas` | Lista tareas. Filtro opcional: `?estado=ejecutando` |
| `GET` | `/tareas/{id}` | Estado y resultado de una tarea (`404` si no existe) |
| `DELETE` | `/tareas/{id}` | Cancela una tarea pendiente o en ejecución (`409` si ya terminó) |
| `GET` | `/estadisticas` | Totales por estado, workers ocupados y largo de la cola |

Estados: `pendiente`, `ejecutando`, `completada`, `fallida`, `cancelada`.

### Tipos de tarea

| Tipo | Naturaleza | Parámetros |
|------|-----------|------------|
| `esperar` | I/O simulado | `segundos` |
| `descargar` | I/O-bound | `urls` (lista) |
| `hashear` | CPU-bound | `texto`, `iteraciones`, `bloquear` (opcional, solo para la medición 2) |

Todas aceptan además un `timeout` en segundos (por defecto 30).

### Ejemplos con `curl`

```bash
# Encolar una espera de 5 s
curl -s -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo":"esperar","parametros":{"segundos":5}}'

# Descargar varias URLs a la vez
curl -s -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo":"descargar","parametros":{"urls":["https://httpbin.org/delay/2","https://httpbin.org/delay/2"]}}'

# Hash iterado (CPU-bound)
curl -s -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo":"hashear","parametros":{"texto":"hola","iteraciones":5000000}}'

# Tarea con timeout de 2 s que dura 10 s (termina "fallida")
curl -s -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo":"esperar","parametros":{"segundos":10},"timeout":2}'

# Consultar, listar, cancelar y ver estadísticas
curl -s localhost:8000/tareas/<ID>
curl -s "localhost:8000/tareas?estado=pendiente"
curl -s -X DELETE localhost:8000/tareas/<ID>
curl -s localhost:8000/estadisticas
```

---

## 2. Arquitectura

```
   Cliente HTTP
        |
        v
  ┌──────────────────┐   put_nowait(id)   ┌──────────────────┐
  │   API (FastAPI)  │───────────────────>│  asyncio.Queue   │
  │  POST /tareas    │                    │  (ids de tareas) │
  │  GET  /tareas    │                    └────────┬─────────┘
  │  GET  /tareas/id │                             │ await get()
  │  DEL  /tareas/id │                             v
  │  GET  /estadist. │                    ┌──────────────────┐
  └────────┬─────────┘                    │ Pool de N workers│
           │ lee/modifica                 │ (corrutinas)     │
           v                              └───┬──────────┬───┘
  ┌──────────────────┐                        │          │
  │ dict[id, Tarea]  │<───────────────────────┘          │ run_in_executor
  │ (estado en       │      actualiza estado             v
  │  memoria)        │                        ┌──────────────────────┐
  └────────┬─────────┘                        │ ProcessPoolExecutor  │
           │ al apagar (SIGTERM/SIGINT)       │ (2 procesos, hashear)│
           v                                  └──────────────────────┘
   estado_<timestamp>.json
```

**Flujo de una tarea:**

1. `POST /tareas` valida el cuerpo (pydantic), crea una `Tarea` en estado `pendiente`, la guarda en el diccionario y mete su `id` en la cola con `put_nowait`. Responde `202` al instante.
2. Un worker libre saca el `id` con `await cola.get()`, pasa la tarea a `ejecutando` y registra `inicio`.
3. El worker busca la función por tipo en el diccionario `EJECUTORES`, la envuelve en una `asyncio.Task` (guardada en la tarea para poder cancelarla) y la espera con `asyncio.wait_for(..., timeout)`.
4. Según cómo termine, la tarea pasa a `completada`, `fallida` (excepción o timeout) o `cancelada` (`DELETE`).

### Estructura del código

```
TP2/
├── app/
│   ├── main.py             # FastAPI, endpoints, lifespan
│   ├── modelos.py          # Estado (Enum), NuevaTarea (pydantic), Tarea (dataclass)
│   ├── workers.py          # Plataforma: cola, workers, cancelación, apagado y volcado
│   ├── tareas.py           # esperar, descargar, hashear y el despachador EJECUTORES
│   └── servidor_prueba.py  # servidor con demora fija, solo para las mediciones
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── medicion_io.py          # medición 1 (cliente directo)
├── medicion_pool.py        # medición 3 (techo del pool)
├── resultados_A.txt        # salida cruda del experimento A de la medición 3
├── resultados_B.txt        # salida cruda del experimento B
├── cpu_C.txt               # muestras de CPU del experimento C
├── requirements.txt
└── README.md
```

---

## 3. Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

`queue.Queue` está pensada para threads: `get()` **bloquea el hilo** hasta que haya un elemento. Si un worker-corrutina la usara, bloquearía el hilo del event loop entero y se congelaría toda la API. `asyncio.Queue.get()` es una corrutina: mientras no hay nada, el worker se suspende en el `await` y el loop sigue atendiendo a los demás. Además, `asyncio.Queue` no necesita locks internos porque todo corre en un solo hilo.

La cola guarda **ids** y no objetos `Tarea`, así el diccionario `tareas` es la única fuente de verdad del estado.

### ¿Cómo evito que una tarea CPU-bound congele la API?

Un `await` solo cede el control cuando la corrutina *espera* algo. Un bucle de millones de hashes no espera nada: nunca cede, y como el event loop vive en ese mismo hilo, no puede atender ni un `GET`. Por eso `hashear` delega el cálculo con `loop.run_in_executor` a un `ProcessPoolExecutor` (2 procesos). Se eligen **procesos y no hilos** porque con hilos el cálculo seguiría compitiendo por el GIL con el event loop; un proceso aparte tiene su propio intérprete y corre en otro núcleo. La corrutina de la tarea queda suspendida en el `await` y el loop sigue libre. Se mide en la sección 4.2.

### ¿Por qué los workers no necesitan un `Lock`?

Porque el event loop es cooperativo y corre en un solo hilo: una corrutina solo puede ser interrumpida en un `await`. Instrucciones como `tarea.estado = Estado.EJECUTANDO` no tienen ningún `await` en el medio, así que nadie puede observar un estado a medias. Un `Lock` haría falta si hubiera varios hilos modificando los mismos datos.

### ¿Cómo implementé la cancelación?

- El worker no ejecuta la función directamente: crea una `asyncio.Task` y la guarda en `tarea._ejecucion`. El `DELETE` tiene así a quién llamarle `.cancel()`.
- **Tarea pendiente:** se marca `cancelada`. El id sigue en la cola, y cuando un worker lo saca ve que el estado ya no es `pendiente` y lo saltea.
- **Tarea en ejecución:** `cancelar()` marca `cancelada` y llama a `.cancel()` sobre la task. La función recibe un `CancelledError` en su `await` actual.
- **Distinguir dos cancelaciones:** el worker también puede recibir un `CancelledError` si lo cancelan a él (apagado del servicio). Como `cancelar()` marca el estado *antes* de cancelar, el worker sabe cuál es cuál: si el estado es `cancelada`, fue un `DELETE` y sigue vivo; si no, marca la tarea como `fallida` por apagado y relanza la excepción para que el worker termine.
- **Recursos:** en `descargar`, el `async with httpx.AsyncClient` cierra las conexiones al salir y `asyncio.gather` cancela a las descargas hermanas, así que no quedan corrutinas huérfanas. Verificado: tras cancelar una descarga a mitad, `/estadisticas` mostró 0 workers ocupados y 0 tareas en ejecución.
- **Excepción conocida:** `hashear` en otro proceso no se puede interrumpir (ver 4.4 y sección 6).

### Timeouts

`asyncio.wait_for(task, timeout)` cancela la task interna, espera a que termine de cancelarse y recién ahí levanta `TimeoutError`. El worker la atrapa y marca la tarea como `fallida` con el motivo en `error`. Medido: una tarea de 10 s con `timeout=2` falló a los 2,00 s.

Detalle: el cronómetro del timeout (y `inicio`) arranca cuando el worker toma la tarea, no cuando el proceso del pool empieza a calcular. Una tarea CPU-bound que espera lugar en el pool consume timeout sin haber calculado.

### ¿Qué pasa si un worker lanza una excepción no capturada?

El bucle del worker tiene un `except Exception` que marca la tarea como `fallida`, guarda `"TipoDeError: mensaje"` en `error`, loguea el traceback y **el worker sigue vivo** para la próxima tarea. Se captura `Exception` y no `BaseException` a propósito: `CancelledError` hereda de `BaseException` desde Python 3.8, y debe propagarse si cancelan al worker. En `descargar`, además, cada URL captura su propio `httpx.HTTPError`, así una URL caída no tumba a las demás.

### Apagado ordenado

`uvicorn` ya captura `SIGTERM` y `SIGINT` y, al recibirlas, ejecuta la parte del `lifespan` posterior al `yield`. Ahí está todo el apagado, sin `loop.add_signal_handler` propio (que solo existe en Unix, el problema que menciona el punto 4.1 del enunciado). Pasos, en este orden:

1. Se pone `aceptando = False`: el `POST` responde `503` y los workers dejan de tomar tareas pendientes, que quedan `pendiente` en el volcado.
2. Se espera con `asyncio.wait` (límite de 10 s, `GRACIA_APAGADO`) a las tareas en ejecución. Las que no terminan se cancelan y quedan `fallida` con el motivo "Interrumpida por el apagado del servicio".
3. Se cancelan los workers y se cierra el pool de procesos.
4. Se escribe `estado_<timestamp>.json` **después** de esperar, para que refleje el estado final.

Al arrancar se busca el último `estado_*.json` y se reporta por log (no se reanudan las tareas, solo se informa).

Verificado: `SIGINT` (Ctrl+C) fuera de Docker y `SIGTERM` dentro de Docker con `docker compose stop`. Fuera de Docker, una tarea de 30 s se cortó tras los 10 s de gracia y quedó `fallida` en el JSON. Dentro de Docker, con una tarea de 60 s, el log muestra la espera de 10 s (22:12:40 a 22:12:50), el volcado a `./estado` y `Pool detenido`, y el contenedor salió con código 0 (no 137, o sea que Docker no lo mató por tiempo).

### Docker

- **Forma exec en `CMD`** (lista JSON): `uvicorn` queda como PID 1 y recibe `SIGTERM` directo. Con la forma shell lo recibiría un `/bin/sh` intermedio y el apagado no correría.
- **`stop_grace_period: 20s`** en el compose: `docker compose stop` mata el contenedor a los 10 s por defecto, igual que nuestra gracia de apagado, y el volcado no llegaría a escribirse.
- **`--host 0.0.0.0`:** dentro del contenedor, `127.0.0.1` es solo el propio contenedor; con `0.0.0.0` el puerto publicado llega desde el host.
- **Volumen `./estado:/data`:** el sistema de archivos del contenedor se pierde al borrarlo; con el volumen, el volcado sobrevive y el próximo arranque lo detecta.
- **Servidor de prueba como servicio con `profiles`:** `docker compose up --build` levanta solo la API (lo que pide la consigna). Para las mediciones: `docker compose --profile medicion up --build`.
- **`ProcessPoolExecutor` en Docker:** corre sobre Linux (`fork`), por lo que la guarda `if __name__ == '__main__'` del punto 4.1 no es necesaria con `uvicorn app.main:app`.

### ¿Por qué `httpx` y no `requests`?

`requests` es síncrona: cada llamada bloquearía el event loop. `httpx` ofrece `AsyncClient` con una API casi idéntica a la de `requests` y se integra directo con `asyncio`.

### Otras decisiones

- **Despachador por diccionario** (`EJECUTORES`): el worker no sabe qué hace cada tipo; agregar un tipo es agregar una línea.
- **`202 Accepted`** en el `POST`: es el código correcto para "recibí el pedido, lo proceso aparte".
- **Estado dentro de la clase `Plataforma`** en lugar de globales sueltas.

---

## 4. Mediciones

Máquina: Lenovo V15 G2 ITL, Ubuntu (Python 3.12). Cliente y servidor corren en la misma máquina, así que comparten CPU. Salvo que se indique otra cosa, cada cifra es de una corrida.

### 4.1 Concurrencia I/O

Servidor local con demora fija de 1 s (`servidor_prueba.py`, puerto 9000). El script `medicion_io.py` hace 20 pedidos con `httpx`: secuenciales (`for` con `await` adentro) y concurrentes (`asyncio.gather`). Se corrió dos veces, con 3 repeticiones cada vez:

| Corrida | Secuencial (3 repeticiones) | Concurrente (3 repeticiones) | Speedup (medianas) |
|---------|-----------------------------|------------------------------|--------------------|
| 1 | 20,14 / 20,12 / 20,12 s | 1,03 / 1,03 / 1,02 s | **19,6x** |
| 2 | 20,15 / 20,12 / 20,13 s | 1,03 / 1,02 / 1,02 s | **19,7x** |

A través de la plataforma, una tarea `descargar` con las mismas 20 URLs (`http://prueba:9000/demora/1`) tardó **1,07 s** (una sola muestra).

**Interpretación:** el secuencial tarda 20 × 1 s más unos 6 ms de overhead por pedido. El concurrente tarda aproximadamente lo del pedido más lento (1 s) más unos 30 ms de costo de crear 20 conexiones. El speedup no llega a 20x porque ese costo fijo no se paraleliza. Que la plataforma dé casi lo mismo que el cliente directo indica que la cola y el pool no agregan costo apreciable en este caso.

Antes de tener el servidor local se probó contra `httpbin.org` (5 descargas de `delay/2`): dos corridas dieron 6,20 s y 2,81 s para la misma tarea. Un servicio público agrega ruido que no se controla, y por eso la medición final usa el servidor local.

### 4.2 El event loop bloqueado

Tarea `hashear` con 25.000.000 de iteraciones de SHA-256 (duración medida: **9,31 s**). Se midió la latencia de `GET /tareas` mientras la tarea estaba en `ejecutando`.

| Modo | Latencia de `GET /tareas` durante el hash |
|------|-------------------------------------------|
| Con `run_in_executor` | **1,0 a 2,0 ms** (10 muestras, todas con la tarea ejecutando) |
| Sin executor (`"bloquear": true`) | **8,50 s** |

Una diferencia de unas 6.000 veces con el mismo cálculo. El hash no tarda menos con executor: tarda lo mismo. Lo que cambia es **quién espera**. Con executor, solo espera la corrutina de esa tarea; sin él, el cálculo corre en el hilo del event loop y, al no haber ningún `await`, espera todo el servidor. Los 8,50 s son los 9,31 s del hash menos el medio segundo de `sleep` previo al `GET` y lo que tardó el worker en arrancar.

### 4.3 Techo del pool

Tareas `esperar`, 60 por corrida, de 1 s cada una. Se varió `N_WORKERS` (`resultados_A.txt`):

| Workers | Total | Rondas `ceil(60/W)` | Tareas/s |
|---------|-------|---------------------|----------|
| 3 | 20,43 s | 20 | 2,9 |
| 10 | 6,24 s | 6 | 9,6 |
| 30 | 2,15 s | 2 | 27,9 |
| 60 | 1,13 s | 1 | 53,3 |
| 200 | 1,11 s | 1 | 53,8 |

**El techo es la cantidad de workers.** Cada worker atiende una tarea por vez, aunque esa tarea sea una espera que casi no consume CPU. El tiempo total es `ceil(60/W) × 1 s` más un overhead de 0,1 a 0,4 s. Con 200 workers no apareció ningún segundo límite, pero tampoco se puede concluir nada de esa fila: había solo 60 tareas, así que 60 workers ya alcanzaban para tomarlas todas a la vez.

**Carga creciente** (`resultados_B.txt`): `N_WORKERS=10`, tareas de 0 s (para aislar el costo del sistema del de las tareas):

| Tareas | Envío | GET `/tareas` | GET `/estadisticas` | Memoria |
|--------|-------|---------------|---------------------|---------|
| 100 | 0,26 s | 4 ms | 2 ms | 36,0 MiB |
| 1.000 | 3,75 s | 23 ms | 3 ms | 37,8 MiB |
| 10.000 (3 corridas) | 19,29 / 10,62 / 10,35 s | 235 / 205 / 204 ms | 8 / 9 / 9 ms | 46,9 MiB |

- **Qué se degrada primero: `GET /tareas`.** Su latencia crece de forma aproximadamente lineal con la cantidad de tareas (10 veces más tareas, unas 10 veces más latencia). El endpoint recorre todo el diccionario y arma el JSON dentro de una corrutina sin ningún `await`, así que mientras lo hace el event loop no atiende a nadie. Esto es consistente con lo medido, pero no medí directamente que otros pedidos quedaran bloqueados durante ese lapso. La latencia se midió desde el cliente e incluye transferir y leer el JSON.
- **Nada se rompió con 10.000 tareas de golpe:** las 10.000 se aceptaron (`202`), sin errores, y terminaron.
- **Memoria:** unos 1,1 KB por tarea ((46,9 − 36,0) MiB / 9.900 tareas), y nunca se libera porque el diccionario no se purga.
- **Los POST/s no son un techo del servidor.** Con 10.000 tareas el envío tardó 19,29 s en una corrida y 10,6 y 10,4 s en las otras dos, sin cambiar nada. No sé a qué se debe la primera. Además, el cliente (un script en Python) puede ser el cuello de botella en vez de la API.

**CPU durante la carga** (`cpu_C.txt`, 10.000 tareas, `docker stats` muestreado mientras corría): las cinco muestras más altas van de 47 % a 65 % de un núcleo. Ninguna llegó a 100 %, lo que indica que el event loop de la API no se saturó en esa corrida. La medición es gruesa (cada lectura de `docker stats` promedia un par de segundos, y un pico corto queda suavizado), así que es un indicio y no una prueba. Para saber si el cuello de botella estaba en el cliente habría que correr dos clientes en paralelo.

### 4.4 Medición adicional: costo de cancelar un `hashear`

Pool de CPU de 2 procesos, hashes de 25M iteraciones (~9,3 s). Se lanzó un hash, se canceló con `DELETE` a los 2 s y de inmediato se mandaron dos hashes nuevos:

| Tarea | Duración | Interpretación |
|-------|----------|----------------|
| Primera nueva | 9,93 s | Tomó el proceso libre: tiempo normal |
| Segunda nueva | 17,29 s | Esperó a que terminara el hash cancelado |

La diferencia (7,36 s) coincide con lo que le faltaba al hash cancelado para terminar (~9,3 s menos los 2 s hasta el `DELETE`). Cancelar liberó al worker de la API pero no al proceso del pool. Es una deducción a partir de los tiempos: no se observó el consumo de CPU en `top`.

---

## 5. Conceptos del curso aplicados

- **Productor-consumidor (clase 11):** la API produce ids con `put_nowait` y el pool de workers los consume de una `asyncio.Queue` compartida. Es el mismo patrón de la clase 11, pero con corrutinas en lugar de threads: acá no hace falta lock porque el event loop no interrumpe entre `await`s.
- **Event loop y corrutinas (clases 17 y 18):** los workers son corrutinas que casi todo el tiempo están suspendidas en `await cola.get()`. El event loop (construido sobre multiplexing de I/O, `epoll`) las reanuda cuando hay algo que hacer. Por eso `time.sleep()` dentro de una corrutina sería un bug (frena el hilo del loop) y `asyncio.sleep()` no (cede el control).
- **HTTP y FastAPI (clase 19):** los endpoints son `async def`, validan con pydantic y responden `202`/`404`/`409`/`503` según el caso.
- **Asyncio en red (clases 20 y 21):** `descargar` lanza N corrutinas con `asyncio.gather`, lo que tarda aproximadamente lo que la más lenta; un `for` con `await` adentro tarda la suma (medición 4.1: 1,03 s contra 20,12 s). Cancelación y timeouts con `Task.cancel()` y `asyncio.wait_for`.
- **Executors (clases 21 y 22):** `run_in_executor` con `ProcessPoolExecutor` para sacar el trabajo CPU-bound del hilo del loop (medición 4.2).
- **Señales y procesos:** `SIGTERM` y `SIGINT` llegan a `uvicorn`, que dispara el apagado del `lifespan`. En Docker, que el servidor sea PID 1 es lo que permite recibir `SIGTERM` directo.

---

## 6. Limitaciones conocidas

- **Cancelar un `hashear` en ejecución no detiene el cálculo.** `ProcessPoolExecutor` no puede interrumpir una función que ya corre en un proceso hijo, así que el proceso sigue ocupado hasta terminar (sección 4.4). Alternativas: un `multiprocessing.Process` por tarea con `terminate()`, o que `_hash_iterado` revise un `multiprocessing.Event` cada cierto número de iteraciones.
- **El timeout incluye la espera en el pool de CPU** (ver "Timeouts").
- **`GET /tareas` no tiene paginación** y bloquea el event loop mientras serializa: ~205 a 235 ms con 10.000 tareas.
- **Cola y diccionario sin límite ni purga:** la memoria crece unos 1,1 KB por tarea, y no hay contrapresión (el `POST` siempre acepta). Con tareas largas, el backlog solo se ve consultando `/estadisticas`.
- **Cantidad de workers y tamaño del pool de CPU:** los workers se configuran con `N_WORKERS`; el pool de CPU es fijo (2 procesos).
- **Una tarea cancelada mientras estaba pendiente** sigue ocupando su lugar en la cola hasta que un worker la saca y la descarta.
- **El volcado es informativo:** al arrancar se reporta, pero no se reanudan las tareas. Las pendientes quedan `pendiente` y las interrumpidas por el apagado, `fallida`.
- **Mediciones:** corridas únicas o pocas repeticiones, cliente y servidor en la misma máquina, muestreo de CPU grueso y un solo dato para la plataforma en la medición 4.1.
- **Plataformas:** se desarrolló y probó en Linux y en Docker. No se probó fuera de contenedor en macOS ni en Windows.
- **Sin tests automáticos ni extensiones opcionales.**

---


