# TP1 — Monitor de Procesos y Threads

**Computación II — Universidad de Mendoza — 2026**

Monitor de sistema en tiempo real, estilo `htop`, que lee `/proc` directamente
(sin `psutil` ni herramientas equivalentes) y muestra la anatomía interna de
cada proceso: memoria, file descriptors, threads, señales y scheduling. Está
implementado como un sistema **multiproceso**: un recolector, siete
analizadores independientes, un agregador y una interfaz de texto (TUI)
interactiva se comunican entre sí con las primitivas de `multiprocessing`.

---

## 1. Descripción general

El monitor arranca con:

```bash
python3 -m src.main
```

o, dentro de Docker:

```bash
docker compose run --rm --build monitor
```

y muestra una TUI a pantalla completa con:

- Una **lista de procesos** siempre visible arriba (PID, usuario, estado,
  CPU%, RSS, nombre), navegable con las flechas.
- Un **panel de detalle** abajo que cambia según la vista activa.
- **7 vistas** alternables con `1`-`7` (o `r m f t s p g`): Resumen, Memoria,
  File Descriptors, Threads, Señales, Scheduling y Sistema global.

### Keybindings

| Tecla | Acción |
|---|---|
| `1`-`7` / `r m f t s p g` | Cambiar de vista |
| `↑` `↓` | Navegar la lista de procesos |
| `Enter` | Fijar (pin) / soltar el proceso seleccionado |
| `/` | Filtrar por nombre de comando |
| `u` | Filtrar por usuario |
| `c` | Cambiar orden: CPU% → RSS → PID → CPU%... |
| `+` / `-` | Subir/bajar el intervalo de refresco de la vista activa |
| `h` / `?` | Mostrar/ocultar la ayuda |
| `q` | Salir |


---

## 2. Diagrama de arquitectura

```
                         ┌────────────────────────────────────┐
                         │        PROCESO PRINCIPAL            │
                         │           (main.py)                 │
                         │  · self-pipe: SIGINT/TERM/HUP/       │
                         │    USR1/USR2 (ver señales.py)        │
                         │  · crea Manager, Queue, Values        │
                         │  · escribe monitor.pid                │
                         │  · arranca y espera a los hijos       │
                         └──────────────────┬────────────────────┘
                                            │ multiprocessing.Process
        ┌──────────────┬───────────────────┼───────────────────┬──────────────┐
        │              │                   │                   │              │
  ┌─────▼─────┐  ┌──────▼──────┐    ┌───────▼────────┐   ┌──────▼──────┐ ┌─────▼──────┐
  │RECOLECTOR │  │  7 ANALIZA- │    │   AGREGADOR    │   │   DISPLAY    │ │  (Manager  │
  │lista /proc│  │  DORES      │    │ Queue -> dict  │   │   (TUI)      │ │  interno:  │
  │cada 1s    │  │ (procesos   │    │  compartido    │   │ Live + hilo  │ │  server +  │
  └─────┬─────┘  │ independien-│    └───────▲────────┘   │ de teclado   │ │  resource_ │
        │        │ tes, c/u su │            │            └──────▲───────┘ │  tracker)  │
        │ escribe│ intervalo)  │  output_   │                   │ lee     └────────────┘
        ▼        └──────┬──────┘  queue.put()                   │
 shared_pids            │ lee            │                       │
 (Manager.list) ◄───────┘                └──────► snapshot (Manager.dict)
        ▲                                          interval_values (7x Value)
        │                                          verbose_value (Value)
        └── todos los analizadores leen la MISMA lista de PIDs por ciclo
```

**Flujo de datos:** recolector → `shared_pids` (memoria compartida) →
7 analizadores (en paralelo, cada uno a su ritmo) → `output_queue` →
agregador → `snapshot` (memoria compartida) → display (lee `snapshot`,
escribe en `interval_values` con `+`/`-`, y en `verbose_value` — indirectamente,
a través de `main.py` — con `SIGUSR2`).

---

## 3. Decisiones de diseño

### ¿Por qué `Manager` para el snapshot y la lista de PIDs, y `Value` para los intervalos?

Son necesidades distintas:

