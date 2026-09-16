# KarpathyWiki — Headless Ingestion Daemon for Obsidian

[English](README.md) | [Español](READMEes.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker: Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Built with: Gemini](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2.svg)](https://deepmind.google/technologies/gemini/)
[![Companion: Obsidian](https://img.shields.io/badge/Obsidian-Plugin%20Companion-7C3AED.svg)](https://obsidian.md/)

An autonomous, high-performance background daemon that automatically generates structured wiki entries (`wiki/concepts/`, `wiki/entities/`, `wiki/sources/`) in your Obsidian vault using the [Karpathy LLM Wiki](https://github.com/GD4AI/obsidian-llm-wiki) methodology and Google Gemini.

It runs continuously 24/7 in the background (via Docker or Systemd), detecting note creation and edits in real time with zero dependency on keeping the Obsidian desktop application open.

---

## 💡 Why This Project?

While the official [obsidian-llm-wiki](https://github.com/GD4AI/obsidian-llm-wiki) plugin is powerful, its batch ingestion is tightly coupled to Obsidian's desktop user interface. If you close Obsidian, put your computer to sleep, or take notes on mobile, background processing stops.

This companion daemon provides:
1. **Headless 24/7 Execution:** Runs as an isolated Docker container or Systemd service on your desktop, home server, NAS, or Raspberry Pi.
2. **Asynchronous & Concurrent Architecture:** Powered by `asyncio` and `AsyncOpenAI`. Includes concurrent initial scans bounded by semaphores and SQLite in WAL mode (`PRAGMA journal_mode=WAL`) for high throughput without database locks.
3. **Native Structured Outputs (Pydantic):** Uses Gemini / OpenAI native `parse` endpoints with strict Pydantic schemas. Eliminates JSON parsing errors, unescaped quotes, or LaTeX formula corruption (`\alpha`, `\int`, `\$`) at the model generation level.
4. **🔗 Reverse Auto-Linker (Magic Links):** When new concepts or entities are discovered, an asynchronous background pass scans existing vault notes and automatically injects bidirectional `[[wiki]]` links without creating infinite re-ingestion loops.
5. **100% Free-Tier Friendly:** Specifically engineered to operate reliably within Google Gemini Free Tier quotas (500 requests/day, 15 RPM) using smart proactive throttling (`REQUEST_INTERVAL=120s`) and dynamic exponential backoff.
6. **Idempotent Incremental Ingestion:** Maintains an SQLite state database (`ingestion_state.db`) tracking SHA-256 hashes for every note. Notes are only processed when their content changes; unchanged notes cost 0 tokens.
7. **Cross-Platform Docker Reliability:** Auto-detects runtime environment and falls back to `PollingObserver` on macOS/Windows Docker mounts where native `inotify` events do not propagate.
8. **🧠 Semantic Search (Vector Embeddings):** Powered by Google's `gemini-embedding-001` and stored in SQLite (no ChromaDB, no extra disk-heavy dependencies). Embeds your generated wiki notes and discovers non-obvious conceptual links, automatically injecting semantically related concepts.
9. **🏠 Plug-and-Play Local Models (Ollama / LM Studio):** Run 100% offline without API keys or costs. Seamlessly points to any OpenAI-compatible local server (`OPENAI_BASE_URL`), auto-injects dummy API keys for localhost, and features a transparent fallback from JSON Schema to standard `json_object` + Pydantic validation if the local engine does not support `beta.chat.completions.parse`.
10. **🔔 Native Desktop Notifications:** Receive instant, non-intrusive OS notifications (via `plyer`) summarizing newly extracted concepts and entities as you write. Features a resilient fallback that gracefully ignores display errors in headless or Docker environments.

---

## 🏗️ Architecture: 3-Layer System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. OBSIDIAN VAULT & COMMUNITY PLUGIN (GD4AI/obsidian-llm-wiki)              │
│    - Markdown notes in vault folders.                                       │
│    - Configuration in .obsidian/plugins/karpathywiki/data.json.             │
│    - Desktop UI: Graph View, interactive chat RAG, and wiki link linting.   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Watches note changes / Writes wiki/
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. AUTONOMOUS ASYNC INGESTION DAEMON (This service — Docker or Systemd)     │
│    - Non-blocking Python service (ingest_daemon.py) running on asyncio.     │
│    - Watchdog bridge (inotify / PollingObserver) with debouncing (20s).     │
│    - Gemini inference via native Pydantic Structured Outputs.               │
│    - Background Auto-Linker: regex pass to interconnect vault notes.        │
│    - Persistent state tracking in SQLite WAL mode (ingestion_state.db).     │
│    - Proactive throttling & rate limit protection (120s between calls).     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Telemetry & Read-only sync
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. WEB DASHBOARD & TELEMETRY (Optional)                                     │
│    - Real-time progress monitoring (OK, Pending, Errors).                   │
│    - Gemini daily quota estimation (Free Tier tracker).                     │
│    - Integrated Markdown reader (Marked.js) for concepts & entities.        │
│    - Live log stream viewer.                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Docker Compose)

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/obsidian-llm-wiki-ingesta.git
cd obsidian-llm-wiki-ingesta
```

### 2. Configure environment variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your settings:
```ini
# Get your key from https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Absolute path to your Obsidian vault on the host machine
VAULT_PATH=/home/username/Documents/ObsidianVault

# Seconds between API calls (120 for Gemini Free tier; 6 for paid)
REQUEST_INTERVAL=120

# Optional: folders to monitor (comma-separated).
# If left empty, it reads watchedFolders from data.json or watches the entire vault.
# WATCHED_FOLDERS=Notes,Journal,Articles

# Optional: scan old notes and inject wiki links when new concepts/entities are found.
# ENABLE_AUTO_LINK=true

# Optional: Generate embeddings for semantic search and append related concepts.
# ENABLE_VECTOR_SEARCH=true

# Optional: Local / Offline Models (Ollama, LMStudio, vLLM, etc.)
# OPENAI_BASE_URL=http://localhost:11434/v1
# MODEL_NAME=llama3.1:8b
# EMBEDDING_MODEL_NAME=nomic-embed-text

# Optional: Desktop system notifications when new concepts are extracted
# ENABLE_NOTIFICATIONS=true
```

### 3. Build and launch
```bash
docker compose up -d
```

### 4. Monitor live activity
```bash
# View Docker logs
docker compose logs -f

# View the vault log file directly
tail -f /path/to/your/vault/karpathy_ingest.log
```

---

## 🛠️ Configuration Reference (`.env`)

| Variable | Required | Default | Description |
|---|:---:|:---:|---|
| `GEMINI_API_KEY` | **Yes** | — | Google Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey). |
| `VAULT_PATH` | **Yes** | `/vault` | Absolute path to the Obsidian vault on the host machine. |
| `REQUEST_INTERVAL` | No | `120` | Minimum seconds between consecutive API calls. Recommended: `120` (Free tier) or `6` (Paid tier). |
| `WATCHED_FOLDERS` | No | *from plugin* | Comma-separated list of folders to watch within the vault. If unset, automatically reads `watchedFolders` from `.obsidian/plugins/karpathywiki/data.json`, or monitors the whole vault. |
| `ENABLE_AUTO_LINK` | No | `false` | Scans old notes and injects `[[wiki]]` links magically when new concepts/entities are generated. |
| `ENABLE_VECTOR_SEARCH` | No | `false` | Generates embeddings via Gemini `gemini-embedding-001` (or a local embedding model) and stores them in SQLite (`ingestion_state.db`). Automatically appends "Semantically Related Concepts" to new concepts. |
| `ENABLE_NOTIFICATIONS` | No | `false` | Sends native OS desktop notifications upon successful extraction (requires running locally, may not work in Docker). |
| `OPENAI_BASE_URL` | No | *Gemini API* | Custom base URL for OpenAI-compatible local endpoints (e.g., `http://localhost:11434/v1` for Ollama, `http://localhost:1234/v1` for LM Studio). Also accepts `LOCAL_API_BASE_URL`. When pointing to `localhost` or `127.0.0.1`, `GEMINI_API_KEY` is not required. |
| `MODEL_NAME` | No | `gemini-2.5-flash-lite` | Override LLM model name (e.g., `llama3.1:8b`, `qwen2.5:7b`, `mistral:7b`). |
| `EMBEDDING_MODEL_NAME` | No | `gemini-embedding-001` | Override embedding model name for vector search (e.g., `nomic-embed-text`, `bge-m3`, `all-minilm` for local servers). |

---

## 🔗 Auto-Linker (Reverse Magic Linking)

One of the biggest friction points in Personal Knowledge Management (PKM) is that extracting new concepts does not automatically link older notes that already mentioned them. 

The daemon features an integrated **AutoLinker** that solves this:

1. **Triggered on Knowledge Extraction:** Whenever the daemon writes new concept notes (`wiki/concepts/`) or entity notes (`wiki/entities/`), an asynchronous background task is scheduled.
2. **Markdown-Safe Regular Expressions:** Uses negative lookarounds `(?<!\[\[)(?<!\[)\b(term)\b(?!\]\])(?!\])(?!\))` and code block splitting (```) to ensure:
   - Existing wiki links (`[[...]]`) are never double-wrapped.
   - Standard markdown links and URLs (`[title](url)`) remain untouched.
   - Code blocks and inline code snippets are completely ignored.
   - Short terms (≤ 3 characters) are excluded to prevent false positives.
3. **Infinite Loop Prevention:** Modifying an old note updates its SHA-256 hash in SQLite (`ingestion_state.db`) immediately. This ensures that the newly modified note is marked as `ok` and will **not** trigger an endless ingestion loop.
4. **Non-Blocking Background Execution:** The pass runs in a separate asyncio task, so file monitoring and note ingestion proceed without interruption.

---

## 🧠 Semantic Search (Vector Embeddings)

In addition to literal keyword matching, the daemon embeds your generated wiki notes and finds semantically related concepts using Google's **`gemini-embedding-001`** model, storing the vectors in **SQLite** (the same `ingestion_state.db` the daemon already uses).

### Why we moved away from ChromaDB
The original implementation used **ChromaDB** with an HNSW index for vector search. In practice, this caused a real problem: ChromaDB depends on libraries with native extensions (`onnxruntime`, `hnswlib`) that don't ship precompiled wheels for `musl` (the C library Alpine Linux uses). On the project's Alpine-based Docker image, `pip` had to **compile those libraries from source** on every build, which exhausted several GB of disk space and made `docker compose build` fail outright.

On top of that, Google deprecated `text-embedding-004` (the model this project originally called) in January 2026, so the old implementation stopped working independently of the disk issue.

Rather than just swapping the base image, we re-evaluated whether a dedicated vector database was needed at all. For a personal Obsidian vault (hundreds to a few thousand notes), it isn't: a brute-force cosine similarity search over all stored vectors, using `numpy`, runs in a fraction of a second. So the fix removes the extra moving part entirely:

- **No ChromaDB, no native ML dependencies.** `requirements.txt` no longer needs `chromadb`; only `numpy` was added, which has lightweight precompiled wheels.
- **`gemini-embedding-001` instead of the deprecated `text-embedding-004`** — currently Google's top-ranked model on the MTEB Multilingual leaderboard, called through the same OpenAI-compatible client the project already uses for text generation.
- **Vectors live in SQLite**, not a separate embedded database — one less service, one less thing to back up or corrupt.
- **`python:3.12-slim` instead of `python:3.12-alpine`** in the `Dockerfile` (multi-stage build) — Debian-based images have precompiled wheels for virtually everything on PyPI, so `pip install` no longer compiles anything from source.

### 1. How It Works
- **Local Persistence:** Vectors are stored as BLOBs in `.obsidian/plugins/karpathywiki/ingestion_state.db`, in an `embeddings` table alongside the existing ingestion-state tracking. No external vector cloud or SaaS required — only the embedding *computation* happens online, via the Gemini API you already use for text generation.
- **Universal Knowledge Indexing:** Every generated markdown entry (`wiki/sources/`, `wiki/concepts/`, `wiki/entities/`) is embedded and stored with its `doc_type` (`concept` | `source` | `entity`).
- **Automatic Conceptual Bridges:** When a new concept note is created or updated, the daemon computes cosine similarity in-memory against every stored `concept` vector and appends the top-3 matches (`top_k=3`) at the bottom of the file:
  ```markdown
  ### 🧠 Conceptos Relacionados Semánticamente
  - [[wiki/concepts/free-energy-principle|Free Energy Principle]]
  - [[wiki/concepts/predictive-coding|Predictive Coding]]
  - [[wiki/concepts/bayesian-brain|Bayesian Brain]]
  ```
- **State Integrity & Anti-Loop:** Because the concept file is modified to include related concepts, the daemon immediately recalculates the final SHA-256 hash and updates `ingestion_state.db`, ensuring that this automated enrichment never triggers an ingestion loop.
- **Resilient Embedding Retries:** Features automatic exponential backoff retries (up to 3 attempts) for the embeddings endpoint to guarantee robust indexation.

### 2. Enabling Vector Search
Add the following variable to your `.env`:
```ini
ENABLE_VECTOR_SEARCH=true
```
No extra system dependencies required beyond what's already in `requirements.txt`.

---

## 🏠 Offline & Local Models (Ollama, LM Studio, vLLM)

You can run the ingestion daemon completely offline without relying on Google Gemini or any cloud provider. The daemon natively interfaces with any local server exposing an OpenAI-compatible API.

### 1. Quick Setup with Ollama
Pull your preferred LLM and embedding models:
```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 2. Configuration in `.env`
Set the local endpoint and model names in `.env`:
```ini
# Local OpenAI-compatible endpoint
OPENAI_BASE_URL=http://localhost:11434/v1

# Models
MODEL_NAME=llama3.1:8b
EMBEDDING_MODEL_NAME=nomic-embed-text

# No rate limiting needed for local inference
REQUEST_INTERVAL=0

# Enable vector search (vectors stored locally in SQLite either way)
ENABLE_VECTOR_SEARCH=true
```

> [!TIP]
> **No API Key Required:** When `OPENAI_BASE_URL` contains `localhost` or `127.0.0.1`, the daemon automatically injects a dummy API key (`local-dummy-key`). You do not need to set `GEMINI_API_KEY`.

### 3. Transparent JSON Fallback & Pydantic Validation
While official OpenAI/Gemini endpoints support `beta.chat.completions.parse` (strict JSON schema), many local inference servers (Ollama, LM Studio, vLLM) do not yet implement this specific beta grammar and return a `400 Bad Request`.

The daemon handles this automatically:
1. It attempts `beta.chat.completions.parse` first.
2. If the local server throws a `BadRequestError`, it seamlessly falls back to standard `chat.completions.create` with `response_format={"type": "json_object"}` and appends strict schema instructions to the prompt.
3. Automatically strips any markdown fences (````json ... ````) returned by local LLMs.
4. Validates the resulting JSON payload through `WikiResponse.model_validate_json(...)` to guarantee full schema integrity before writing to your vault.

---

## 🔔 Native Desktop Notifications

If you run the daemon natively on your desktop (Linux, macOS, or Windows via Systemd or Python), you can enable real-time OS toast notifications:

- **Smart Summaries:** Emits a notification whenever new knowledge is successfully written, e.g.:
  > **KarpathyWiki**  
  > *Extraídos 2 conceptos y 1 entidades de 'Active Inference'*
- **Non-Blocking & Asynchronous:** Dispatched asynchronously via `asyncio.to_thread` so file ingestion and watcher loops are never paused.
- **Headless & Docker Resilient:** If running inside Docker or a headless server without a desktop environment/display server, notification failures are caught and silenced safely without crashing the service.
- **How to Enable:**
  ```ini
  ENABLE_NOTIFICATIONS=true
  ```
  *(Requires `plyer>=2.1.0` in `requirements.txt`).*

---

## ⚙️ How Ingestion Works

```
Your note in Obsidian
       │
       ▼ (Watchdog inotify / PollingObserver detects file change)
  Debounce (20s — waits until you finish typing)
       │
       ▼ (SHA-256 Hash check against ingestion_state.db)
  Hash matches & status is OK? ──► Ignored (0 tokens, 0 cost)
  New note or modified?
       │
       ▼ (Throttling check — enforces REQUEST_INTERVAL)
  Calls Google Gemini API (Pydantic Structured Outputs)
       │
       ├─────────────────────────────────────────────┐
       ▼                                             ▼
  wiki/sources/   ← Note summary & metadata     [If ENABLE_AUTO_LINK=true]
  wiki/concepts/  ← Concepts, definitions & links   Auto-Linker runs in background:
  wiki/entities/  ← People, organizations & authors  Scans old notes & injects [[links]]
       │                                             Updates SHA-256 in SQLite (no loops)
       ▼ [If ENABLE_VECTOR_SEARCH=true]
  Vector Store (SQLite):
  - Generates embeddings with gemini-embedding-001
  - Injects "Semantically Related Concepts" into concept notes
  - Updates note SHA-256 hash in SQLite
```

### Safety & Vault Integrity
- **Default Mode (`ENABLE_AUTO_LINK=false`):** Purely read-only on your source notes. The daemon only creates files under `wiki/` and updates the SQLite database. It never deletes or alters your original notes.
- **Auto-Linker Mode (`ENABLE_AUTO_LINK=true`):** Safely injects wiki links (`[[wiki/...|Term]]`) into existing notes, while preserving code snippets and URLs, and tracking hashes to ensure absolute idempotence.
- **Ignored Directories:** Automatically skips `wiki/`, `.obsidian/`, `.git/`, and `.trash/`.

---

## 🖥️ Alternative: Running with Systemd (Native Linux)

If you prefer running natively on Ubuntu, Debian, or Raspberry Pi without Docker:

1. **Install dependencies in a virtual environment:**
   ```bash
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```

2. **Configure the service unit:**
   Edit `karpathy-wiki-ingest@.service` with your username and vault path.

3. **Install and enable the service:**
   ```bash
   sudo cp karpathy-wiki-ingest@.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now karpathy-wiki-ingest@$USER
   ```

4. **Check status & live logs:**
   ```bash
   systemctl status karpathy-wiki-ingest@$USER
   journalctl -u karpathy-wiki-ingest@$USER -f
   ```

---

## 📋 Docker Commands Cheat Sheet

| Action | Command |
|---|---|
| **Start** | `docker compose up -d` |
| **Stop** | `docker compose stop` |
| **Restart** | `docker compose restart` |
| **View logs** | `docker compose logs -f` |
| **Rebuild image** | `docker compose build` |
| **Destroy container** | `docker compose down` |
| **Status check** | `docker ps \| grep karpathy` |

---

## 🔍 Log Output Example

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

## 🤝 Relationship to the Obsidian Community Plugin

This project is an autonomous companion tool designed to work alongside the [Karpathy LLM Wiki Obsidian Plugin](https://github.com/GD4AI/obsidian-llm-wiki) created by `GD4AI` / `green-dalii`. Both tools adhere to the exact same folder structure (`wiki/concepts/`, `wiki/entities/`, `wiki/sources/`), allowing you to use Obsidian for visual graph exploration and RAG chat while this headless daemon handles continuous background ingestion.

---

## 🤖 AI Attribution & Disclaimer

This project was developed with the assistance of **Google Gemini** (via pair-programming with Gemini 3.8 Flash). The architecture design, code implementation of `ingest_daemon.py`, Docker configuration, error-handling mechanisms, and documentation were created under human requirements, supervision, and live vault testing.

- **Human Contribution:** Conceptual design, architectural specifications, debugging live vault ingestion bottlenecks, test validation, and prompt direction.
- **AI Contribution:** Code generation, asyncio refactoring, Pydantic structured output integration, auto-linker regex engine, systemd template, and bilingual documentation.

*Disclaimer:* While tested extensively on live vaults, always maintain backups of your Obsidian vault before deploying any automated ingestion tooling.

---

## 📄 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 Matías Diez.
