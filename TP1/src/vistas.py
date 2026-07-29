from __future__ import annotations


VISTAS = [
    {"id": "resumen", "teclas": ("1", "r"), "titulo": "Resumen", "intervalo_default": 2.0, "intervalo_minimo": 0.5},
    {"id": "memoria", "teclas": ("2", "m"), "titulo": "Memoria", "intervalo_default": 3.0, "intervalo_minimo": 1.0},
    {"id": "fds", "teclas": ("3", "f"), "titulo": "File Descriptors", "intervalo_default": 5.0, "intervalo_minimo": 2.0},
    {"id": "threads", "teclas": ("4", "t"), "titulo": "Threads", "intervalo_default": 2.0, "intervalo_minimo": 0.5},
    {"id": "senales", "teclas": ("5", "s"), "titulo": "Senales", "intervalo_default": 10.0, "intervalo_minimo": 5.0},
    {"id": "scheduling", "teclas": ("6", "p"), "titulo": "Scheduling", "intervalo_default": 10.0, "intervalo_minimo": 5.0},
    {"id": "sistema", "teclas": ("7", "g"), "titulo": "Sistema global", "intervalo_default": 2.0, "intervalo_minimo": 1.0},
]

VISTA_POR_ID = {v["id"]: v for v in VISTAS}

TECLA_A_VISTA: dict[str, str] = {}
for _v in VISTAS:
    for _k in _v["teclas"]:
        TECLA_A_VISTA[_k] = _v["id"]