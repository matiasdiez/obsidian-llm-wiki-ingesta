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
import asyncio
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
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Third-party imports (graceful error if not installed)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("❌  Missing dependency: run  pip install python-dotenv")

try:
    from openai import AsyncOpenAI, RateLimitError, APIStatusError, APIConnectionError
    from pydantic import BaseModel, Field
except ImportError:
    sys.exit("❌  Missing dependency: run  pip install openai pydantic")

try:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers import Observer
    from watchdog.observers.polling import PollingObserver
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

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
    logger.addHandler(fh)

    return logger

# ---------------------------------------------------------------------------
# Configuration Loader
# ---------------------------------------------------------------------------
class Config:
    PLUGIN_DATA_REL = ".obsidian/plugins/karpathywiki/data.json"
    FALLBACK_PLUGIN_IDS = ["karpathywiki", "karpathy-wiki", "obsidian-llm-wiki"]

    def __init__(self, vault_path: Path, logger: logging.Logger) -> None:
        self.vault      = vault_path.resolve()
        self.logger     = logger
        self._raw: dict[str, Any] = {}
        self._load()

    def _find_data_json(self) -> Path | None:
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
            self.logger.warning("data.json not found in known plugin folders. Using defaults.")

        env_file = self.vault / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file)
            self.logger.debug("Loaded .env from %s", env_file)
        else:
            load_dotenv()

    @property
    def base_url(self) -> str:
        return self._raw.get("baseUrl", "https://generativelanguage.googleapis.com/v1beta/openai")

    @property
    def model(self) -> str:
        return self._raw.get("model", "gemini-2.5-flash-lite")

    @property
    def wiki_folder(self) -> str:
        return self._raw.get("wikiFolder", "wiki")

    @property
    def watched_folders(self) -> list[str]:
        env_watched = os.environ.get("WATCHED_FOLDERS")
        if env_watched:
            raw = [f.strip() for f in env_watched.split(",") if f.strip()]
        else:
            raw = self._raw.get("watchedFolders", [])

        if not raw:
            return [""]
        return [f if f.endswith("/") else f + "/" for f in raw]

    @property
    def language(self) -> str:
        return self._raw.get("wikiLanguage") or self._raw.get("language", "es")

    @property
    def api_key(self) -> str:
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
    def auto_link_enabled(self) -> bool:
        env_val = os.environ.get("ENABLE_AUTO_LINK", "").lower()
        if env_val in ("true", "1", "yes"):
            return True
        return self._raw.get("enableAutoLink", False)

    @property
    def ignore_dirs(self) -> list[str]:
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
        
        # Optimize SQLite for concurrent access
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        
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
# Utilities
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
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

# ---------------------------------------------------------------------------
# Structured Output Models (Pydantic)
# ---------------------------------------------------------------------------
class WikiFile(BaseModel):
    filename: str = Field(description="The markdown filename, including .md extension. E.g., 'concept-slug.md'")
    content: str = Field(description="The full markdown content including YAML frontmatter")

class WikiResponse(BaseModel):
    source: Optional[WikiFile] = Field(None, description="Exactly one source note summarising the note's key points.")
    concepts: list[WikiFile] = Field(default_factory=list, description="1 to 5 abstract/technical concepts found in the note.")
    entities: list[WikiFile] = Field(default_factory=list, description="0 to 5 people, authors, or organisations mentioned.")

