FROM python:3.11-slim

# El monitor lee archivos de configuracion y escribe dumps con rutas
# relativas (config.json, dump_<timestamp>.json), asi que fijamos un
# WORKDIR y trabajamos siempre desde ahi.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El monitor necesita una TUI interactiva: se corre con
# `docker compose up` usando tty:true y stdin_open:true (ver
# docker-compose.yml), no hace falta nada especial aca para eso.
CMD ["python3", "-m", "src.main"]