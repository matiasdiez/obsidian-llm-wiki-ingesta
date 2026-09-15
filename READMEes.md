# KarpathyWiki — Daemon de Ingesta Automática para Obsidian

[English](README.md) | [Español](READMEes.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker: Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Built with: Gemini](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2.svg)](https://deepmind.google/technologies/gemini/)
[![Companion: Obsidian](https://img.shields.io/badge/Obsidian-Plugin%20Companion-7C3AED.svg)](https://obsidian.md/)

Daemon autónomo y asíncrono en Python que automatiza la generación de notas wiki en Obsidian siguiendo la metodología [Karpathy LLM Wiki](https://github.com/GD4AI/obsidian-llm-wiki). Detecta en tiempo real la creación o edición de notas y genera automáticamente entradas estructuradas en `wiki/concepts/`, `wiki/entities/` y `wiki/sources/`, sin depender de mantener abierta la aplicación de Obsidian.

---

## 💡 Novedades y Capacidades Destacadas

1. **Núcleo Asíncrono de Alto Rendimiento:** Basado en `asyncio` y `AsyncOpenAI`. Escaneo inicial concurrente acotado por semáforos y base de datos SQLite optimizada en modo WAL (`PRAGMA journal_mode=WAL`) para máxima fluidez y cero bloqueos.
2. **Structured Outputs Nativos con Pydantic:** Abandona el parseo manual de JSON frágil. Valida esquemas de forma nativa a través de la API de Gemini/OpenAI, garantizando el 100% de integridad en fórmulas LaTeX (`\alpha`, `\int`), comillas y sintaxis markdown.
3. **🔗 Auto-Linker Inverso (Enlaces Mágicos):** Al descubrir nuevos conceptos o entidades, un pase en segundo plano escanea notas antiguas en la bóveda e inyecta enlaces bidireccionales `[[wiki]]` automáticamente, sin provocar bucles infinitos de reingesta.
4. **100% Amigable con el Free Tier de Gemini:** Throttling proactivo configurable (`REQUEST_INTERVAL=120s`) y backoff exponencial que respetan a rajatabla los límites gratuitos de Google Gemini (15 RPM / 500 peticiones diarias).
5. **Idempotencia Estricta:** SQLite (`ingestion_state.db`) registra los hashes SHA-256 de cada archivo; si una nota no ha cambiado, el costo en tokens y llamadas es cero.
6. **Compatibilidad Docker Multiplataforma:** Detección automática con fallback a `PollingObserver` para contenedores sobre macOS y Windows donde `inotify` no se propaga a través de volúmenes compartidos.
7. **🧠 Embeddings Locales y Búsqueda Vectorial:** Integración con ChromaDB y Google `text-embedding-004`. Indexa la base de conocimiento localmente en disco y enlaza de forma autónoma conceptos semánticamente afines.
8. **🏠 Soporte Plug-and-Play para Modelos Locales (Ollama / LM Studio):** Ejecución 100% offline y gratuita sin depender de APIs en la nube. Incluye fallback automático si el servidor local no soporta `beta.chat.completions.parse`, retrocediendo a `json_object` y validando con Pydantic. Inyección automática de API key ficticia para `localhost`.
9. **🔔 Notificaciones Nativas de Escritorio:** Recibe notificaciones toast inmediatas y discretas del sistema operativo (vía `plyer`) con un resumen inteligente cada vez que se extraen nuevos conceptos o entidades mientras escribes. Mecanismo resiliente que ignora caídas en entornos sin interfaz gráfica o Docker.

---

## Cómo funciona

```
Tu nota en Obsidian
       │
       ▼ (watchdog inotify / PollingObserver detecta cambio)
  Debounce 20s (espera a que termines de redactar)
       │
       ▼ (hash SHA-256 contra ingestion_state.db)
  Sin cambios & estado OK → ignorado (0 tokens, 0 costo)
  Nota nueva o modificada
       │
       ▼ (control de ritmo: espera REQUEST_INTERVAL)
  Inferencia Gemini API (Structured Outputs con Pydantic)
       │
       ├─────────────────────────────────────────────┐
       ▼                                             ▼
  wiki/sources/   ← resumen de la nota          [Si ENABLE_AUTO_LINK=true]
  wiki/concepts/  ← conceptos y definiciones        Auto-Linker en segundo plano:
  wiki/entities/  ← personas y organizaciones       Escanea notas viejas e inyecta [[links]]
       │                                            Actualiza hash en SQLite (sin bucles)
       ▼ [Si ENABLE_VECTOR_SEARCH=true]
  Almacén Vectorial ChromaDB:
  - Genera embeddings con text-embedding-004
  - Inyecta "Conceptos Relacionados Semánticamente" en la nota
  - Actualiza el hash final de la nota en SQLite
```

**Lee la configuración** del plugin desde `.obsidian/plugins/karpathywiki/data.json` (carpetas monitoreadas, modelo, idioma). Si no encuentra el archivo, puede definirse en `.env` o monitorear todo el vault.

**Evita reprocesar:** guarda un hash SHA-256 de cada nota procesada en `.obsidian/plugins/karpathywiki/ingestion_state.db` en modo WAL. Si la nota no cambió y su estado anterior fue exitoso, no hace ninguna llamada a la API.

---

## Estructura del proyecto

```
obsidian-llm-wiki-ingesta/
├── ingest_daemon.py       # Script principal del daemon (asyncio)
├── Dockerfile             # Imagen Python 3.12 Alpine (~80MB)
├── docker-compose.yml     # Gestión simplificada del contenedor
├── requirements.txt       # Dependencias Python (watchdog, openai, pydantic, chromadb)
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
# ENABLE_AUTO_LINK=true
# ENABLE_VECTOR_SEARCH=true

# Opcional: Modelos Locales Offline (Ollama, LMStudio, vLLM, etc.)
# OPENAI_BASE_URL=http://localhost:11434/v1
# MODEL_NAME=llama3.1:8b
# EMBEDDING_MODEL_NAME=nomic-embed-text

# Opcional: Notificaciones de sistema
# ENABLE_NOTIFICATIONS=true
```

| Variable | Requerido | Valor recomendado / Descripción |
|---|:---:|---|
| `GEMINI_API_KEY` | **Sí** | Clave de API de Gemini desde [Google AI Studio](https://aistudio.google.com/app/apikey). |
| `VAULT_PATH` | **Sí** | Ruta absoluta al vault de Obsidian en el host. |
| `REQUEST_INTERVAL` | No | Segundos entre llamadas a la API: `120` (Free tier) · `6` (Paid tier). |
| `WATCHED_FOLDERS` | No | Lista de carpetas a monitorear separadas por coma. Si se omite, lee `watchedFolders` del plugin en `data.json`, o monitorea todo el vault. |
| `ENABLE_AUTO_LINK` | No | Activa la inyección automática de enlaces mágicos `[[wiki]]` en notas antiguas cuando se extraen nuevos conceptos. (`true`/`false`) |
| `ENABLE_VECTOR_SEARCH` | No | Genera embeddings (`text-embedding-004` o modelo local) en ChromaDB y añade "Conceptos Relacionados Semánticamente" al final de cada concepto nuevo. (`true`/`false`) |
| `ENABLE_NOTIFICATIONS` | No | Envía notificaciones de escritorio del SO cuando se extraen conceptos exitosamente (requiere ejecución local, puede fallar en Docker). (`true`/`false`) |
| `OPENAI_BASE_URL` | No | URL base personalizada para servidores locales compatibles con OpenAI (ej. `http://localhost:11434/v1` para Ollama, `http://localhost:1234/v1` para LM Studio). También acepta `LOCAL_API_BASE_URL`. Si apunta a `localhost` o `127.0.0.1`, no requiere `GEMINI_API_KEY`. |
| `MODEL_NAME` | No | Sobrescribe el nombre del modelo LLM (ej. `llama3.1:8b`, `qwen2.5:7b`, `mistral:7b`). Por defecto: `gemini-2.5-flash-lite`. |
| `EMBEDDING_MODEL_NAME` | No | Sobrescribe el nombre del modelo de embeddings para búsqueda vectorial (ej. `nomic-embed-text`, `bge-m3`). Por defecto: `text-embedding-004`. |

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

```text
🚀 KarpathyWiki Ingest Daemon (Async) started
   Vault    : /vault
   Model    : gemini-2.5-flash-lite
   Debounce : 20s
   Throttle : 120s between API calls
   Watching : 02 Notas permanentes/, Clippings/
   Log file : /vault/karpathy_ingest.log
============================================================
🔍 Running initial vault scan…
🔍 Found 2 modified/new note(s). Processing concurrently...
📝 Processing note: 02 Notas permanentes/Inferencia Activa.md
⏳ Rate limiter: waiting 118.3s before next API call…
  ✅ Written: wiki/sources/inferencia-activa_4f2a.md
  ✅ Written: wiki/concepts/frontera-de-markov.md
  ✅ Written: wiki/concepts/principio-de-energia-libre.md
  ✅ Generated 3 wiki file(s) from: 02 Notas permanentes/Inferencia Activa.md
🔗 Auto-Linker: Iniciando escaneo de enlaces mágicos en la bóveda...
  🔗 Auto-Linker: 2 enlaces inyectados en 01 Notas efímeras/Lecturas.md
🔗 Auto-Linker: Pass completado. 2 enlaces inyectados en 1 notas.
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

## 🔗 Auto-Linker Inverso (Inyección de Enlaces Mágicos)

Uno de los principales desafíos en los sistemas de gestión de conocimiento (PKM / Zettelkasten) es que, al extraer nuevos conceptos o entidades, las notas redactadas con anterioridad que ya mencionaban esos términos quedan desconectadas.

El daemon integra un motor de **AutoLinker** inverso que resuelve esto de forma automática y segura:

1. **Disparo Reactivo:** Cada vez que el daemon genera o actualiza conceptos (`wiki/concepts/`) o entidades (`wiki/entities/`), programa una tarea asíncrona en segundo plano.
2. **Expresiones Regulares con Protección Estricta:** Utiliza regex con lookarounds negativos `(?<!\[\[)(?<!\[)\b(termino)\b(?!\]\])(?!\])(?!\))` y segmenta el texto omitiendo bloques de código (\`\`\`), garantizando que:
   - Los enlaces wiki preexistentes (`[[...]]`) jamás se dupliquen.
   - Los enlaces markdown tradicionales y URLs (`[texto](url)`) no se alteren.
   - Los bloques de código y snippets no sean modificados.
   - Términos cortos (≤ 3 caracteres) se descartan para evitar falsos positivos.
3. **Prevención de Bucles Infinitos:** Si una nota existente es modificada para inyectarle enlaces, el daemon recalcula inmediatamente su hash SHA-256 y lo actualiza en SQLite (`ingestion_state.db`) con estado `ok`. De este modo, la nota queda registrada y **no** entra en un ciclo de reingesta infinita.
4. **Ejecución Asíncrona:** Se ejecuta en una corutina de fondo sin congelar la detección de eventos ni la ingesta de notas entrantes.

---

## 🧠 Embeddings Locales para Búsqueda Semántica (Vector Search)

Además de la vinculación explícita por nombres y entidades, el daemon incorpora un subsistema de base de datos vectorial local impulsado por **ChromaDB** y el modelo **`text-embedding-004`** de Google:

### 1. ¿Cómo funciona?
- **Almacenamiento Local Persistente:** Los vectores e índices se almacenan directamente dentro de tu vault en `.obsidian/plugins/karpathywiki/chroma_db` mediante un índice HNSW con métrica de similitud coseno (`cosine`). Es 100% privado, local y sin costos de bases de datos en la nube ni servicios de terceros.
- **Indexación Integral de Conocimiento:** Cada entrada generada (`wiki/sources/`, `wiki/concepts/`, `wiki/entities/`) se vectoriza y almacena junto a su metadato de clasificación (`{"type": "concept" | "source" | "entity"}`).
- **Descubrimiento Conceptual Autónomo:** Cuando se genera o actualiza una nota de concepto, el daemon consulta automáticamente en ChromaDB los 3 conceptos conceptualmente más próximos (`top_k=3`) e inyecta al final del archivo una sección con enlaces wiki:
  ```markdown
  ### 🧠 Conceptos Relacionados Semánticamente
  - [[wiki/concepts/principio-de-energia-libre|Principio De Energia Libre]]
  - [[wiki/concepts/codificacion-predictiva|Codificacion Predictiva]]
  - [[wiki/concepts/cerebro-bayesiano|Cerebro Bayesiano]]
  ```
- **Integridad de Hash e Idempotencia:** Como la nota de concepto se modifica para agregar los enlaces relacionados, el daemon recalcula inmediatamente el hash SHA-256 definitivo y lo actualiza en `ingestion_state.db` con estado `ok`, evitando bucles de reingesta.
- **Tolerancia y Reintentos:** Cuenta con reintentos automáticos con backoff exponencial (hasta 3 intentos) para la generación de embeddings en caso de microcortes de red.

### 2. Activación
Añade la siguiente variable a tu `.env`:
```ini
ENABLE_VECTOR_SEARCH=true
```
*(Requiere `chromadb>=0.4.0` en `requirements.txt`).*

---

## 🏠 Modelos Locales y Offline (Ollama, LM Studio, vLLM)

Es posible ejecutar el daemon de ingesta de forma completamente offline y privada sin enviar datos a Google Gemini ni incurrir en costes de API, aprovechando modelos locales mediante cualquier servidor con interfaz compatible con OpenAI.

### 1. Puesta en marcha rápida con Ollama
Descarga tus modelos preferidos de LLM y embeddings:
```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 2. Configuración en `.env`
Configura el endpoint local y los nombres de los modelos en tu archivo `.env`:
```ini
# Endpoint local compatible con OpenAI
OPENAI_BASE_URL=http://localhost:11434/v1

# Modelos
MODEL_NAME=llama3.1:8b
EMBEDDING_MODEL_NAME=nomic-embed-text

# Sin esperas de limitación de tasa para inferencia local
REQUEST_INTERVAL=0

# Búsqueda vectorial local con ChromaDB
ENABLE_VECTOR_SEARCH=true
```

> [!TIP]
> **Sin API Key Requerida:** Cuando `OPENAI_BASE_URL` contiene `localhost` o `127.0.0.1`, el daemon inyecta de forma automática una clave ficticia (`local-dummy-key`). No necesitas definir `GEMINI_API_KEY`.

### 3. Fallback Transparente de JSON y Validación con Pydantic
Muchos servidores locales de inferencia (Ollama, LM Studio, vLLM) no implementan la sintaxis específica `beta.chat.completions.parse` de OpenAI y devuelven un error `400 Bad Request`.

El daemon gestiona esto de forma completamente automática y transparente:
1. Intenta en primer lugar invocar `beta.chat.completions.parse`.
2. Si el servidor local responde con `BadRequestError`, captura la excepción y retrocede de inmediato a `chat.completions.create` con `response_format={"type": "json_object"}`, inyectando instrucciones estrictas de formato JSON en el prompt.
3. Limpia automáticamente cualquier bloque de código markdown (````json ... ````) que el modelo local añada.
4. Valida y deserializa el JSON directamente con `WikiResponse.model_validate_json(...)` de Pydantic antes de escribir cualquier archivo en tu bóveda.

---

## 🔔 Notificaciones Nativas de Escritorio

Si ejecutas el daemon directamente en tu máquina local (Linux, macOS o Windows mediante Systemd o Python nativo), puedes habilitar notificaciones toast en tiempo real en tu sistema operativo:

- **Resumen Inteligente:** Notifica cada vez que se extraen nuevos conocimientos con éxito, por ejemplo:
  > **KarpathyWiki**  
  > *Extraídos 2 conceptos y 1 entidades de 'Inferencia Activa'*
- **Asíncrono y No Bloqueante:** Se despacha a través de `asyncio.to_thread` para no interrumpir el flujo del event loop ni la detección de notas.
- **Resiliente ante Fallos:** Si se ejecuta en entornos headless, servidores sin display gráfico o dentro de contenedores Docker, captura de forma segura cualquier excepción sin interrumpir la ejecución del daemon.
- **Activación:**
  ```ini
  ENABLE_NOTIFICATIONS=true
  ```
  *(Requiere `plyer>=2.1.0` en `requirements.txt`).*

---

## Seguridad

- **Modo por defecto (`ENABLE_AUTO_LINK=false`):** El daemon opera estrictamente en **modo de solo lectura** sobre tus notas de origen. Solo escribe en `wiki/sources/`, `wiki/concepts/`, `wiki/entities/`, el log y la base de datos SQLite.
- **Modo Auto-Linker (`ENABLE_AUTO_LINK=true`):** Modifica quirúrgicamente notas existentes **únicamente** para inyectar enlaces `[[wiki/...]]` a conceptos ya indexados, respetando enlaces preexistentes, URLs y bloques de código, y registrando el nuevo hash en SQLite.
- **Nunca borra** ningún archivo de tu bóveda.
- Si un archivo wiki ya existe con el mismo nombre, lo sobreescribe con el contenido refinado.
- **Carpetas ignoradas:** `wiki/`, `.obsidian/`, `.git/`, `.trash/`.

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
│ 2. DAEMON AUTÓNOMO ASÍNCRONO (Este servicio en Docker o Systemd)            │
│    - Script Python asíncrono (ingest_daemon.py) impulsado por asyncio.     │
│    - Watchdog (inotify / PollingObserver) con debounce de 20s.              │
│    - Inferencia con Gemini API y Structured Outputs nativos (Pydantic).     │
│    - Auto-Linker inverso en background para interconectar notas de la wiki. │
│    - Persistencia en SQLite WAL (ingestion_state.db) para alta concurrencia.│
│    - Throttling proactivo (120s entre peticiones) y reintentos automáticos. │
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
1. **Desacoplamiento total de la UI:** El plugin oficial de Obsidian requiere que la app de escritorio esté abierta y la máquina activa. El daemon permite que la ingesta continúe en segundo plano 24/7 en servidores domésticos, Raspberry Pi o NAS, incluso si tomas notas desde el móvil.
2. **Núcleo Asíncrono y Rate Limiting Riguroso:** La API de Google Gemini en su nivel gratuito impone límites estrictos (15 RPM y 500 peticiones/día). El daemon gestiona la concurrencia con `asyncio` y asegura un espaciado exacto de 120 segundos entre inferencias, evitando saturar cuotas.
3. **Structured Outputs Nativos (Pydantic):** Elimina el parseo manual de JSON. El LLM devuelve respuestas que cumplen estrictamente el esquema de datos tipado en Python, blindando la salida frente a errores sintácticos o fórmulas LaTeX complejas.
4. **Auto-Enlazado Retroactivo:** Mantiene la bóveda hiperconectada sin trabajo manual, enlazando menciones antiguas cada vez que se descubre un concepto nuevo.
5. **Persistencia e Idempotencia:** La base de datos SQLite en modo WAL (`ingestion_state.db`) registra los hashes SHA-256 de las notas, garantizando que notas sin modificaciones consuman 0 tokens.

---

## 🤖 Atribución de IA y Declaración de Autoría

Este proyecto fue desarrollado con la asistencia de **Google Gemini** (en modalidad de *pair-programming* asistido con Gemini 3.8 Flash). El diseño de la arquitectura, la implementación del código en `ingest_daemon.py`, la configuración de Docker, la lógica de recuperación de errores y la documentación fueron generados por el modelo de IA bajo requerimientos, supervisión y pruebas de bóveda reales por parte del autor humano.

- **Aporte Humano:** Concepción de la idea, definición de requerimientos, depuración de cuellos de botella en vaults reales, supervisión y validación en vivo.
- **Aporte de la IA:** Código en Python, migración a arquitectura asíncrona con asyncio, integración de Structured Outputs con Pydantic, motor de regex para Auto-Linker inverso, plantilla de systemd y documentación técnica bilingüe.

*Aviso:* Aunque ha sido probado exhaustivamente en entornos reales, se recomienda mantener siempre copias de seguridad de tu bóveda de Obsidian antes de desplegar herramientas automáticas de ingesta.

---

## 📄 Licencia

Distribuido bajo la [Licencia MIT](LICENSE). Copyright (c) 2026 Matías Diez.

