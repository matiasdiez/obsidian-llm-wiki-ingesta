#!/usr/bin/env python3
"""
ingest_daemon.py — KarpathyWiki Obsidian Ingestion Daemon
==========================================================
Watches Obsidian vault folders and automatically generates wiki entries
(sources, concepts, entities) using the Gemini LLM API when notes are
created or modified.

Usage:
    python ingest_daemon.py /path/to/obsidian/vault

Environment:
    GEMINI_API_KEY   — Gemini API key (overrides .env and data.json)

Author: Antigravity (AI Assistant)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Third-party imports (graceful error if not installed)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("❌  Missing dependency: run  pip install python-dotenv")

try:
    from openai import OpenAI, RateLimitError, APIStatusError, APIConnectionError
except ImportError:
    sys.exit("❌  Missing dependency: run  pip install openai")

try:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers import Observer
except ImportError:
    sys.exit("❌  Missing dependency: run  pip install watchdog")


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
LOG_DATE   = "%Y-%m-%d %H:%M:%S"

def setup_logging(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("karpathy_ingest")
    logger.setLevel(logging.DEBUG)

    # Console handler (INFO+)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
    logger.addHandler(ch)

    # File handler (DEBUG+)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# Configuration Loader
# ---------------------------------------------------------------------------
class Config:
    """Loads and validates plugin configuration from data.json + environment."""

    PLUGIN_DATA_REL = ".obsidian/plugins/karpathywiki/data.json"
    FALLBACK_PLUGIN_IDS = ["karpathywiki", "karpathy-wiki", "obsidian-llm-wiki"]

    def __init__(self, vault_path: Path, logger: logging.Logger) -> None:
        self.vault      = vault_path.resolve()
        self.logger     = logger
        self._raw: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    def _find_data_json(self) -> Path | None:
        """Search for data.json across known plugin folder name variants."""
        for plugin_id in self.FALLBACK_PLUGIN_IDS:
            candidate = self.vault / ".obsidian" / "plugins" / plugin_id / "data.json"
            if candidate.exists():
                return candidate
        return None

    def _load(self) -> None:
        data_path = self._find_data_json()
        if data_path:
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    self._raw = json.load(f)
                self.logger.info("Loaded plugin config from: %s", data_path)
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warning("Cannot read data.json (%s). Using defaults.", exc)
        else:
            self.logger.warning(
                "data.json not found in known plugin folders. Using defaults."
            )

        # Load .env from vault root (if present)
        env_file = self.vault / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file)
            self.logger.debug("Loaded .env from %s", env_file)
        else:
            load_dotenv()

    # ------------------------------------------------------------------
    # Accessors — provide defaults that match the user specification
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._raw.get(
            "baseUrl",
            "https://generativelanguage.googleapis.com/v1beta/openai"
        )

    @property
    def model(self) -> str:
        return self._raw.get("model", "gemini-2.5-flash-lite")

    @property
    def wiki_folder(self) -> str:
        return self._raw.get("wikiFolder", "wiki")

    @property
    def watched_folders(self) -> list[str]:
        # Priority:
        # 1. Environment variable WATCHED_FOLDERS (comma-separated list, e.g. "Notes,Journal,Articles")
        # 2. Plugin data.json watchedFolders list
        # 3. Whole vault root ("")
        env_watched = os.environ.get("WATCHED_FOLDERS")
        if env_watched:
            raw = [f.strip() for f in env_watched.split(",") if f.strip()]
        else:
            raw = self._raw.get("watchedFolders", [])

        if not raw:
            return [""]

        # Ensure each folder ends with /
        return [f if f.endswith("/") else f + "/" for f in raw]

    @property
    def language(self) -> str:
        lang = self._raw.get("wikiLanguage") or self._raw.get("language", "es")
        return lang

    @property
    def api_key(self) -> str:
        # Priority: env var > .env > data.json
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            key = self._raw.get("apiKey", "")
        if not key:
            raise RuntimeError(
                "No API key found. Set the GEMINI_API_KEY environment variable "
                "or add it to your vault's .env file."
            )
        return key

    @property
    def debounce_seconds(self) -> int:
        return int(self._raw.get("debounceSeconds", 20))

    @property
    def request_interval_seconds(self) -> float:
        """Minimum wait time (seconds) between consecutive LLM API calls.
        Set to 0 to disable throttling (rely only on exponential backoff).
        Recommended: 60 for Gemini Free tier (1 RPM), 6 for paid (10 RPM).
        """
        return float(self._raw.get("requestIntervalSeconds", 0))

    @property
    def wiki_concepts_dir(self) -> Path:
        return self.vault / self.wiki_folder / "concepts"

    @property
    def wiki_entities_dir(self) -> Path:
        return self.vault / self.wiki_folder / "entities"

    @property
    def wiki_sources_dir(self) -> Path:
        return self.vault / self.wiki_folder / "sources"

    @property
    def db_path(self) -> Path:
        return self.vault / ".obsidian" / "plugins" / "karpathywiki" / "ingestion_state.db"

    @property
    def log_path(self) -> Path:
        return self.vault / "karpathy_ingest.log"

    @property
    def ignore_dirs(self) -> list[str]:
        """Absolute path prefixes that should always be skipped."""
        wiki_abs = str(self.vault / self.wiki_folder)
        return [
            wiki_abs,
            str(self.vault / ".obsidian"),
            str(self.vault / ".git"),
            str(self.vault / ".trash"),
        ]


# ---------------------------------------------------------------------------
# State Database (SQLite)
# ---------------------------------------------------------------------------
class IngestionStateDB:
    """
    Tracks SHA-256 hashes of processed files to avoid redundant LLM calls.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS ingestion_state (
        file_path              TEXT PRIMARY KEY,
        sha256_hash            TEXT NOT NULL,
        last_processed_at      TEXT NOT NULL,
        status                 TEXT NOT NULL DEFAULT 'ok'
    );
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(self.DDL)
        self._conn.commit()

    def get_hash(self, file_path: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT sha256_hash FROM ingestion_state WHERE file_path = ?",
                (file_path,),
            ).fetchone()
        return row[0] if row else None

    def get_record(self, file_path: str) -> tuple[str, str] | None:
        """Returns (sha256_hash, status) or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT sha256_hash, status FROM ingestion_state WHERE file_path = ?",
                (file_path,),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def upsert(self, file_path: str, sha256_hash: str, status: str = "ok") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO ingestion_state (file_path, sha256_hash, last_processed_at, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    sha256_hash         = excluded.sha256_hash,
                    last_processed_at   = excluded.last_processed_at,
                    status              = excluded.status
                """,
                (file_path, sha256_hash, now, status),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Slug / File Name Utilities
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    """Convert a string to a URL-safe slug (ASCII, lowercase, hyphens)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def safe_parse_json(raw: str, logger: logging.Logger | None = None) -> dict[str, Any]:
    """
    Robustly parses JSON returned by LLM, tolerating markdown fences,
    unescaped control characters, and invalid backslash escapes (e.g. LaTeX, regex).
    """
    cleaned = raw.strip()

    # 1. Strip markdown fences ```json ... ``` if present
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # 2. Extract outermost { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        cleaned = cleaned[start:end]

    # 3. Direct attempt with strict=False (allows unescaped newlines/tabs inside strings)
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError as err:
        if logger:
            logger.debug("Initial JSON decode failed: %s. Attempting escape repair…", err)

    # 4. Repair invalid backslash escapes (e.g. \alpha, \m, \ , \$ -> \\alpha, \\m, etc.)
    # In JSON, valid escapes are: \", \\, \/, \b, \f, \n, \r, \t, and \uXXXX.
    repaired = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', cleaned)
    try:
        return json.loads(repaired, strict=False)
    except json.JSONDecodeError as err2:
        if logger:
            logger.debug("Escape-repaired JSON decode failed: %s. Attempting control-char purge…", err2)

    # 5. Clean invalid ASCII control characters (< 0x20 except \t, \n, \r)
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', repaired)
    return json.loads(sanitized, strict=False)


# ---------------------------------------------------------------------------
# LLM Client & Prompting
# ---------------------------------------------------------------------------
class WikiGenerator:
    """
    Wraps the OpenAI-compatible Gemini client and handles all LLM interactions.
    """

    MAX_RETRIES   = 5
    BACKOFF_BASE  = 2.0   # seconds — exponential backoff base

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        # Rate limiter state — enforces minimum gap between API calls
        self._rate_lock      = threading.Lock()
        self._last_call_time = 0.0   # monotonic timestamp of last successful call

    # ------------------------------------------------------------------
    def _wait_for_rate_limit(self) -> None:
        """Block until the configured minimum interval since the last call has elapsed."""
        interval = self.config.request_interval_seconds
        if interval <= 0:
            return
        with self._rate_lock:
            now     = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < interval:
                wait = interval - elapsed
                self.logger.info(
                    "⏳ Rate limiter: waiting %.1fs before next API call…", wait
                )
                time.sleep(wait)
            self._last_call_time = time.monotonic()

    # ------------------------------------------------------------------
    def _parse_retry_delay(self, exc: Exception, attempt: int) -> float:
        """
        Extract the retryDelay value that Gemini returns in the 429 error body.
        Falls back to exponential backoff if the field cannot be parsed.

        Gemini error body structure:
            [{'error': {'details': [
                {'@type': '…RetryInfo', 'retryDelay': '26s'}
            ]}}]
        """
        fallback = self.BACKOFF_BASE ** attempt
        try:
            body = getattr(exc, "body", None)
            if isinstance(body, list) and body:
                details = body[0].get("error", {}).get("details", [])
            elif isinstance(body, dict):
                details = body.get("error", {}).get("details", [])
            else:
                return fallback
            for detail in details:
                if "RetryInfo" in detail.get("@type", ""):
                    delay_str = detail.get("retryDelay", "")
                    # Format: "26s" or "26.291s"
                    seconds = float(delay_str.rstrip("s"))
                    # Use the API's suggestion, but never less than our fallback
                    return max(seconds, fallback)
        except Exception:
            pass
        return fallback

    # ------------------------------------------------------------------
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM with proactive throttling + API-aware backoff on rate limits."""
        self._wait_for_rate_limit()
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self.config.model,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                )
                return response.choices[0].message.content or ""
            except (RateLimitError, APIStatusError, APIConnectionError) as exc:
                is_429 = (
                    isinstance(exc, RateLimitError)
                    or (isinstance(exc, APIStatusError) and exc.status_code == 429)
                )
                if is_429:
                    wait = self._parse_retry_delay(exc, attempt)
                    self.logger.warning(
                        "⏳ Rate limit hit (attempt %d/%d). Waiting %.0fs as requested by API…",
                        attempt + 1, self.MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue

                # Temporary server errors (500, 502, 503, 504)
                if isinstance(exc, APIStatusError) and exc.status_code in (500, 502, 503, 504):
                    wait = min(60.0, 5.0 * (2 ** attempt))
                    self.logger.warning(
                        "⚠️ Server error %s (attempt %d/%d). Retrying in %.0fs…",
                        exc.status_code, attempt + 1, self.MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue

                # Network / connection drop
                if isinstance(exc, APIConnectionError):
                    wait = min(30.0, 3.0 * (2 ** attempt))
                    self.logger.warning(
                        "⚠️ Connection error (attempt %d/%d): %s. Retrying in %.0fs…",
                        attempt + 1, self.MAX_RETRIES, exc, wait,
                    )
                    time.sleep(wait)
                    continue

                raise

        raise RuntimeError(
            f"LLM call failed after {self.MAX_RETRIES} attempts (persistent rate limit or server error)."
        )

    # ------------------------------------------------------------------
    def _system_prompt(self) -> str:
        lang_name = {
            "es": "Spanish", "en": "English", "fr": "French",
            "de": "German",  "pt": "Portuguese",
        }.get(self.config.language, self.config.language)

        return (
            f"You are a knowledge-base assistant that processes Obsidian notes "
            f"and generates structured wiki entries in {lang_name}. "
            "You write in Markdown with YAML frontmatter. "
            "You use Obsidian internal link syntax: [[path/to/note|Display Name]]. "
            "Be concise, precise, and academically rigorous. "
            "Never invent sources or facts not present in the note."
        )

    # ------------------------------------------------------------------
    def generate_wiki_entries(
        self, note_path: Path, content: str
    ) -> dict[str, dict[str, str]]:
        """
        Ask the LLM to produce the three wiki outputs as JSON.

        Returns a dict with keys: "source", "concepts", "entities"
        Each value is a dict mapping  filename -> markdown_content.
        """
        note_title   = note_path.stem
        wiki_folder  = self.config.wiki_folder
        lang         = self.config.language

        user_prompt = f"""
Analyze the following Obsidian note and produce JSON output with the following structure.
Do NOT include any text outside the JSON block.

Note title: "{note_title}"
Note path: "{note_path}"
Wiki folder: "{wiki_folder}"
Language code: "{lang}"

```json
{{
  "source": {{
    "filename": "<slug>_<4-char-hex-id>.md",
    "content": "<full markdown with YAML frontmatter>"
  }},
  "concepts": [
    {{
      "filename": "<concept-slug>.md",
      "content": "<full markdown with YAML frontmatter>"
    }}
  ],
  "entities": [
    {{
      "filename": "<entity-slug>.md",
      "content": "<full markdown with YAML frontmatter>"
    }}
  ]
}}
```

### Rules:
1. **source** — Create exactly one source note summarising the note's key points.
   - filename pattern: `[note-title-slug]_[4 hex chars].md`
   - YAML frontmatter: type, tags, updated_at (ISO8601), source_note
   - Body: 3–7 bullet point summary of key ideas.
   - Link every concept/entity mentioned using Obsidian syntax:
     [[{wiki_folder}/concepts/concept-slug|Concept Name]]
     [[{wiki_folder}/entities/entity-slug|Entity Name]]

2. **concepts** — 1–5 abstract/technical concepts found in the note.
   - One markdown file per concept.
   - YAML frontmatter: type: concept, tags, updated_at, sources (list of source slugs)
   - Body: brief definition + explanation in context of the note.
   - Use inter-links between concepts and entities.

3. **entities** — 0–5 people, authors, or organisations mentioned.
   - One markdown file per entity.
   - YAML frontmatter: type: entity, tags, updated_at, sources
   - Body: who/what they are + their relevance to the note content.
   - If no entities found, return an empty list [].

### Note content to analyse:
---
{content}
---
"""

        raw = self._call_llm(self._system_prompt(), user_prompt)
        try:
            return safe_parse_json(raw, self.logger)
        except json.JSONDecodeError as exc:
            self.logger.error(
                "LLM returned invalid JSON. Raw output:\n%s\nError: %s", raw[:500], exc
            )
            raise


# ---------------------------------------------------------------------------
# Wiki File Writer
# ---------------------------------------------------------------------------
class WikiWriter:
    """Writes generated wiki entries to the correct vault sub-folders."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        for d in (
            config.wiki_concepts_dir,
            config.wiki_entities_dir,
            config.wiki_sources_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def write(self, entries: dict[str, Any]) -> list[Path]:
        """Write all entries to disk. Returns list of written Paths."""
        written: list[Path] = []

        # --- source ---
        source_data = entries.get("source")
        if source_data and isinstance(source_data, dict):
            p = self._write_single(self.config.wiki_sources_dir, source_data)
            if p:
                written.append(p)

        # --- concepts ---
        for concept in entries.get("concepts", []):
            p = self._write_single(self.config.wiki_concepts_dir, concept)
            if p:
                written.append(p)

        # --- entities ---
        for entity in entries.get("entities", []):
            p = self._write_single(self.config.wiki_entities_dir, entity)
            if p:
                written.append(p)

        return written

    def _write_single(self, folder: Path, data: dict[str, str]) -> Path | None:
        filename = data.get("filename", "").strip()
        content  = data.get("content", "").strip()
        if not filename or not content:
            self.logger.debug("Skipping entry with missing filename or content.")
            return None

        # Safety: sanitise filename
        filename = re.sub(r"[^\w\s\-.]", "", filename)
        if not filename.endswith(".md"):
            filename += ".md"

        target = folder / filename
        target.write_text(content, encoding="utf-8")
        self.logger.info("  ✅ Written: %s", target.relative_to(self.config.vault))
        return target


# ---------------------------------------------------------------------------
# Ingestion Pipeline (orchestrates LLM + writer + state DB)
# ---------------------------------------------------------------------------
class IngestionPipeline:

    def __init__(
        self,
        config:    Config,
        db:        IngestionStateDB,
        generator: WikiGenerator,
        writer:    WikiWriter,
        logger:    logging.Logger,
    ) -> None:
        self.config    = config
        self.db        = db
        self.generator = generator
        self.writer    = writer
        self.logger    = logger

    def process(self, file_path: Path) -> None:
        rel = str(file_path.relative_to(self.config.vault))
        self.logger.info("📝 Processing note: %s", rel)

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.error("Cannot read %s: %s", rel, exc)
            return

        # Skip very short / empty notes
        if len(content.strip()) < 30:
            self.logger.info("  ⏭  Skipping (content too short): %s", rel)
            return

        # Hash check — skip if unchanged AND previous status was ok
        current_hash = sha256_of_file(file_path)
        record = self.db.get_record(rel)
        if record:
            stored_hash, stored_status = record
            if stored_hash == current_hash and stored_status == "ok":
                self.logger.info("  ⏭  No change detected (hash match & status ok). Skipping.")
                return

        # Run LLM
        try:
            entries = self.generator.generate_wiki_entries(file_path, content)
        except Exception as exc:
            self.logger.error("LLM error for %s: %s", rel, exc)
            self.db.upsert(rel, current_hash, status="error")
            return

        # Write outputs
        written = self.writer.write(entries)
        self.logger.info(
            "  ✅ Generated %d wiki file(s) from: %s", len(written), rel
        )

        # Update state
        self.db.upsert(rel, current_hash, status="ok")


# ---------------------------------------------------------------------------
# File System Watcher (Watchdog)
# ---------------------------------------------------------------------------
class MarkdownEventHandler(FileSystemEventHandler):
    """
    Handles file creation/modification events with debouncing.
    Only processes .md files inside watched_folders, ignoring ignored dirs.
    """

    def __init__(
        self,
        config:   Config,
        pipeline: IngestionPipeline,
        logger:   logging.Logger,
    ) -> None:
        super().__init__()
        self.config   = config
        self.pipeline = pipeline
        self.logger   = logger
        self._timers: dict[str, threading.Timer] = {}
        self._lock    = threading.Lock()

    # ------------------------------------------------------------------
    def _is_watched(self, path: str) -> bool:
        """Return True if path is inside a watched folder and not ignored."""
        abs_path = os.path.abspath(path)

        # Check ignored dirs
        for ignored in self.config.ignore_dirs:
            if abs_path.startswith(ignored):
                return False

        # Check watched folders
        vault = str(self.config.vault)
        for folder in self.config.watched_folders:
            watch_abs = os.path.join(vault, folder)
            if abs_path.startswith(watch_abs):
                return True

        return False

    # ------------------------------------------------------------------
    def _schedule(self, path: str) -> None:
        """Schedule a debounced processing call."""
        with self._lock:
            # Cancel pending timer for this file
            if path in self._timers:
                self._timers[path].cancel()

            delay = self.config.debounce_seconds
            timer = threading.Timer(
                delay,
                self._run_pipeline,
                args=(path,),
            )
            self._timers[path] = timer
            timer.start()
            self.logger.debug(
                "Debounce scheduled for %s (%.0fs)", os.path.basename(path), delay
            )

    def _run_pipeline(self, path: str) -> None:
        with self._lock:
            self._timers.pop(path, None)
        p = Path(path)
        if p.exists() and p.is_file():
            self.pipeline.process(p)

    # ------------------------------------------------------------------
    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and event.src_path.endswith(".md"):
            if self._is_watched(event.src_path):
                self.logger.debug("FILE CREATED: %s", event.src_path)
                self._schedule(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and event.src_path.endswith(".md"):
            if self._is_watched(event.src_path):
                self.logger.debug("FILE MODIFIED: %s", event.src_path)
                self._schedule(event.src_path)


# ---------------------------------------------------------------------------
# Initial Vault Scan (process existing unprocessed notes on startup)
# ---------------------------------------------------------------------------
def initial_scan(config: Config, pipeline: IngestionPipeline, logger: logging.Logger) -> None:
    """
    Scan all watched folders for .md files not yet in the DB (or changed).
    This catches notes created while the daemon was offline.
    """
    logger.info("🔍 Running initial vault scan…")
    found = 0
    for folder in config.watched_folders:
        watch_dir = config.vault / folder
        if not watch_dir.exists():
            logger.debug("Watched folder not found, skipping: %s", folder)
            continue
        for md_file in watch_dir.rglob("*.md"):
            rel  = str(md_file.relative_to(config.vault))
            # Skip files inside ignored dirs
            abs_path = str(md_file.resolve())
            ignored  = any(abs_path.startswith(d) for d in config.ignore_dirs)
            if ignored:
                continue
            current_hash = sha256_of_file(md_file)
            record = pipeline.db.get_record(rel)
            if record:
                stored_hash, stored_status = record
                if stored_hash == current_hash and stored_status == "ok":
                    continue
            found += 1
            pipeline.process(md_file)
    logger.info("🔍 Initial scan complete — processed %d note(s).", found)


# ---------------------------------------------------------------------------
# Signal Handler & Graceful Shutdown
# ---------------------------------------------------------------------------
def make_signal_handler(observer: Observer, db: IngestionStateDB, logger: logging.Logger):
    def _handler(sig, frame):
        logger.info("⛔ Received signal %s. Shutting down gracefully…", sig)
        observer.stop()
        db.close()
        sys.exit(0)
    return _handler


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KarpathyWiki Obsidian Ingestion Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_daemon.py ~/Documents/MyVault
  GEMINI_API_KEY=key python ingest_daemon.py ~/Documents/MyVault --debounce 30
  python ingest_daemon.py ~/Documents/MyVault --no-initial-scan
        """,
    )
    parser.add_argument(
        "vault",
        type=Path,
        help="Absolute or relative path to your Obsidian vault root.",
    )
    parser.add_argument(
        "--debounce",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Override debounce delay in seconds (default: from data.json or 20).",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Minimum seconds between consecutive Gemini API calls (proactive throttle). "
            "Use 60 for Free tier (1 RPM), 6 for paid tier (10 RPM). "
            "Default: 0 (disabled, rely on exponential backoff only)."
        ),
    )
    parser.add_argument(
        "--no-initial-scan",
        action="store_true",
        default=False,
        help="Skip scanning existing notes on startup.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log verbosity (default: INFO).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    vault_path = args.vault.expanduser().resolve()
    if not vault_path.exists():
        sys.exit(f"❌  Vault path does not exist: {vault_path}")
    if not vault_path.is_dir():
        sys.exit(f"❌  Vault path is not a directory: {vault_path}")

    # --- Config ---
    # Temporary logger for bootstrapping
    boot_logger = logging.getLogger("karpathy_ingest.boot")
    boot_logger.addHandler(logging.StreamHandler(sys.stdout))
    boot_logger.setLevel(logging.INFO)

    config = Config(vault_path, boot_logger)

    # --- Real logger (with file handler) ---
    logger = setup_logging(config.log_path)
    if args.log_level:
        logger.handlers[0].setLevel(getattr(logging, args.log_level))

    if args.debounce is not None:
        config._raw["debounceSeconds"] = args.debounce
    if args.request_interval is not None:
        config._raw["requestIntervalSeconds"] = args.request_interval

    # Ensure wiki output dirs exist
    for d in (config.wiki_sources_dir, config.wiki_concepts_dir, config.wiki_entities_dir):
        d.mkdir(parents=True, exist_ok=True)

    # --- Component wiring ---
    db        = IngestionStateDB(config.db_path)
    generator = WikiGenerator(config, logger)
    writer    = WikiWriter(config, logger)
    pipeline  = IngestionPipeline(config, db, generator, writer, logger)
    handler   = MarkdownEventHandler(config, pipeline, logger)

    # --- Watchdog Observer ---
    observer = Observer()
    observer.schedule(handler, str(vault_path), recursive=True)
    observer.start()

    # --- Signals ---
    signal.signal(signal.SIGINT,  make_signal_handler(observer, db, logger))
    signal.signal(signal.SIGTERM, make_signal_handler(observer, db, logger))

    logger.info("=" * 60)
    logger.info("🚀 KarpathyWiki Ingest Daemon started")
    logger.info("   Vault    : %s", vault_path)
    logger.info("   Model    : %s", config.model)
    logger.info("   Debounce : %ds", config.debounce_seconds)
    if config.request_interval_seconds > 0:
        logger.info("   Throttle : %.0fs between API calls", config.request_interval_seconds)
    else:
        logger.info("   Throttle : disabled (exponential backoff only)")
    logger.info("   Watching : %s", ", ".join(config.watched_folders))
    logger.info("   Log file : %s", config.log_path)
    logger.info("=" * 60)

    # --- Optional initial scan ---
    if not args.no_initial_scan:
        initial_scan(config, pipeline, logger)

    # --- Main loop ---
    try:
        while observer.is_alive():
            observer.join(timeout=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        db.close()
        logger.info("👋 Daemon stopped.")


if __name__ == "__main__":
    main()
