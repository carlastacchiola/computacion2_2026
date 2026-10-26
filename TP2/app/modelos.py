import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class Estado(str, Enum):
    PENDIENTE = "pendiente"
    EJECUTANDO = "ejecutando"
    COMPLETADA = "completada"
    FALLIDA = "fallida"
    CANCELADA = "cancelada"


class NuevaTarea(BaseModel):
    """Lo que el cliente manda en el POST. Pydantic valida por nosotros."""
    tipo: Literal["esperar", "descargar", "hashear"]
    parametros: dict[str, Any] = {}
    timeout: float = 30.0  # segundos; lo usamos en el paso 2


@dataclass
class Tarea:
    """Lo que guardamos internamente."""
    tipo: str
    parametros: dict[str, Any]
    timeout: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    estado: Estado = Estado.PENDIENTE
    resultado: Any = None
    error: str | None = None
    creada: float = field(default_factory=time.time)
    inicio: float | None = None
    fin: float | None = None
    # La asyncio.Task en ejecución (la usaremos para cancelar).
    # No es serializable, por eso queda afuera de a_dict().
    _ejecucion: asyncio.Task | None = field(default=None, repr=False)

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "parametros": self.parametros,
            "estado": self.estado.value,
            "resultado": self.resultado,
            "error": self.error,
            "creada": self.creada,
            "inicio": self.inicio,
            "fin": self.fin,
        }