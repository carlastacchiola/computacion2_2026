
# TP2: Plataforma de Tareas Distribuidas

**Computación II, Universidad de Mendoza, 2026**
**Alumna:** Carla Stacchiola

Servicio HTTP al que se le encargan trabajos, que los ejecuta de forma concurrente con un pool de workers asíncronos y permite consultar su estado, su resultado y cancelarlos.

> **Estado del trabajo (26/10/2026):** informe parcial. Lo que falta está marcado como _pendiente_ en cada sección.

| Parte | Estado |
|-------|--------|
| API HTTP (5 endpoints) | Hecho |
| Cola + pool de workers | Hecho |
| Tareas `esperar`, `descargar`, `hashear` | Hecho |
| Cancelación y timeouts | Hecho |
| Apagado ordenado + volcado a JSON | Pendiente |
| Docker (`Dockerfile`, `docker-compose.yml`) | Pendiente |
| Medición 1 (I/O secuencial vs concurrente) | Pendiente (hay datos preliminares) |
| Medición 2 (event loop bloqueado) | Hecha |
| Medición 3 (techo del pool) | Pendiente |

---

## 1. Descripción y uso

### Requisitos

- Python 3.11+ (desarrollado con 3.12 en Ubuntu)
- Dependencias: `fastapi`, `uvicorn`, `httpx`

### Ejecución (sin Docker, por ahora)

```bash
cd TP2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app
```

La API queda en `http://localhost:8000` y la documentación interactiva en `http://localhost:8000/docs`.

> La versión con `docker compose up --build` está pendiente.

### Endpoints