- **`snapshot` y `shared_pids` (Manager.dict / Manager.list):** estructuras
  compuestas (diccionarios anidados, listas de PIDs) que un proceso escribe y
  *varios* leen. `Manager` corre un proceso servidor propio que serializa el
  acceso y devuelve proxies, así que soporta tipos arbitrarios (listas,
  diccionarios, strings) sin que yo tenga que definir su tamaño de antemano.
- **`interval_values` y `verbose_value` (`multiprocessing.Value`):** un único
  número (`float` o `byte`) que se lee con mucha frecuencia (cada analizador
  lo consulta en cada ciclo) y se escribe rara vez (solo cuando el usuario
  aprieta `+`/`-`, o llega `SIGUSR2`). `Value` vive en memoria compartida real
  (no pasa por un proceso servidor intermediario), así que leerlo es
  prácticamente gratis comparado con una llamada RPC a un `Manager`. Para un
  solo escalar que cambia poco y se lee mucho, es la herramienta más liviana.

### ¿Por qué `Queue` para los mensajes de los analizadores, y no `Manager` directo?

Los 7 analizadores podrían, en teoría, escribir directo al `snapshot`
compartido. No lo hice así porque eso significaría que 7 procesos escriben
concurrentemente sobre el mismo diccionario compartido, y aunque el `Manager`
serializa cada llamada individual, entrelazar 7 escritores sin un punto único
de coordinación es más difícil de razonar y de debuggear. En cambio, cada
analizador solo *produce mensajes* (`output_queue.put(...)`) y un único
proceso — el agregador — es el que consume la cola y escribe al snapshot. Hay
un solo escritor del `snapshot`, lo cual simplifica bastante el razonamiento
sobre concurrencia.

### El recolector centralizado (evitar 7 recorridas de `/proc`)

En una versión temprana, cada analizador llamaba a su propia versión de
"listar PIDs". Eso significa 7 recorridas independientes de `/proc` por
ciclo, y peor: si un proceso muere entre que el analizador A lo lista y el
analizador B lo lista, cada uno termina viendo un universo de PIDs distinto
en el mismo instante. Ahora hay un único recolector que llama `list_pids()` y
publica el resultado en `shared_pids`; los 7 analizadores parten de la misma
foto de PIDs en cada ciclo.

### Race conditions: dónde podrían pasar y cómo se evitan

- **Reemplazo de `shared_pids`:** el recolector hace `shared_pids[:] = pids`,
  que se traduce en una única llamada RPC al proceso servidor del `Manager`.
  Ese servidor procesa las llamadas de a una, así que un analizador que hace
  `list(shared_pids)` en el medio de esa escritura ve la lista vieja completa
  o la nueva completa, nunca una mezcla a mitad de camino. No hace falta un
  `Lock` explícito porque la atomicidad la da el propio diseño del `Manager`
  (una llamada = una operación serializada).
- **Lectura de `interval_values` mientras `display.py` lo escribe:** un
  `multiprocessing.Value('d', ...)` respalda un `double` en memoria
  compartida; leer/escribir un float de 8 bytes alineado es atómico a nivel
  de hardware en la práctica (no hay tearing visible), así que no protejo
  esa lectura con lock tampoco. Si en cambio tuviera que hacer un
  incremento no-atómico tipo "leer, sumar, escribir" desde *dos* procesos
  distintos al mismo tiempo, ahí sí necesitaría el `Lock` que trae
  `Value` por default — pero acá solo hay un escritor (`display.py`) y
  varios lectores, así que no aplica.

### El self-pipe para señales (SIGINT/TERM/HUP/USR1/USR2)

Ver `src/señales.py`. Un handler de señal puede interrumpir el programa en
cualquier punto, incluso a mitad de una operación no reentrante, y la lista
de funciones seguras para llamar desde adentro de un handler
(`signal-safety(7)`) es muy corta. Por eso mis handlers no hacen ningún
trabajo real: solo prenden un booleano (`self._shutdown_requested = True`,
etc.). El trabajo de verdad (releer `config.json`, volcar el snapshot a
disco) lo hace el loop principal, que corre como código Python normal fuera
de un handler. Uso `signal.set_wakeup_fd()` en vez de escribir yo misma al
pipe desde el handler: es la forma que ofrece la stdlib para este patrón, y
la escritura del byte la hace el propio intérprete a nivel C.

