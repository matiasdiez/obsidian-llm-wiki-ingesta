# Dockerfile — KarpathyWiki Ingest Daemon
# Base: python:3.12-slim (build multi-stage)
#
# Antes usábamos python:3.12-alpine. Alpine usa musl en vez de glibc, y varias
# dependencias con extensiones nativas (antes: chromadb/onnxruntime/hnswlib)
# no publican wheels precompilados para musl, así que pip las compilaba desde
# código fuente en cada build — eso agotaba el espacio en disco.
# slim (Debian) sí tiene wheels manylinux precompilados: pip solo descarga
# binarios, no compila nada.

# ---- Etapa 1: build ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Etapa 2: runtime ----
FROM python:3.12-slim
WORKDIR /app

# Copiar solo los paquetes ya instalados de la etapa de build.
# El toolchain de compilación (si hizo falta) nunca llega a esta imagen.
COPY --from=builder /install /usr/local

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