# ---------------------------------------------------------------------------
# LLM Client & Prompting
# ---------------------------------------------------------------------------
class WikiGenerator:
    MAX_RETRIES   = 5
    BACKOFF_BASE  = 2.0

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._rate_lock      = asyncio.Lock()
        self._last_call_time = 0.0

    async def _wait_for_rate_limit(self) -> None:
        interval = self.config.request_interval_seconds
        if interval <= 0:
            return
        async with self._rate_lock:
            now     = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < interval:
                wait = interval - elapsed
                self.logger.info("⏳ Rate limiter: waiting %.1fs before next API call…", wait)
                await asyncio.sleep(wait)
            self._last_call_time = time.monotonic()

    def _parse_retry_delay(self, exc: Exception, attempt: int) -> float:
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
                    seconds = float(delay_str.rstrip("s"))
                    return max(seconds, fallback)
        except Exception:
            pass
        return fallback

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> WikiResponse:
        await self._wait_for_rate_limit()
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Using the beta parse helper which leverages JSON Schema under the hood
                response = await self._client.beta.chat.completions.parse(
                    model=self.config.model,
                    temperature=0.2,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    response_format=WikiResponse,
                )
                
                # The response is guaranteed to match the Pydantic model
                if response.choices[0].message.parsed:
                    return response.choices[0].message.parsed
                else:
                    raise RuntimeError("LLM returned an empty parsed response.")

            except (RateLimitError, APIStatusError, APIConnectionError) as exc:
                is_429 = (isinstance(exc, RateLimitError) or 
                          (isinstance(exc, APIStatusError) and exc.status_code == 429))
                if is_429:
                    wait = self._parse_retry_delay(exc, attempt)
                    self.logger.warning("⏳ Rate limit hit (attempt %d/%d). Waiting %.0fs as requested by API…",
                                        attempt + 1, self.MAX_RETRIES, wait)
                    await asyncio.sleep(wait)
                    continue

                if isinstance(exc, APIStatusError) and exc.status_code in (500, 502, 503, 504):
                    wait = min(60.0, 5.0 * (2 ** attempt))
                    self.logger.warning("⚠️ Server error %s (attempt %d/%d). Retrying in %.0fs…",
                                        exc.status_code, attempt + 1, self.MAX_RETRIES, wait)
                    await asyncio.sleep(wait)
                    continue

                if isinstance(exc, APIConnectionError):
                    wait = min(30.0, 3.0 * (2 ** attempt))
                    self.logger.warning("⚠️ Connection error (attempt %d/%d): %s. Retrying in %.0fs…",
                                        attempt + 1, self.MAX_RETRIES, exc, wait)
                    await asyncio.sleep(wait)
                    continue

                raise

        raise RuntimeError(f"LLM call failed after {self.MAX_RETRIES} attempts.")

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

    async def generate_wiki_entries(self, note_path: Path, content: str) -> WikiResponse:
        note_title   = note_path.stem
        wiki_folder  = self.config.wiki_folder
        lang         = self.config.language

        user_prompt = f"""
Analyze the following Obsidian note and produce a structured wiki output.

Note title: "{note_title}"
Note path: "{note_path}"
Wiki folder: "{wiki_folder}"
Language code: "{lang}"

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

### Note content to analyse:
---
{content}
---
"""
        return await self._call_llm(self._system_prompt(), user_prompt)

# ---------------------------------------------------------------------------
# Wiki File Writer
# ---------------------------------------------------------------------------
class WikiWriter:
    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        for d in (config.wiki_concepts_dir, config.wiki_entities_dir, config.wiki_sources_dir):
            d.mkdir(parents=True, exist_ok=True)

    def write(self, response: WikiResponse) -> list[Path]:
        written: list[Path] = []

        if response.source:
            p = self._write_single(self.config.wiki_sources_dir, response.source)
            if p: written.append(p)

        for concept in response.concepts:
            p = self._write_single(self.config.wiki_concepts_dir, concept)
            if p: written.append(p)

        for entity in response.entities:
            p = self._write_single(self.config.wiki_entities_dir, entity)
            if p: written.append(p)

        return written

    def _write_single(self, folder: Path, data: WikiFile) -> Path | None:
        filename = data.filename.strip()
        content  = data.content.strip()
        if not filename or not content:
            self.logger.debug("Skipping entry with missing filename or content.")
            return None

        filename = re.sub(r"[^\w\s\-.]", "", filename)
        if not filename.endswith(".md"):
            filename += ".md"

        target = folder / filename
        target.write_text(content, encoding="utf-8")
        self.logger.info("  ✅ Written: %s", target.relative_to(self.config.vault))
        return target