Los procesos hijos (recolector, agregador, analizadores, display) resetean
esta disposición apenas arrancan (`ignorar_senales_de_control()`): ignoran
SIGINT (el shutdown ordenado lo dispara el proceso principal vía
`stop_event`, no cada hijo por su cuenta) y vuelven el resto a su
comportamiento por defecto, para que solo el proceso principal reaccione a
`SIGHUP`/`SIGUSR1`/`SIGUSR2`.

### Por qué el intervalo de cada vista es un `Value` y no un número fijo

El enunciado pide que `+`/`-` ajusten el intervalo de la vista activa **en
caliente**, sin reiniciar nada. Un analizador que recibiera un `float` fijo
como argumento nunca podría enterarse de un cambio posterior — Python pasa
los `float` por valor. Por eso cada analizador recibe un
`multiprocessing.Value('d', ...)` y lee `interval_value.value` en cada vuelta
de su loop: es memoria compartida real entre el proceso de display (que
escribe) y el analizador (que lee), no una copia.

### Intervalos por defecto elegidos

Las vistas que cambian rápido en un sistema real (Resumen, Threads, Sistema)
refrescan cada 2 segundos; Memoria cada 3 (los datos de `/status` cambian más
lento); FDs cada 5 (recorrer `/proc/<pid>/fd/` de muchos procesos es más
caro, listar symlinks tiene su costo); Señales y Scheduling cada 10 (son los
datos que menos cambian segundo a segundo). Los mínimos permitidos con `-`
son la mitad del default aproximadamente, para no dejar que alguien fije un
intervalo tan chico que sature el sistema leyendo `/proc` en loop.

---

## 4. Conceptos del curso aplicados

- **Clase 3 (Procesos, `/proc`, memoria virtual):** todo `src/procfs.py` — el
  parseo de `/proc/<pid>/stat` y `/status` campo por campo (sin herramientas
  que abstraigan el filesystem), y el agrupamiento de `VmSize`/`VmRSS`/etc.
  en la vista Memoria.
- **Clase 4 (fork, exec, wait; zombies, COW):** en la vista Sistema, detecto
  zombies mirando si el campo `State` de `/proc/<pid>/stat` es `Z` — un
  zombie es un proceso terminado cuyo padre todavía no llamó a `wait()`, así
  que sigue teniendo una entrada en `/proc` aunque ya no esté "vivo" en
  sentido estricto.
- **Clase 5 (Pipes, FDs, IPC básico):** la vista File Descriptors recorre
  `/proc/<pid>/fd/` con `os.readlink` para ver a qué apunta cada FD. Y el
  self-pipe de `señales.py` usa `os.pipe()` — la misma primitiva, aplicada
  para comunicar el "mundo async" de los signal handlers con el loop
  principal dentro del mismo proceso.
- **Clase 6 (Señales, handlers, async-signal-safety, self-pipe):**
  `señales.py` completo — `signal.set_wakeup_fd`, handlers que solo marcan
  flags, y por qué eso es necesario (ver sección de diseño más arriba).
- **Clase 7 (mmap, memoria compartida):** `Manager.dict()`/`Manager.list()`
  para el snapshot y la lista de PIDs.
- **Clase 8-9 (Multiprocessing, `Process`, `Queue`, `Manager`, `Value`):** la
  arquitectura entera — recolector, 7 analizadores, agregador y display como
  procesos independientes, `Queue` para los mensajes de los analizadores al
  agregador, `Value` para los intervalos ajustables.
- **Clase 10 (Threading, GIL, threads como LWPs):** la vista Threads lee
  `/proc/<pid>/task/<tid>/` — el "proceso" y sus "threads" son, para el
  kernel, todos entradas de tareas (`task_struct`) que comparten espacio de
  memoria pero tienen su propio TID. Y el hilo de lectura de teclado dentro
  de `display.py` es la única excepción permitida a la arquitectura
  multiproceso: usa un `threading.Thread`, no un `Process`, porque necesita
  bloquear esperando input sin frenar el resto del programa, y no vale la
  pena la sobrecarga de un proceso completo solo para eso.

---

## 5. Limitaciones conocidas

