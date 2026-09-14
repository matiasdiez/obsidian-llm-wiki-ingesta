# KarpathyWiki — Daemon de Ingesta Automática para Obsidian

[English](README.md) | [Español](READMEes.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker: Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Built with: Gemini](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2.svg)](https://deepmind.google/technologies/gemini/)
[![Companion: Obsidian](https://img.shields.io/badge/Obsidian-Plugin%20Companion-7C3AED.svg)](https://obsidian.md/)

Daemon en Python que automatiza la generación de notas wiki en Obsidian usando el plugin [obsidian-llm-wiki](https://github.com/GD4AI/obsidian-llm-wiki). Detecta nuevas notas o modificaciones en tiempo real y genera automáticamente entradas estructuradas en `wiki/concepts`, `wiki/entities` y `wiki/sources`, sin intervención manual desde la interfaz de Obsidian.

---

## Cómo funciona

```
Tu nota en Obsidian
       │
       ▼ (watchdog detecta creación/modificación)
  Debounce 20s (espera que termines de escribir)
       │
       ▼ (hash SHA-256 — ¿cambió el archivo?)
  Sin cambios & estado OK → ignorado (0 tokens, 0 costo)
  Con cambios o pendiente → llama a la API de Gemini
       │
       ▼
  wiki/sources/   ← resumen de la nota
  wiki/concepts/  ← conceptos abstractos/técnicos extraídos
  wiki/entities/  ← personas, autores u organizaciones mencionadas
```

**Lee la configuración** del plugin desde `.obsidian/plugins/karpathywiki/data.json` (carpetas monitoreadas, modelo, idioma). Si no encuentra el archivo, puede definirse en `.env` o monitorear todo el vault.

**Evita reprocesar:** guarda un hash SHA-256 de cada nota procesada en `.obsidian/plugins/karpathywiki/ingestion_state.db`. Si la nota no cambió y su estado anterior fue exitoso, no hace ninguna llamada a la API.

---

## Estructura del proyecto

```
obsidian-llm-wiki-ingesta/
├── ingest_daemon.py       # Script principal del daemon
├── Dockerfile             # Imagen Python 3.12 Alpine (~80MB)
├── docker-compose.yml     # Gestión simplificada del contenedor
├── requirements.txt       # Dependencias Python
├── .env.example           # Plantilla de variables de entorno
└── .env                   # Configuración local (NO subir a git)
```

---

## Configuración (`.env`)

```ini
GEMINI_API_KEY=tu_api_key_de_google_ai_studio
VAULT_PATH=/ruta/absoluta/a/tu/vault/de/obsidian
REQUEST_INTERVAL=120
# WATCHED_FOLDERS=Notes,Journal,Articles
```

| Variable | Requerido | Valor recomendado / Descripción |
|---|:---:|---|
| `GEMINI_API_KEY` | **Sí** | Clave de API de Gemini desde [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `VAULT_PATH` | **Sí** | Ruta absoluta al vault de Obsidian en el host. |
| `REQUEST_INTERVAL` | No | Segundos entre llamadas a la API: `120` (Free tier) · `6` (Paid tier). |
| `WATCHED_FOLDERS` | No | Lista de carpetas a monitorear separadas por coma. Si se omite, lee `watchedFolders` del plugin en `data.json`, o monitorea todo el vault. |

> ⚠️ El `.env` contiene tu API key y rutas locales. Está en `.gitignore` para no subirse a git. Usa `.env.example` como plantilla.

---

## Encender el servicio

```bash
cd ~/obsidian-llm-wiki-ingesta

docker compose up -d
```

La primera vez (o tras cambiar el código) reconstruye la imagen antes:

```bash
docker compose build && docker compose up -d
```

---

## Apagar el servicio

```bash
# Detener (el contenedor queda listo para volver a iniciar)
docker compose stop

# Detener y eliminar el contenedor (la imagen y el .env se conservan)
docker compose down
```

> `docker compose stop` solo detiene **este** servicio, no afecta a ningún otro contenedor Docker que tengas corriendo.

---

## Ver qué está haciendo

```bash
# Logs en tiempo real desde Docker
docker compose logs -f

# Log físico generado dentro del vault
tail -f $VAULT_PATH/karpathy_ingest.log
```

Líneas típicas en el log:

```
🚀 KarpathyWiki Ingest Daemon started
🔍 Running initial vault scan…
📝 Processing note: 02 Notas permanentes/Mi Nota.md
⏳ Rate limiter: waiting 118.3s before next API call…
  ✅ Generated 4 wiki file(s) from: 02 Notas permanentes/Mi Nota.md
⏭  No change detected (hash match). Skipping.
```

---

## Reiniciar tras cambiar la configuración

Si modificas `.env` (por ejemplo, cambiando `REQUEST_INTERVAL`):

```bash
docker compose down && docker compose up -d
```

---

## Inicio automático con Ubuntu

El campo `restart: unless-stopped` del `docker-compose.yml` hace que el contenedor
se reinicie automáticamente cuando Ubuntu arranca, siempre que Docker esté habilitado:

```bash
sudo systemctl is-enabled docker   # debe decir: enabled
```

Si no está habilitado:
```bash
sudo systemctl enable docker
```

---

## Límites y cuotas de la API

| Plan | Requests/día | `REQUEST_INTERVAL` sugerido |
|---|---|---|
| Free tier | 500 / día | 120s (~30/hora) |
| Paid tier | Sin límite diario | 6s (~10/minuto) |

Cuando se agota la cuota diaria el log mostrará:
```
Quota exceeded … GenerateRequestsPerDayPerProjectPerModel-FreeTier  limit: 500
```
La cuota se resetea automáticamente a medianoche (hora del Pacífico). Detén el servicio hasta el día siguiente con `docker compose stop`.

El daemon lee el tiempo de espera sugerido directamente de la respuesta de error de Gemini y lo respeta automáticamente.

---

## Carpetas monitoreadas por defecto

Si no existe `data.json` del plugin, el daemon monitorea estas carpetas:

- `00 Inbox/`
- `01 Notas efímeras/`
- `02 Notas permanentes/`
- `03 Revisión bibliográfica/`
- `04 Bibliografía/`
- `Clippings/`

Siempre **ignora**: `wiki/`, `.obsidian/`, `.git/`, `.trash/`.

Para usar tus propias carpetas, configúralas en el plugin de Obsidian (Settings → KarpathyWiki → Watched Folders). El daemon las leerá desde `data.json` al reiniciar.

---

## Primera ejecución: notas ya procesadas por el plugin

El daemon tiene su propia base de datos de estado (SQLite), independiente del registro interno del plugin. En la primera ejecución tiene dos comportamientos posibles:

- **Con escaneo inicial (por defecto):** intentará procesar todas las notas de las carpetas monitoreadas, incluyendo las que el plugin ya procesó. Útil para homogeneizar o actualizar la wiki.
- **Sin escaneo inicial:** solo procesa notas nuevas o modificadas a partir de ese momento. Útil si el plugin ya procesó todo y solo quieres monitoreo continuo:

```bash
# Agregar --no-initial-scan al comando en docker-compose.yml:
command: /vault --request-interval ${REQUEST_INTERVAL:-120} --no-initial-scan
```

---

## Seguridad

- El daemon solo **lee** notas de las carpetas monitoreadas.
- Solo **escribe** en `wiki/sources/`, `wiki/concepts/`, `wiki/entities/`, el log y la base de datos SQLite.
- **Nunca borra** ningún archivo del vault.
- Si un archivo wiki ya existe con el mismo nombre, lo sobreescribe con contenido actualizado.

---

## Referencia de comandos

| Acción | Comando |
|---|---|
| Iniciar | `docker compose up -d` |
| Detener | `docker compose stop` |
| Reiniciar | `docker compose restart` |
| Ver logs | `docker compose logs -f` |
| Reconstruir imagen | `docker compose build` |
| Eliminar contenedor | `docker compose down` |
| Estado del contenedor | `docker ps \| grep karpathy` |

---

## Arquitectura del Ecosistema y Capas del Sistema

Este servicio forma parte de una arquitectura desacoplada de 3 niveles diseñada para permitir la generación automática de la base de conocimiento sin sobrecargar la interfaz interactiva de Obsidian ni depender de mantener la aplicación abierta.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. BÓVEDA OBSIDIAN & PLUGIN OFICIAL (GD4AI/obsidian-llm-wiki)               │
│    - Almacenamiento Markdown en disco (~/Documents/ObsidianVault).          │
│    - Configuración centralizada en .obsidian/plugins/karpathywiki/data.json.│
│    - Interfaz gráfica: Graph View, chat RAG sobre notas y linting.          │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Lee notas / Escribe en wiki/
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. DAEMON AUTÓNOMO DE INGESTA (Este servicio en Docker)                     │
│    - Script Python (ingest_daemon.py) ejecutado en contenedor Docker.       │
│    - Detección en tiempo real mediante Watchdog (inotify).                  │
│    - Orquestador de inferencia con Gemini API (OpenAI compatibility).       │
│    - Persistencia de estado en SQLite: ingestion_state.db.                  │
│    - Mecanismos de tolerancia: parser JSON seguro, backoff y reintentos.    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Lee ingestion_state.db, wiki/ y logs
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. DASHBOARD WEB & TELEMETRÍA (obsidian_collector.py + UI)                  │
│    - Monitoreo en vivo de carpetas, notas procesadas, pendientes y errores. │
│    - Estimación de cuota diaria consumida de Gemini (Free Tier 500 req/día).│
│    - Visor interactivo Markdown (Marked.js) para fuentes, conceptos y ent.  │
│    - Visor en vivo de los últimos eventos del daemon.                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### ¿Por qué existe esta capa intermedia (Daemon)?
1. **Desacoplamiento total de la UI:** El plugin oficial de Obsidian requiere que Obsidian esté abierto y la computadora activa para procesar lotes. El daemon permite que la ingesta continúe en segundo plano 24/7 incluso si Obsidian está cerrado o en dispositivos móviles.
2. **Control riguroso de Rate Limiting:** La API de Google Gemini en su nivel gratuito impone límites estrictos (15 RPM y 500 peticiones/día). El daemon asegura un espaciado exacto de 120 segundos entre inferencias, evitando saturar cuotas.
3. **Persistencia y Auditoría:** La base de datos SQLite (`ingestion_state.db`) registra los hashes SHA-256 de las notas procesadas, garantizando que el sistema sea completamente idempotente (solo procesa notas nuevas o con modificaciones reales en su contenido).

---

## 🤖 Atribución de IA y Declaración de Autoría

Este proyecto fue desarrollado con la asistencia de **Google Gemini** (en modalidad de *pair-programming* asistido con Gemini 3.8 Flash). El diseño de la arquitectura, la implementación del código en `ingest_daemon.py`, la configuración de Docker, la lógica de recuperación de errores y la documentación fueron generados por el modelo de IA bajo requerimientos, supervisión y pruebas de bóveda reales por parte del autor humano.

- **Aporte Humano:** Concepción de la idea, definición de requerimientos, depuración de cuellos de botella en vaults reales, supervisión y validación en vivo.
- **Aporte de la IA:** Escritura del código en Python, parser tolerante a fallos de JSON, controladores de reintento, plantilla de systemd y documentación bilingüe.

*Aviso:* Aunque ha sido probado exhaustivamente en entornos reales, se recomienda mantener siempre copias de seguridad de tu bóveda de Obsidian antes de desplegar herramientas automáticas de ingesta.

---

## 📄 Licencia

Distribuido bajo la [Licencia MIT](LICENSE). Copyright (c) 2026 Matías Diez.