# ---------------------------------------------------------------------------
# Auto-Linker (Inyección de Enlaces Mágicos)
# ---------------------------------------------------------------------------
class AutoLinker:
    def __init__(self, config: Config, db: IngestionStateDB, logger: logging.Logger) -> None:
        self.config = config
        self.db = db
        self.logger = logger
        self._lock = asyncio.Lock()
        self._is_running = False

    def _get_terms(self) -> dict[str, str]:
        terms = {}
        if self.config.wiki_concepts_dir.exists():
            for p in self.config.wiki_concepts_dir.glob("*.md"):
                term = p.stem.replace("-", " ")
                terms[term] = f"{self.config.wiki_folder}/concepts/{p.stem}"
        if self.config.wiki_entities_dir.exists():
            for p in self.config.wiki_entities_dir.glob("*.md"):
                term = p.stem.replace("-", " ")
                terms[term] = f"{self.config.wiki_folder}/entities/{p.stem}"
        return terms

    def _apply_links(self, content: str, terms: dict[str, str]) -> tuple[str, int]:
        total_replacements = 0
        parts = content.split('```')
        
        for term, target in terms.items():
            if len(term) <= 3:
                continue
            
            pattern = re.compile(rf'(?<!\[\[)(?<!\[)\b({re.escape(term)})\b(?!\]\])(?!\])(?!\))', flags=re.IGNORECASE)
            
            def replacer(match):
                nonlocal total_replacements
                total_replacements += 1
                return f"[[{target}|{match.group(1)}]]"

            for i in range(0, len(parts), 2):
                parts[i] = pattern.sub(replacer, parts[i])
                
        return '```'.join(parts), total_replacements

    async def run_full_pass(self) -> None:
        if not self.config.auto_link_enabled:
            return

        if self._is_running:
            return
            
        async with self._lock:
            self._is_running = True
            try:
                self.logger.info("🔗 Auto-Linker: Iniciando escaneo de enlaces mágicos en la bóveda...")
                terms = await asyncio.to_thread(self._get_terms)
                if not terms:
                    return

                linked_files = 0
                total_links = 0

                for folder in self.config.watched_folders:
                    watch_dir = self.config.vault / folder
                    if not watch_dir.exists():
                        continue
                        
                    for md_file in watch_dir.rglob("*.md"):
                        abs_path = str(md_file.resolve())
                        if any(abs_path.startswith(d) for d in self.config.ignore_dirs):
                            continue

                        try:
                            content = await asyncio.to_thread(md_file.read_text, encoding="utf-8")
                        except OSError:
                            continue

                        new_content, count = await asyncio.to_thread(self._apply_links, content, terms)
                        
                        if count > 0 and new_content != content:
                            await asyncio.to_thread(md_file.write_text, new_content, encoding="utf-8")
                            new_hash = await asyncio.to_thread(sha256_of_file, md_file)
                            rel = str(md_file.relative_to(self.config.vault))
                            await asyncio.to_thread(self.db.upsert, rel, new_hash, status="ok")
                            
                            linked_files += 1
                            total_links += count
                            self.logger.debug("  🔗 Auto-Linker: %d enlaces inyectados en %s", count, rel)

                if linked_files > 0:
                    self.logger.info("🔗 Auto-Linker: Pass completado. %d enlaces inyectados en %d notas.", total_links, linked_files)
                else:
                    self.logger.info("🔗 Auto-Linker: Pass completado. No se encontraron nuevas menciones.")
            finally:
                self._is_running = False