| Método | Ruta | Qué hace |
|--------|------|----------|
| `POST` | `/tareas` | Encola una tarea. Responde `202` con `id` y estado, sin esperar a que termine |
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
  └──────────────────┘                        │ ProcessPoolExecutor  │
                                              │ (2 procesos, hashear)│
                                              └──────────────────────┘
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
│   ├── main.py      # FastAPI, endpoints, lifespan
│   ├── modelos.py   # Estado (Enum), NuevaTarea (pydantic), Tarea (dataclass)
│   ├── workers.py   # Plataforma: cola, pool de workers, cancelación
│   └── tareas.py    # esperar, descargar, hashear y el despachador EJECUTORES
├── requirements.txt
└── README.md
```

---

## 3. Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

`queue.Queue` está pensada para threads: `get()` **bloquea el hilo** hasta que haya un elemento. Si un worker-corrutina la usara, bloquearía el hilo del event loop entero y se congelaría toda la API. `asyncio.Queue.get()` es una corrutina: mientras no hay nada, el worker se suspende en el `await` y el loop sigue atendiendo a los demás. Además, `asyncio.Queue` no necesita locks internos porque todo corre en un solo hilo.

La cola guarda **ids** y no objetos `Tarea`, así el diccionario `tareas` es la única fuente de verdad del estado.

### ¿Cómo evito que una tarea CPU-bound congele la API?

Un `await` solo cede el control cuando la corrutina *espera* algo. Un bucle de millones de hashes no espera nada: nunca cede, y como el event loop vive en ese mismo hilo, no puede atender ni un `GET`. Por eso `hashear` delega el cálculo con `loop.run_in_executor` a un `ProcessPoolExecutor` (2 procesos). Se eligen **procesos y no hilos** porque con hilos el cálculo seguiría compitiendo por el GIL con el event loop; un proceso aparte tiene su propio intérprete y corre en otro núcleo. La corrutina de la tarea queda suspendida en el `await` y el loop sigue libre. Esto se mide en la sección 4.2.

### ¿Por qué los workers no necesitan un `Lock`?

Porque el event loop es cooperativo y corre en un solo hilo: una corrutina solo puede ser interrumpida en un `await`. Instrucciones como `tarea.estado = Estado.EJECUTANDO` no tienen ningún `await` en el medio, así que nadie puede observar un estado a medias. Un `Lock` haría falta si hubiera varios hilos modificando los mismos datos.

### ¿Cómo implementé la cancelación?

- El worker no ejecuta la función directamente: crea una `asyncio.Task` y la guarda en `tarea._ejecucion`. El `DELETE` tiene así a quién llamarle `.cancel()`.
- **Tarea pendiente:** se marca `cancelada`. El id sigue en la cola, y cuando un worker lo saca ve que el estado ya no es `pendiente` y lo saltea.
- **Tarea en ejecución:** `cancelar()` marca `cancelada` y llama a `.cancel()` sobre la task. La función recibe un `CancelledError` en su `await` actual.
- **Distinguir dos cancelaciones:** el worker también puede recibir un `CancelledError` si lo cancelan a él (apagado del servicio). Como `cancelar()` marca el estado *antes* de cancelar, el worker sabe cuál es cuál: si el estado es `cancelada`, fue un `DELETE` y sigue vivo; si no, relanza la excepción para que el worker termine.
- **Recursos:** en `descargar`, el `async with httpx.AsyncClient` cierra las conexiones al salir y `asyncio.gather` cancela a las descargas hermanas, así que no quedan corrutinas huérfanas. Verificado: tras cancelar una descarga a mitad, `/estadisticas` muestra 0 workers ocupados y 0 tareas en ejecución.
- **Excepción conocida:** `hashear` en otro proceso no se puede interrumpir (ver sección 6).

### Timeouts

`asyncio.wait_for(task, timeout)` cancela la task interna, espera a que termine de cancelarse y recién ahí levanta `TimeoutError`. El worker la atrapa y marca la tarea como `fallida` con el motivo en `error`. Medido: una tarea de 10 s con `timeout=2` falló a los 2,00 s.

Detalle: el cronómetro del timeout (y `inicio`) arranca cuando el worker toma la tarea, no cuando el proceso del pool empieza a calcular. Una tarea CPU-bound que espera lugar en el pool consume timeout sin haber calculado.

### ¿Qué pasa si un worker lanza una excepción no capturada?

El bucle del worker tiene un `except Exception` que marca la tarea como `fallida`, guarda `"TipoDeError: mensaje"` en `error`, loguea el traceback y **el worker sigue vivo** para la próxima tarea. Se captura `Exception` y no `BaseException` a propósito: `CancelledError` hereda de `BaseException` desde Python 3.8, y debe propagarse si cancelan al worker. En `descargar`, además, cada URL captura su propio `httpx.HTTPError`, así una URL caída no tumba a las demás.

### ¿Por qué `httpx` y no `requests`?

`requests` es síncrona: cada llamada bloquearía el event loop. `httpx` ofrece `AsyncClient` con una API casi idéntica a la de `requests`, lo que facilita el uso, y se integra directo con `asyncio`.

### Otras decisiones

- **Despachador por diccionario** (`EJECUTORES`): el worker no sabe qué hace cada tipo; agregar un tipo es agregar una línea.
- **`202 Accepted`** en el `POST`: es el código correcto para "recibí el pedido, lo proceso aparte".
- **Estado dentro de la clase `Plataforma`** en lugar de globales sueltas, para agrupar cola, workers y diccionario.
- **`lifespan` de FastAPI** para arrancar y detener los workers dentro del event loop de uvicorn.

---

## 4. Mediciones

Máquina: Lenovo V15 G2 ITL, Ubuntu (Python 3.12), servidor y cliente en la misma máquina.

### 4.1 Concurrencia I/O (preliminar, **pendiente la medición final**)

Datos preliminares con 5 descargas concurrentes a `https://httpbin.org/delay/2` (tarea `descargar`, `fin - inicio`):

| Corrida | Total | Descarga más lenta | Suma de las 5 |
|---------|-------|--------------------|---------------|
| 1 | 6,20 s | 6,15 s | 19,7 s |
| 2 | 2,81 s | 2,79 s | 13,9 s |

El total coincide con la descarga más lenta y no con la suma, que es lo esperado con `asyncio.gather`. La diferencia entre corridas se debe a `httpbin.org`, un servicio público con latencia variable.

**Pendiente:** 20 descargas realmente secuenciales contra 20 concurrentes contra un servidor local con demora fija, con su speedup. La "suma" de la tabla anterior es la suma de los tiempos individuales, no una corrida secuencial real, así que no sirve como speedup.

### 4.2 El event loop bloqueado

Tarea `hashear` con 25.000.000 de iteraciones de SHA-256 (duración medida: **9,31 s**). Se midió la latencia de `GET /tareas` mientras la tarea estaba en `ejecutando`.