- **Todos los procesos hijos aparecen con el mismo comando en `ps aux`**
  (`python3 -m src.main`, heredado del `fork` de `multiprocessing`, ya que no
  uso ningún mecanismo para cambiar el nombre visible del proceso). Por eso
  el proceso principal escribe su PID en `monitor.pid` al arrancar — es la
  forma no ambigua de mandarle una señal.
- **La lectura de teclado y el self-pipe de señales no tienen tests
  automatizados** (`tests/`): ambos necesitan una terminal/proceso real para
  tener sentido, así que los verifiqué a mano, mandando señales con `kill` y
  simulando una terminal real con `pty.fork()` durante el desarrollo (quedó
  documentado en el proceso, no como test de CI).
- **El Top 3 por CPU/RSS de la vista Sistema se calcula a partir del último
  muestreo de la vista Resumen**, que corre en un proceso separado con su
  propio intervalo — puede estar hasta ~2 segundos desactualizado respecto
  del resto de las métricas globales de esa misma vista.
- **`docker compose up` (sin `-d`) no conecta el teclado al contenedor**,
  aunque `tty`/`stdin_open` estén en `true` — es una limitación conocida de
  Compose (no de `docker run` directo). El monitor arranca y se ve, pero no
  responde a ninguna tecla. Lo verifiqué en un entorno real: `docker compose
  run --rm --build monitor` (o `up -d` + `docker attach`) sí conecta la
  terminal correctamente. Documentado con el detalle completo en la sección
  6.
- **`resolve_username` cachea el mapeo UID→usuario para siempre** (nunca
  invalida la caché). En un sistema real donde se crean/borran usuarios en
  caliente esto podría mostrar un nombre viejo, pero es un caso de uso muy
  poco común para un monitor de este tipo.


---

## 6. Cómo correr y testear

### Sin Docker

```bash
cd TP1
pip install -r requirements.txt
python3 -m src.main
```

### Con Docker

```bash
cd TP1
docker compose up --build
```

Este es el comando que pide la consigna, y buildea y arranca el contenedor
correctamente. `docker compose up` (sin `-d`) muestra la salida del
contenedor en tu terminal, pero **no conecta tu teclado al `stdin` del
contenedor** — es una limitación conocida de Compose, no algo que dependa de
`tty`/`stdin_open` (esos sí son necesarios, pero no alcanzan). El monitor
arranca y se ve, pero ninguna tecla responde.

Para tener la TUI completamente interactiva (que es lo que en la práctica
vas a querer para usar el monitor), dos alternativas, verificadas ambas:

```bash
# Opcion A (recomendada): docker compose run se comporta como
# "docker run -it", conecta stdin/stdout/stderr de la terminal.
docker compose run --rm --build monitor

# Opcion B: levantar en background y adjuntarse aparte.
docker compose up -d --build
docker attach tp1-monitor
# para salir sin matar el contenedor: Ctrl+P, despues Ctrl+Q
```


### Probar las señales manualmente

```bash
# con el monitor corriendo en otra terminal:
kill -HUP  $(cat monitor.pid)   # deberías ver un mensaje cyan en el monitor
kill -USR1 $(cat monitor.pid)   # mensaje verde + aparece dump_<timestamp>.json
kill -USR2 $(cat monitor.pid)   # mensaje magenta, header pasa a verbose=ON
kill -TERM $(cat monitor.pid)
```
---

## 7. Decisiones sobre la TUI

Usé `rich` (`Live` en modo pantalla completa) en vez de `curses` porque ya
venía trabajando con `rich.table.Table` para el prototipo inicial y su API de
alto nivel simplifica mucho el layout (tablas, estilos, paneles) comparado
con manejar coordenadas de celda a mano como pide `curses`. La contrapartida
es que `rich` no me da un manejo de teclado nativo no bloqueante, así que lo
armé por separado con `termios`/`tty`/`select` en un hilo — con un detalle
importante: `multiprocessing` cierra `sys.stdin` en todo proceso hijo (lo
reemplaza por `/dev/null`), así que la lectura de teclado no puede usar
`sys.stdin` dentro del proceso de display — tiene que abrir `/dev/tty`
directamente, que es la terminal *controladora* del proceso y sí sobrevive
al fork.

## 8. Capturas de pantalla
Las capturas de pantalla se encuentran en la carpeta `capturas/`.


---