# ---------------------------------------------------------------------------
# Ingestion Pipeline
# ---------------------------------------------------------------------------
class IngestionPipeline:
    def __init__(
        self,
        config:    Config,
        db:        IngestionStateDB,
        generator: WikiGenerator,
        writer:    WikiWriter,
        logger:    logging.Logger,
        auto_linker: AutoLinker = None,
    ) -> None:
        self.config    = config
        self.db        = db
        self.generator = generator
        self.writer    = writer
        self.logger    = logger
        self.auto_linker = auto_linker

    async def process(self, file_path: Path) -> None:
        rel = str(file_path.relative_to(self.config.vault))
        self.logger.info("📝 Processing note: %s", rel)

        try:
            content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
        except OSError as exc:
            self.logger.error("Cannot read %s: %s", rel, exc)
            return

        if len(content.strip()) < 30:
            self.logger.info("  ⏭  Skipping (content too short): %s", rel)
            return

        current_hash = await asyncio.to_thread(sha256_of_file, file_path)
        record = await asyncio.to_thread(self.db.get_record, rel)
        if record:
            stored_hash, stored_status = record
            if stored_hash == current_hash and stored_status == "ok":
                self.logger.info("  ⏭  No change detected (hash match & status ok). Skipping.")
                return

        try:
            entries = await self.generator.generate_wiki_entries(file_path, content)
        except Exception as exc:
            self.logger.error("LLM error for %s: %s", rel, exc)
            await asyncio.to_thread(self.db.upsert, rel, current_hash, status="error")
            return

        written = await asyncio.to_thread(self.writer.write, entries)
        self.logger.info("  ✅ Generated %d wiki file(s) from: %s", len(written), rel)

        await asyncio.to_thread(self.db.upsert, rel, current_hash, status="ok")
        
        # Trigger Auto-Linker asynchronously if enabled and concepts/entities were created
        if self.auto_linker:
            has_new_knowledge = any("concepts" in str(w) or "entities" in str(w) for w in written)
            if has_new_knowledge:
                asyncio.create_task(self.auto_linker.run_full_pass())

