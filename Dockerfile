# Dockerfile — KarpathyWiki Ingest Daemon
# Base: python:3.12-alpine (~80 MB en disco final)

FROM python:3.12-alpine

# Dependencias del sistema necesarias para watchdog/inotify
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el script del daemon
COPY ingest_daemon.py .

# El vault se monta desde el host en tiempo de ejecución (bind mount)
# No se copia aquí para no acoplar la imagen a un vault específico
VOLUME ["/vault"]

# Variables de entorno esperadas en runtime
# GEMINI_API_KEY — obligatoria
# VAULT_PATH     — opcional, por defecto /vault
ENV VAULT_PATH=/vault

ENTRYPOINT ["python", "ingest_daemon.py"]
CMD ["/vault"]