| Modo | Latencia de `GET /tareas` durante el hash |
|------|-------------------------------------------|
| Con `run_in_executor` | **1,0 a 2,0 ms** (10 muestras, todas con la tarea ejecutando) |
| Sin executor (`"bloquear": true`) | **8,50 s** |

Es una diferencia de unas 6.000 veces con el mismo cálculo. El hash no tarda menos con executor: tarda lo mismo. Lo que cambia es **quién espera**. Con executor, solo espera la corrutina de esa tarea; sin él, el cálculo corre en el hilo del event loop y, al no haber ningún `await`, espera todo el servidor. Los 8,50 s son los 9,31 s del hash menos el medio segundo de `sleep` previo al `GET` y lo que tardó el worker en arrancar.

### 4.3 Techo del pool: **pendiente**

_(Subir la cantidad de tareas concurrentes hasta que los tiempos se degraden, indicar dónde está el límite y por qué.)_

### 4.4 Medición adicional: costo de cancelar un `hashear`

Pool de CPU de 2 procesos, hashes de 25M iteraciones (~9,3 s). Se lanzó un hash, se canceló con `DELETE` a los 2 s y de inmediato se mandaron dos hashes nuevos:

| Tarea | Duración | Interpretación |
|-------|----------|----------------|
| Primera nueva | 9,93 s | Tomó el proceso libre: tiempo normal |
| Segunda nueva | 17,29 s | Esperó a que terminara el hash cancelado |

La diferencia (7,36 s) coincide con lo que le faltaba al hash cancelado para terminar (~9,3 s menos los 2 s hasta el `DELETE`). Cancelar liberó al worker de la API pero no al proceso del pool. Es indirecto: se dedujo de los tiempos, no se observó el consumo de CPU en `top`.

---

## 5. Conceptos del curso aplicados

- **Productor-consumidor (clase 11):** la API produce ids con `put_nowait` y el pool de workers los consume de una `asyncio.Queue` compartida. Es el mismo patrón de la clase 11, pero con corrutinas en lugar de threads: acá no hace falta lock porque el event loop no interrumpe entre `await`s.
- **Event loop y corrutinas (clases 17 y 18):** los workers son corrutinas que casi todo el tiempo están suspendidas en `await cola.get()`. El event loop (construido sobre multiplexing de I/O, `epoll`) las reanuda cuando hay algo que hacer. Por eso `time.sleep()` dentro de una corrutina sería un bug (frena el hilo del loop) y `asyncio.sleep()` no (cede el control).
- **HTTP y FastAPI (clase 19):** los endpoints son `async def`, validan con pydantic y responden `202`/`404`/`409` según el caso.
- **Asyncio en red (clases 20 y 21):** `descargar` lanza N corrutinas con `asyncio.gather`, lo que tarda aproximadamente lo que la más lenta; un `for` con `await` adentro tardaría la suma. Cancelación y timeouts con `Task.cancel()` y `asyncio.wait_for`.
- **Executors (clases 21 y 22):** `run_in_executor` con `ProcessPoolExecutor` para sacar el trabajo CPU-bound del hilo del loop.

---

## 6. Limitaciones conocidas

- **Cancelar un `hashear` en ejecución no detiene el cálculo.** `ProcessPoolExecutor` no puede interrumpir una función que ya corre en un proceso hijo, así que el proceso sigue ocupado hasta terminar (sección 4.4). Alternativas: un `multiprocessing.Process` por tarea con `terminate()`, o que `_hash_iterado` revise un `multiprocessing.Event` cada cierto número de iteraciones.
- **El timeout incluye la espera en el pool de CPU** (ver "Timeouts").
- **Cola y diccionario sin límite:** con muchas tareas de golpe, la memoria crece sin tope y el diccionario `tareas` nunca se purga.
- **Tamaño del pool de CPU fijo** (2 procesos), no configurable por variable de entorno todavía.
- **Una tarea cancelada mientras estaba pendiente** sigue ocupando su lugar en la cola hasta que un worker la saca y la descarta.
- **Apagado ordenado y volcado a JSON: no implementados todavía.**
- **Sin Docker todavía.**

---

