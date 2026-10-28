FROM python:3.12-slim

WORKDIR /app

# Primero las dependencias: así Docker cachea esta capa si el código cambia
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Acá se guardan los volcados de estado (se monta como volumen)
ENV DIR_ESTADO=/data
RUN mkdir -p /data

EXPOSE 8000

# Forma "exec" (lista JSON): uvicorn queda como PID 1 y recibe SIGTERM directo.
# Con la forma "shell" lo recibiría un /bin/sh intermedio y el apagado no correría.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]