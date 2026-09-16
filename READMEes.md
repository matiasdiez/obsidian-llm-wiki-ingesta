# KarpathyWiki — Daemon de Ingesta Desacoplado (Headless) para Obsidian

[English](README.md) | [Español](READMEes.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker: Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Built with: Gemini](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2.svg)](https://deepmind.google/technologies/gemini/)
[![Companion: Obsidian](https://img.shields.io/badge/Obsidian-Plugin%20Companion-7C3AED.svg)](https://obsidian.md/)

Daemon autónomo y de alto rendimiento que genera automáticamente entradas estructuradas de wiki (`wiki/concepts/`, `wiki/entities/`, `wiki/sources/`) en tu bóveda de Obsidian siguiendo la metodología [Karpathy LLM Wiki](https://github.com/GD4AI/obsidian-llm-wiki) y Google Gemini.

Se ejecuta continuamente 24/7 en segundo plano (vía Docker o Systemd), detectando la creación y edición de notas en tiempo real sin requerir que la aplicación de escritorio de Obsidian permanezca abierta.

---

## 💡 ¿Por qué este proyecto?

Aunque el plugin oficial [obsidian-llm-wiki](https://github.com/GD4AI/obsidian-llm-wiki) es potente, su procesamiento por lotes está fuertemente acoplado a la interfaz de usuario de Obsidian. Si cierras Obsidian, suspendes la computadora o tomas notas desde el móvil, el procesamiento en segundo plano se detiene.

Este daemon complementario proporciona:
1. **Ejecución Headless 24/7:** Se ejecuta como un contenedor Docker aislado o servicio Systemd en tu PC de escritorio, servidor doméstico, NAS o Raspberry Pi.
2. **Arquitectura Asíncrona y Concurrente:** Impulsado por `asyncio` y `AsyncOpenAI`. Incluye escaneo inicial concurrente limitado por semáforos y SQLite en modo WAL (`PRAGMA journal_mode=WAL`) para alto rendimiento sin bloqueos de base de datos.
3. **Structured Outputs Nativos (Pydantic):** Emplea los endpoints nativos `parse` de Gemini / OpenAI con esquemas Pydantic estrictos. Elimina errores de parseo JSON, comillas sin escapar o corrupción en fórmulas LaTeX (`\alpha`, `\int`, `\$`) directamente a nivel del modelo.
4. **🔗 Auto-Linker Inverso (Enlaces Mágicos):** Cuando se descubren nuevos conceptos o entidades, un pase asíncrono en segundo plano escanea notas existentes en la bóveda e inyecta enlaces bidireccionales `[[wiki]]` automáticamente, sin provocar bucles infinitos de reingesta.
5. **100% Amigable con el Free Tier:** Diseñado específicamente para operar de forma confiable dentro de las cuotas del nivel gratuito de Google Gemini (500 peticiones/día, 15 RPM) mediante limitación de ritmo proactiva (`REQUEST_INTERVAL=120s`) y retroceso exponencial dinámico.
6. **Ingesta Incremental e Idempotente:** Mantiene una base de datos de estado SQLite (`ingestion_state.db`) que rastrea hashes SHA-256 de cada nota. Las notas solo se procesan cuando su contenido cambia; las notas intactas consumen 0 tokens.
7. **Confiabilidad Multiplataforma en Docker:** Detecta automáticamente el entorno de ejecución y conmuta a `PollingObserver` en montajes Docker de macOS/Windows donde los eventos nativos `inotify` no se propaga.
8. **🧠 Búsqueda Semántica (Vector Embeddings):** Impulsada por `gemini-embedding-001` de Google y almacenada directamente en SQLite (sin ChromaDB ni dependencias pesadas en disco). Vectoriza las notas de la wiki y descubre conexiones conceptuales no evidentes, inyectando conceptos afines automáticamente.
9. **🏠 Modelos Locales Plug-and-Play (Ollama / LM Studio):** Ejecución 100% offline sin claves de API ni costes. Se conecta a cualquier servidor local compatible con OpenAI (`OPENAI_BASE_URL`), inyecta claves ficticias para localhost y cuenta con fallback transparente de JSON Schema a `json_object` + validación Pydantic.
10. **🔔 Notificaciones Nativas de Escritorio:** Recibe notificaciones toast inmediatas y discretas del sistema operativo (vía `plyer`) resumiendo los conceptos y entidades extraídos mientras redactas. Resiliente ante entornos sin interfaz gráfica o Docker.

---

## 🏗️ Arquitectura: Sistema de 3 Capas

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. BÓVEDA OBSIDIAN & PLUGIN COMUNITARIO (GD4AI/obsidian-llm-wiki)           │
│    - Notas Markdown en carpetas de la bóveda.                               │
│    - Configuración en .obsidian/plugins/karpathywiki/data.json.             │
│    - Interfaz gráfica: Graph View, chat RAG interactivo y linting de links. │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Monitorea cambios / Escribe en wiki/
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. DAEMON DE INGESTA ASÍNCRONO (Este servicio — Docker o Systemd)           │
│    - Servicio Python no bloqueante (ingest_daemon.py) basado en asyncio.    │
│    - Puente Watchdog (inotify / PollingObserver) con debounce (20s).        │
│    - Inferencia Gemini con Structured Outputs nativos de Pydantic.          │
│    - Auto-Linker en background: pase de regex para interconectar notas.     │
│    - Almacenamiento de estado y vectores en SQLite WAL (ingestion_state.db).│
│    - Throttling proactivo y protección de cuota (120s entre llamadas).      │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Telemetría y sincronización de lectura
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. DASHBOARD WEB & TELEMETRÍA (Opcional)                                    │
│    - Monitoreo de progreso en tiempo real (OK, Pendientes, Errores).        │
│    - Estimación de cuota diaria de Gemini (Rastreador de Free Tier).        │
│    - Lector Markdown integrado (Marked.js) para conceptos y entidades.      │
│    - Visor de flujo de registros en vivo.                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Inicio Rápido (Docker Compose)

### 1. Clonar el repositorio
```bash
git clone https://github.com/YOUR_USERNAME/obsidian-llm-wiki-ingesta.git
cd obsidian-llm-wiki-ingesta
```

### 2. Configurar variables de entorno
Copia `.env.example` a `.env`:
```bash
cp .env.example .env
```

Edita `.env` con tus preferencias:
```ini
# Obtén tu clave en https://aistudio.google.com/app/apikey
GEMINI_API_KEY=tu_clave_api_de_gemini_aqui

# Ruta absoluta a tu bóveda de Obsidian en la máquina host
VAULT_PATH=/home/usuario/Documentos/ObsidianVault

# Segundos entre llamadas a la API (120 para Gemini Free tier; 6 para tier de pago)
REQUEST_INTERVAL=120

# Opcional: carpetas a monitorear (separadas por comas).
# Si se deja vacío, lee watchedFolders de data.json o monitorea toda la bóveda.
# WATCHED_FOLDERS=Notas,Diario,Articulos

# Opcional: escanear notas antiguas e inyectar enlaces wiki al hallar nuevos conceptos/entidades.
# ENABLE_AUTO_LINK=true

# Opcional: generar embeddings para búsqueda semántica e inyectar conceptos relacionados.
# ENABLE_VECTOR_SEARCH=true

# Opcional: Modelos locales / offline (Ollama, LM Studio, vLLM, etc.)
# OPENAI_BASE_URL=http://localhost:11434/v1
# MODEL_NAME=llama3.1:8b
# EMBEDDING_MODEL_NAME=nomic-embed-text

# Opcional: notificaciones de escritorio del sistema al extraer nuevos conceptos
# ENABLE_NOTIFICATIONS=true
```

### 3. Construir e iniciar
```bash
docker compose up -d
```

### 4. Monitorear actividad en vivo
```bash
# Ver logs desde Docker
docker compose logs -f

# Ver directamente el archivo de log en la bóveda
tail -f /ruta/a/tu/boveda/karpathy_ingest.log
```

---

## 🛠️ Referencia de Configuración (`.env`)

| Variable | Requerido | Por Defecto | Descripción |
|---|:---:|:---:|---|
| `GEMINI_API_KEY` | **Sí** | — | Clave de API de Google Gemini desde [Google AI Studio](https://aistudio.google.com/app/apikey). |
| `VAULT_PATH` | **Sí** | `/vault` | Ruta absoluta a la bóveda de Obsidian en la máquina anfitriona. |
| `REQUEST_INTERVAL` | No | `120` | Segundos mínimos entre llamadas consecutivas a la API. Recomendado: `120` (Free tier) o `6` (Tier de pago). |
| `WATCHED_FOLDERS` | No | *del plugin* | Carpetas a vigilar separadas por coma. Si no se define, lee `watchedFolders` de `.obsidian/plugins/karpathywiki/data.json` o monitorea toda la bóveda. |
| `ENABLE_AUTO_LINK` | No | `false` | Escanea notas antiguas e inyecta enlaces mágicos `[[wiki]]` cuando se generan nuevos conceptos o entidades. |
| `ENABLE_VECTOR_SEARCH` | No | `false` | Genera embeddings vía Gemini `gemini-embedding-001` (o modelo local) y los guarda en SQLite (`ingestion_state.db`). Añade automáticamente "Conceptos Relacionados Semánticamente" a los nuevos conceptos. |
| `ENABLE_NOTIFICATIONS` | No | `false` | Envía notificaciones de escritorio nativas del sistema operativo tras una extracción exitosa (requiere ejecución local, puede no funcionar en Docker). |
| `OPENAI_BASE_URL` | No | *Gemini API* | URL base personalizada para endpoints locales compatibles con OpenAI (ej. `http://localhost:11434/v1` para Ollama, `http://localhost:1234/v1` para LM Studio). También acepta `LOCAL_API_BASE_URL`. Si apunta a `localhost` o `127.0.0.1`, no requiere `GEMINI_API_KEY`. |
| `MODEL_NAME` | No | `gemini-2.5-flash-lite` | Sobrescribe el nombre del modelo LLM (ej. `llama3.1:8b`, `qwen2.5:7b`, `mistral:7b`). |
| `EMBEDDING_MODEL_NAME` | No | `gemini-embedding-001` | Sobrescribe el modelo de embeddings para búsqueda vectorial (ej. `nomic-embed-text`, `bge-m3`, `all-minilm` para servidores locales). |

### Carpetas monitoreadas por defecto
Si no existe `data.json` del plugin y no se define `WATCHED_FOLDERS`, el daemon vigila por defecto:
- `00 Inbox/`, `01 Notas efímeras/`, `02 Notas permanentes/`, `03 Revisión bibliográfica/`, `04 Bibliografía/`, `Clippings/`.
- Siempre **ignora**: `wiki/`, `.obsidian/`, `.git/`, `.trash/`.

### Primera ejecución y reprocesamiento
- **Con escaneo inicial (por defecto):** procesa notas modificadas o no registradas en `ingestion_state.db`.
- **Sin escaneo inicial:** si solo deseas procesar notas creadas o editadas a partir de ahora, agrega `--no-initial-scan` al comando en `docker-compose.yml`:
  ```yaml
  command: /vault --request-interval ${REQUEST_INTERVAL:-120} --no-initial-scan
  ```

### Límites y cuotas de la API (Gemini Free Tier)
| Plan | Peticiones/día | `REQUEST_INTERVAL` sugerido |
|---|---|---|
| Free tier | 500 / día | 120s (~30/hora) |
| Paid tier | Sin límite diario | 6s (~10/minuto) |

Cuando se agota la cuota diaria (reset a medianoche, hora del Pacífico), el daemon lee el tiempo de espera sugerido directamente del encabezado de error de Gemini y reintenta automáticamente.

---

## 🔗 Auto-Linker Inverso (Inyección de Enlaces Mágicos)

Uno de los principales desafíos en los sistemas de gestión de conocimiento personal (PKM) es que, al extraer nuevos conceptos, las notas redactadas con anterioridad que ya mencionaban esos términos quedan desconectadas.

El daemon incluye un **AutoLinker** integrado que resuelve este problema:

1. **Disparo Reactivo al Extraer Conocimiento:** Cada vez que el daemon genera o actualiza notas de conceptos (`wiki/concepts/`) o entidades (`wiki/entities/`), se programa una tarea asíncrona en segundo plano.
2. **Expresiones Regulares Seguras para Markdown:** Utiliza lookarounds negativos `(?<!\[\[)(?<!\[)\b(termino)\b(?!\]\])(?!\])(?!\))` y segmentación de bloques de código (```) garantizando que:
   - Los enlaces wiki preexistentes (`[[...]]`) jamás se dupliquen.
   - Los enlaces markdown tradicionales y URLs (`[título](url)`) permanezcan intactos.
   - Los bloques de código y snippets no sean modificados.
   - Términos cortos (≤ 3 caracteres) sean excluidos para prevenir falsos positivos.
3. **Prevención de Bucles Infinitos:** Si una nota existente se modifica para inyectarle enlaces, el daemon recalcula inmediatamente su hash SHA-256 y lo actualiza en SQLite (`ingestion_state.db`) con estado `ok`. De este modo, la nota queda registrada y **no** entra en un ciclo de reingesta infinita.
4. **Ejecución en Segundo Plano No Bloqueante:** Se ejecuta en una tarea asyncio independiente, por lo que el monitoreo de archivos y la ingesta continúan sin interrupción.

---

## 🧠 Búsqueda Semántica (Vector Embeddings)

Además del emparejamiento literal por palabras clave, el daemon vectoriza las notas wiki generadas y descubre conceptos semánticamente afines usando el modelo **`gemini-embedding-001`** de Google, almacenando los vectores en **SQLite** (en el mismo archivo `ingestion_state.db` que ya utiliza el daemon).

### ¿Por qué abandonamos ChromaDB?
La implementación original empleaba **ChromaDB** con un índice HNSW para la búsqueda vectorial. En la práctica, esto causó un problema grave: ChromaDB depende de librerías con extensiones nativas (`onnxruntime`, `hnswlib`) que no distribuyen wheels precompilados para `musl` (la librería C de Alpine Linux). En la imagen Docker basada en Alpine del proyecto, `pip` debía **compilar esas dependencias desde el código fuente** en cada build, lo que consumía varios gigabytes de disco y hacía fallar por completo el comando `docker compose build`.

Sumado a esto, Google deprecó `text-embedding-004` (el modelo al que llamaba originalmente este proyecto) en enero de 2026, interrumpiendo el funcionamiento de la implementación anterior con independencia del problema de espacio en disco.

En lugar de limitarnos a cambiar la imagen base, reevaluamos si realmente era necesario un motor de base de datos vectorial dedicado. Para una bóveda personal de Obsidian (de cientos a pocos miles de notas), no lo es: una búsqueda exhaustiva por similitud coseno sobre todos los vectores almacenados, implementada mediante `numpy`, se ejecuta en una fracción de segundo. Por ello, la solución eliminó esa pieza superflua por completo:

- **Sin ChromaDB ni dependencias nativas pesadas de ML:** `requirements.txt` ya no requiere `chromadb`; solo se incorporó `numpy`, que cuenta con wheels precompilados sumamente ligeros.
- **`gemini-embedding-001` en reemplazo del deprecado `text-embedding-004`:** actualmente el modelo líder de Google en el leaderboard MTEB Multilingüe, invocado a través del mismo cliente compatible con OpenAI que el proyecto ya utiliza para la generación de texto.
- **Los vectores residen en SQLite:** no en una base de datos embebida independiente — un servicio menos, una base de datos menos que respaldar o susceptible de corrupción.
- **`python:3.12-slim` en reemplazo de `python:3.12-alpine`** en el `Dockerfile` (build multi-stage): las imágenes basadas en Debian disponen de wheels precompilados para prácticamente la totalidad de paquetes en PyPI, eliminando por completo la necesidad de compilar paquetes en `pip install`.

### 1. ¿Cómo funciona?
- **Persistencia Local:** Los vectores se almacenan como `BLOB` en `.obsidian/plugins/karpathywiki/ingestion_state.db`, dentro de una tabla `embeddings` junto al seguimiento del estado de ingesta. No se requiere ninguna base de datos vectorial en la nube ni servicios SaaS externos — únicamente el *cálculo* del embedding se realiza en línea mediante la API de Gemini que ya utilizas para generar texto.
- **Indexación Universal de Conocimiento:** Cada entrada generada (`wiki/sources/`, `wiki/concepts/`, `wiki/entities/`) se vectoriza y almacena junto con su `doc_type` (`concept` | `source` | `entity`).
- **Puentes Conceptuales Automáticos:** Cuando se genera o actualiza una nota de concepto, el daemon calcula la similitud coseno en memoria contra todos los vectores almacenados con tipo `concept` y añade los 3 mejores resultados (`top_k=3`) al final del archivo:
  ```markdown
  ### 🧠 Conceptos Relacionados Semánticamente
  - [[wiki/concepts/principio-de-energia-libre|Principio de Energía Libre]]
  - [[wiki/concepts/codificacion-predictiva|Codificación Predictiva]]
  - [[wiki/concepts/cerebro-bayesiano|Cerebro Bayesiano]]
  ```
- **Integridad de Estado y Anti-Loop:** Dado que el archivo de concepto se modifica para incorporar los conceptos relacionados, el daemon recalcula de inmediato el hash SHA-256 definitivo y actualiza `ingestion_state.db`, asegurando que este enriquecimiento automático no desencadene un ciclo infinito de ingesta.
- **Reintentos Resilientes:** Cuenta con reintentos automáticos con retroceso exponencial (hasta 3 intentos) en el endpoint de embeddings para garantizar una indexación robusta.

### 2. Activación
Añade la siguiente variable a tu archivo `.env`:
```ini
ENABLE_VECTOR_SEARCH=true
```
No se requieren dependencias adicionales de sistema más allá de las incluidas en `requirements.txt`.

---

## 🏠 Modelos Locales y Offline (Ollama, LM Studio, vLLM)

Puedes ejecutar el daemon de ingesta de forma completamente offline y privada sin depender de Google Gemini ni de proveedores cloud. El daemon se conecta nativamente con cualquier servidor local que exponga una API compatible con OpenAI.

### 1. Puesta en marcha rápida con Ollama
Descarga los modelos de LLM y embeddings de tu elección:
```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 2. Configuración en `.env`
Define el endpoint local y los modelos en tu archivo `.env`:
```ini
# Endpoint local compatible con OpenAI
OPENAI_BASE_URL=http://localhost:11434/v1

# Modelos
MODEL_NAME=llama3.1:8b
EMBEDDING_MODEL_NAME=nomic-embed-text

# No se requiere limitación de velocidad para inferencia local
REQUEST_INTERVAL=0

# Habilitar búsqueda vectorial (los vectores se guardan en SQLite igualmente)
ENABLE_VECTOR_SEARCH=true
```

> [!TIP]
> **No se Requiere Clave de API:** Cuando `OPENAI_BASE_URL` contiene `localhost` o `127.0.0.1`, el daemon inyecta automáticamente una clave ficticia (`local-dummy-key`). No necesitas definir `GEMINI_API_KEY`.

### 3. Fallback Transparente de JSON y Validación con Pydantic
Si bien los endpoints oficiales de OpenAI y Gemini soportan `beta.chat.completions.parse` (esquema JSON estricto), muchos servidores locales de inferencia (Ollama, LM Studio, vLLM) aún no implementan esta gramática beta y devuelven un error `400 Bad Request`.

El daemon gestiona esto de forma automática:
1. Intenta en primer lugar ejecutar `beta.chat.completions.parse`.
2. Si el servidor local arroja un `BadRequestError`, conmuta de forma transparente al método estándar `chat.completions.create` con `response_format={"type": "json_object"}` y anexa instrucciones estrictas de esquema en el prompt.
3. Elimina automáticamente los delimitadores de código markdown (````json ... ````) devueltos por LLMs locales.
4. Valida el contenido JSON resultante a través de `WikiResponse.model_validate_json(...)` para asegurar la total conformidad con el esquema antes de escribir en tu bóveda.

---

## 🔔 Notificaciones Nativas de Escritorio

Si ejecutas el daemon directamente en tu sistema de escritorio (Linux, macOS o Windows vía Systemd o Python nativo), puedes habilitar notificaciones toast en tiempo real en tu sistema operativo:

- **Resúmenes Inteligentes:** Emite una notificación cada vez que se genera nuevo conocimiento satisfactoriamente, por ejemplo:
  > **KarpathyWiki**  
  > *Extraídos 2 conceptos y 1 entidades de 'Inferencia Activa'*
- **Asíncrono y No Bloqueante:** Despachado de forma asíncrona mediante `asyncio.to_thread` para que los ciclos de ingesta y monitoreo no se detengan.
- **Resiliente en Entornos Headless y Docker:** Si se ejecuta dentro de Docker o en un servidor headless sin interfaz gráfica o servidor de pantalla, los fallos de notificación se capturan y silencian de forma segura sin detener el servicio.
- **Cómo habilitarlo:**
  ```ini
  ENABLE_NOTIFICATIONS=true
  ```
  *(Requiere `plyer>=2.1.0` en `requirements.txt`).*

---

## ⚙️ Cómo Funciona la Ingesta

```
Tu nota en Obsidian
       │
       ▼ (Watchdog inotify / PollingObserver detecta cambio)
  Debounce (20s — espera a que termines de redactar)
       │
       ▼ (Comprobación de hash SHA-256 contra ingestion_state.db)
  ¿Hash coincide y estado es OK? ──► Ignorado (0 tokens, 0 coste)
  ¿Nota nueva o modificada?
       │
       ▼ (Control de velocidad — respeta REQUEST_INTERVAL)
  Llamada a API de Google Gemini (Structured Outputs de Pydantic)
       │
       ├─────────────────────────────────────────────┐
       ▼                                             ▼
  wiki/sources/   ← Resumen y metadatos         [Si ENABLE_AUTO_LINK=true]
  wiki/concepts/  ← Conceptos, definiciones     Auto-Linker en segundo plano:
  wiki/entities/  ← Personas, organizaciones    Escanea notas viejas e inyecta [[links]]
       │                                        Actualiza SHA-256 en SQLite (sin loops)
       ▼ [Si ENABLE_VECTOR_SEARCH=true]
  Almacén Vectorial (SQLite):
  - Genera embeddings con gemini-embedding-001
  - Inyecta "Conceptos Relacionados Semánticamente" en notas de conceptos
  - Actualiza el hash SHA-256 de la nota en SQLite
```

### Seguridad e Integridad de la Bóveda
- **Modo por defecto (`ENABLE_AUTO_LINK=false`):** Estrictamente de **solo lectura** sobre tus notas de origen. El daemon únicamente crea archivos bajo `wiki/` y actualiza la base de datos SQLite. Jamás borra ni modifica tus notas originales.
- **Modo Auto-Linker (`ENABLE_AUTO_LINK=true`):** Inyecta enlaces wiki de forma segura (`[[wiki/...|Término]]`) en notas existentes, preservando snippets de código y URLs, y registrando los hashes para asegurar absoluta idempotencia.
- **Directorios ignorados:** Omite automáticamente `wiki/`, `.obsidian/`, `.git/` y `.trash/`.

---

## 🖥️ Alternativa: Ejecución con Systemd (Linux Nativo)

Si prefieres ejecutar el daemon de forma nativa en Ubuntu, Debian o Raspberry Pi sin Docker:

1. **Instalar dependencias en un entorno virtual:**
   ```bash
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```

2. **Configurar la unidad de servicio:**
   Edita `karpathy-wiki-ingest@.service` con tu usuario y la ruta a tu bóveda.

3. **Instalar y habilitar el servicio:**
   ```bash
   sudo cp karpathy-wiki-ingest@.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now karpathy-wiki-ingest@$USER
   ```

4. **Comprobar estado y ver logs en vivo:**
   ```bash
   systemctl status karpathy-wiki-ingest@$USER
   journalctl -u karpathy-wiki-ingest@$USER -f
   ```

---

## 📋 Chuleta de Comandos de Docker

| Acción | Comando |
|---|---|
| **Iniciar** | `docker compose up -d` |
| **Detener** | `docker compose stop` |
| **Reiniciar** | `docker compose restart` |
| **Ver logs** | `docker compose logs -f` |
| **Reconstruir imagen** | `docker compose build` |
| **Destruir contenedor** | `docker compose down` |
| **Comprobar estado** | `docker ps \| grep karpathy` |

---

## 🔍 Ejemplo de Salida de Logs

```text
🚀 KarpathyWiki Ingest Daemon (Async) started
   Vault    : /vault
   Model    : gemini-2.5-flash-lite
   Debounce : 20s
   Throttle : 120s between API calls
   Watching : 02 Permanent Notes/, Clippings/
   Log file : /vault/karpathy_ingest.log
============================================================
🔍 Running initial vault scan…
🔍 Found 2 modified/new note(s). Processing concurrently...
📝 Processing note: 02 Permanent Notes/Active Inference.md
⏳ Rate limiter: waiting 118.3s before next API call…
  ✅ Written: wiki/sources/active-inference_4f2a.md
  ✅ Written: wiki/concepts/markov-blanket.md
  ✅ Written: wiki/concepts/free-energy-principle.md
  ✅ Generated 3 wiki file(s) from: 02 Permanent Notes/Active Inference.md
🔗 Auto-Linker: Iniciando escaneo de enlaces mágicos en la bóveda...
  🔗 Auto-Linker: 2 enlaces inyectados en 01 Fleeting Notes/Reading List.md
🔗 Auto-Linker: Pass completado. 2 enlaces inyectados en 1 notas.
```

---

## 🤝 Relación con el Plugin Oficial de Obsidian

Este proyecto es una herramienta complementaria y autónoma diseñada para operar junto al [Karpathy LLM Wiki Obsidian Plugin](https://github.com/GD4AI/obsidian-llm-wiki) creado por `GD4AI` / `green-dalii`. Ambas herramientas respetan exactamente la misma estructura de carpetas (`wiki/concepts/`, `wiki/entities/`, `wiki/sources/`), permitiéndote usar Obsidian para la exploración visual del grafo y chat RAG interactivo, mientras este daemon desacoplado gestiona la ingesta continua en segundo plano.

---

## 🤖 Atribución de IA y Declaración de Autoría

Este proyecto fue desarrollado con la asistencia de **Google Gemini** (en modalidad de *pair-programming* asistido con Gemini 3.8 Flash). El diseño arquitectónico, la implementación del código en `ingest_daemon.py`, la configuración de Docker, los mecanismos de tolerancia a fallos y la documentación fueron generados bajo requerimientos, supervisión y pruebas en bóvedas reales por parte del autor humano.

- **Aporte Humano:** Diseño conceptual, especificaciones arquitectónicas, depuración de cuellos de botella en bóvedas reales, validación de pruebas y dirección de prompts.
- **Aporte de la IA:** Generación de código, refactorización a asyncio, integración de Structured Outputs con Pydantic, motor de regex para Auto-Linker, plantilla de systemd y documentación técnica bilingüe.

*Descargo de responsabilidad:* Aunque ha sido probado exhaustivamente en bóvedas reales, mantén siempre copias de seguridad de tu bóveda de Obsidian antes de desplegar herramientas de ingesta automatizadas.

---

## 📄 Licencia

Distribuido bajo la [Licencia MIT](LICENSE). Copyright (c) 2026 Matías Diez.