# ---------------------------------------------------------------------------
# File System Watcher (Watchdog to Asyncio Bridge)
# ---------------------------------------------------------------------------
class MarkdownEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        config:   Config,
        pipeline: IngestionPipeline,
        logger:   logging.Logger,
        loop:     asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self.config   = config
        self.pipeline = pipeline
        self.logger   = logger
        self.loop     = loop
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock    = threading.Lock()

    def _is_watched(self, path: str) -> bool:
        abs_path = os.path.abspath(path)
        for ignored in self.config.ignore_dirs:
            if abs_path.startswith(ignored):
                return False
        vault = str(self.config.vault)
        for folder in self.config.watched_folders:
            watch_abs = os.path.join(vault, folder)
            if abs_path.startswith(watch_abs):
                return True
        return False

    async def _debounced_process(self, path: str) -> None:
        delay = self.config.debounce_seconds
        self.logger.debug("Debounce started for %s (%.0fs)", os.path.basename(path), delay)
        await asyncio.sleep(delay)
        
        with self._lock:
            self._tasks.pop(path, None)
            
        p = Path(path)
        if p.exists() and p.is_file():
            await self.pipeline.process(p)

    def _schedule(self, path: str) -> None:
        with self._lock:
            if path in self._tasks:
                self._tasks[path].cancel()
                
            task = asyncio.run_coroutine_threadsafe(self._debounced_process(path), self.loop)
            self._tasks[path] = task

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
# Initial Vault Scan
# ---------------------------------------------------------------------------
async def initial_scan(config: Config, pipeline: IngestionPipeline, logger: logging.Logger) -> None:
    logger.info("🔍 Running initial vault scan…")
    
    # We use a semaphore to limit the number of concurrent LLM processing tasks
    # The actual rate limiter in WikiGenerator will further throttle based on time,
    # but the semaphore prevents loading too many files into memory at once.
    semaphore = asyncio.Semaphore(10)
    
    async def _process_with_semaphore(md_file: Path):
        async with semaphore:
            await pipeline.process(md_file)
            
    tasks = []
    
    for folder in config.watched_folders:
        watch_dir = config.vault / folder
        if not watch_dir.exists():
            logger.debug("Watched folder not found, skipping: %s", folder)
            continue
            
        for md_file in watch_dir.rglob("*.md"):
            rel  = str(md_file.relative_to(config.vault))
            abs_path = str(md_file.resolve())
            ignored  = any(abs_path.startswith(d) for d in config.ignore_dirs)
            if ignored:
                continue
                
            # Perform a quick hash check before even queuing the task to save memory
            current_hash = await asyncio.to_thread(sha256_of_file, md_file)
            record = await asyncio.to_thread(pipeline.db.get_record, rel)
            if record:
                stored_hash, stored_status = record
                if stored_hash == current_hash and stored_status == "ok":
                    continue
            
            tasks.append(asyncio.create_task(_process_with_semaphore(md_file)))
            
    if tasks:
        logger.info("🔍 Found %d modified/new note(s). Processing concurrently...", len(tasks))
        await asyncio.gather(*tasks)
    else:
        logger.info("🔍 No new or modified notes found.")
        
    logger.info("🔍 Initial scan complete.")

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KarpathyWiki Obsidian Ingestion Daemon (Asyncio Edition)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("vault", type=Path, help="Absolute or relative path to your Obsidian vault root.")
    parser.add_argument("--debounce", type=int, default=None, metavar="SECONDS")
    parser.add_argument("--request-interval", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--no-initial-scan", action="store_true", default=False)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()

async def async_main(args: argparse.Namespace, vault_path: Path) -> None:
    boot_logger = logging.getLogger("karpathy_ingest.boot")
    boot_logger.addHandler(logging.StreamHandler(sys.stdout))
    boot_logger.setLevel(logging.INFO)

    config = Config(vault_path, boot_logger)
    logger = setup_logging(config.log_path)
    if args.log_level:
        logger.handlers[0].setLevel(getattr(logging, args.log_level))

    if args.debounce is not None:
        config._raw["debounceSeconds"] = args.debounce
    if args.request_interval is not None:
        config._raw["requestIntervalSeconds"] = args.request_interval

    for d in (config.wiki_sources_dir, config.wiki_concepts_dir, config.wiki_entities_dir):
        d.mkdir(parents=True, exist_ok=True)

    db        = IngestionStateDB(config.db_path)
    generator = WikiGenerator(config, logger)
    writer    = WikiWriter(config, logger)
    auto_linker = AutoLinker(config, db, logger)
    pipeline  = IngestionPipeline(config, db, generator, writer, logger, auto_linker)

    loop = asyncio.get_running_loop()
    handler = MarkdownEventHandler(config, pipeline, logger, loop)

    # Use PollingObserver on Docker for Mac/Windows as inotify may not work across volumes
    if sys.platform in ('darwin', 'win32') and os.environ.get('DOCKER_CONTAINER'):
        logger.info("Using PollingObserver (Docker on Mac/Windows workaround)")
        observer = PollingObserver()
    else:
        observer = Observer()
        
    observer.schedule(handler, str(vault_path), recursive=True)
    observer.start()

    logger.info("=" * 60)
    logger.info("🚀 KarpathyWiki Ingest Daemon (Async) started")
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

    if not args.no_initial_scan:
        await initial_scan(config, pipeline, logger)
        if config.auto_link_enabled:
            await auto_linker.run_full_pass()

    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("⛔ Received stop signal. Shutting down gracefully…")
        stop_event.set()

    # Register signals to gracefully stop the loop
    if sys.platform != 'win32':
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    try:
        await stop_event.wait()
    finally:
        observer.stop()
        observer.join()
        db.close()
        logger.info("👋 Daemon stopped.")

def main() -> None:
    args = parse_args()
    vault_path = args.vault.expanduser().resolve()
    
    if not vault_path.exists() or not vault_path.is_dir():
        sys.exit(f"❌  Vault path is invalid: {vault_path}")

    # Set up asyncio loop
    try:
        asyncio.run(async_main(args, vault_path))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
