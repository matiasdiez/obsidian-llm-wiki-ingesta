# KarpathyWiki — Headless Ingestion Daemon for Obsidian

[English](README.md) | [Español](READMEes.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker: Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Built with: Gemini](https://img.shields.io/badge/Built%20with-Google%20Gemini-8E75B2.svg)](https://deepmind.google/technologies/gemini/)
[![Companion: Obsidian](https://img.shields.io/badge/Obsidian-Plugin%20Companion-7C3AED.svg)](https://obsidian.md/)

An autonomous, lightweight background daemon that automatically generates structured wiki entries (`wiki/concepts/`, `wiki/entities/`, `wiki/sources/`) in your Obsidian vault using the [Karpathy LLM Wiki](https://github.com/GD4AI/obsidian-llm-wiki) methodology and Google Gemini.

It runs continuously 24/7 in the background (via Docker or Systemd), detecting note creation and edits in real time without requiring the Obsidian desktop app to remain open.

---

## 💡 Why This Project?

While the official [obsidian-llm-wiki](https://github.com/GD4AI/obsidian-llm-wiki) plugin is powerful, its batch ingestion is tightly coupled to Obsidian's desktop user interface. If you close Obsidian, put your computer to sleep, or take notes on mobile, background processing stops.

This companion daemon provides:
1. **Headless 24/7 Execution:** Runs as an isolated Docker container or Systemd service on your desktop, home server, NAS, or Raspberry Pi.
2. **100% Free-Tier Friendly:** Specifically engineered to operate reliably within the Google Gemini Free Tier (500 requests/day, 15 RPM) using smart throttling (`REQUEST_INTERVAL=120s`) and dynamic exponential backoff on API rate limits.
3. **Idempotent Incremental Ingestion:** Maintains an SQLite state database (`ingestion_state.db`) tracking SHA-256 hashes for every note. Notes are only processed when modified; unchanged notes cost 0 tokens.
4. **Resilient JSON & Error Recovery:** Includes a self-repairing JSON parser that tolerates LaTeX formulas (`\alpha`, `\int`, `\$`), regex escapes, and unescaped quotes returned by LLMs. Automatically retries transient network errors and server overloads (503/500).
5. **Zero Vault Clutter:** Does not alter your source notes; only writes generated summaries and concepts to your `wiki/` directory.

---

## 🏗️ Architecture: 3-Layer System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. OBSIDIAN VAULT & COMMUNITY PLUGIN (GD4AI/obsidian-llm-wiki)              │
│    - Markdown notes in vault folder.                                        │
│    - Configuration in .obsidian/plugins/karpathywiki/data.json.             │
│    - Desktop UI: Graph View, interactive chat RAG, and wiki link linting.   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Watches note changes / Writes wiki/
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. AUTONOMOUS INGESTION DAEMON (This service — Docker or Systemd)           │
│    - Headless Python service (ingest_daemon.py) monitoring via inotify.     │
│    - Configurable debounce (20s) to wait until you finish writing.          │
│    - Gemini API inference with strict JSON schema and escape auto-repair.   │
│    - Persistent state tracking in SQLite (ingestion_state.db).              │
│    - Throttling & rate limit protection (120s between calls).               │
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
| `GEMINI_API_KEY` | **Yes** | — | Google Gemini API key from Google AI Studio. |
| `VAULT_PATH` | **Yes** | `/vault` | Absolute path to the Obsidian vault on the host machine. |
| `REQUEST_INTERVAL` | No | `120` | Minimum seconds between consecutive API calls. Recommended: `120` (Free tier) or `6` (Paid tier). |
| `WATCHED_FOLDERS` | No | *from plugin* | Comma-separated list of folders to watch within the vault. If unset, automatically reads `watchedFolders` from `.obsidian/plugins/karpathywiki/data.json`, or monitors the whole vault. |

---

## 🖥️ Alternative: Running with Systemd (No Docker)

If you prefer running natively on a Linux machine or Raspberry Pi:

1. **Install Python dependencies in a virtual environment:**
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

4. **Check status:**
   ```bash
   systemctl status karpathy-wiki-ingest@$USER
   journalctl -u karpathy-wiki-ingest@$USER -f
   ```

---

## ⚙️ How Ingestion Works

```
Your note in Obsidian
       │
       ▼ (Watchdog inotify detects file change)
  Debounce (20s — waits until you finish typing)
       │
       ▼ (SHA-256 Hash check against ingestion_state.db)
  Hash matches & status is OK? ──► Ignored (0 tokens, 0 cost)
  New note or modified?
       │
       ▼ (Throttling check — enforces REQUEST_INTERVAL)
  Calls Google Gemini API (Structured JSON)
       │
       ▼
  wiki/sources/   ← Note summary & metadata
  wiki/concepts/  ← Core concepts, definitions & interlinks
  wiki/entities/  ← People, organizations, authors mentioned
```

- **Safety:** The daemon **only reads** source notes. It **never deletes or modifies** your original files. It only writes generated files under `wiki/` and updates the SQLite state database.
- **Ignored Directories:** Automatically ignores `wiki/`, `.obsidian/`, `.git/`, and `.trash/`.

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

## 🤝 Relationship to the Obsidian Community Plugin

This project is a standalone, companion tool designed to work alongside the [Karpathy LLM Wiki Obsidian Plugin](https://github.com/GD4AI/obsidian-llm-wiki) created by `GD4AI` / `green-dalii`. Both tools operate on the same folder conventions (`wiki/concepts/`, `wiki/entities/`, `wiki/sources/`), allowing you to use Obsidian for querying and graph visualization while this daemon handles continuous background ingestion.

---

## 🤖 AI Attribution & Disclaimer

This project was developed with the assistance of **Google Gemini** (via pair-programming with Gemini 3.8 Flash). The architecture design, code implementation of `ingest_daemon.py`, Docker configuration, error-handling mechanisms, and documentation were generated by the AI model under human requirements, supervision, and live vault testing.

- **Human Contribution:** Conceptual design, architecture requirements, debugging live vault ingestion bottlenecks, test validation, and prompt direction.
- **AI Contribution:** Code generation, resilient JSON parsing logic, retry handlers, systemd template, and bilingual documentation.

*Disclaimer:* While tested extensively on live vaults, always maintain backups of your Obsidian vault before deploying any automated ingestion tooling.

---

## 📄 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 Matías Diez.
