"""
SQLite-based async batch job manager for tracking fetch and parse operations.

Uses aiosqlite for non-blocking database access, enabling concurrent
batch processing of multiple source URLs with full state tracking.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from gst_scraper.models import FetchStatus

logger = logging.getLogger("gst_scraper.db")

# SQL schema
_SCHEMA = """
CREATE TABLE IF NOT EXISTS fetch_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    url         TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'html',
    priority    TEXT NOT NULL DEFAULT 'medium',
    is_primary  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    retries     INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    content_path TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(url)
);

CREATE TABLE IF NOT EXISTS parse_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_job_id INTEGER NOT NULL,
    source_name  TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',
    error        TEXT,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (fetch_job_id) REFERENCES fetch_jobs(id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    stage      TEXT NOT NULL,
    data_path  TEXT NOT NULL,
    row_count  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(stage)
);
"""


class JobDB:
    """Async SQLite job manager for batch scraping operations."""

    def __init__(self, db_path: str = "output/gst_scraper.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open connection and initialize schema."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("Connected to job database", extra={"stage": "db_init"})

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Fetch Jobs
    # ------------------------------------------------------------------

    async def enqueue_fetch(
        self,
        source_name: str,
        url: str,
        source_type: str = "html",
        priority: str = "medium",
        is_primary: bool = False,
        max_retries: int = 3,
    ) -> int:
        """Add a fetch job to the queue. Returns job id. Skips if URL already exists."""
        now = datetime.utcnow().isoformat() + "Z"
        try:
            cursor = await self._db.execute(
                """
                INSERT OR IGNORE INTO fetch_jobs
                    (source_name, url, source_type, priority, is_primary, max_retries, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (source_name, url, source_type, priority, int(is_primary), max_retries, now, now),
            )
            await self._db.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to enqueue fetch job: {e}")
            raise

    async def enqueue_sources(self, sources: list[dict[str, Any]], max_retries: int = 3) -> int:
        """Bulk-enqueue source configs. Returns count of new jobs added."""
        count = 0
        for src in sources:
            job_id = await self.enqueue_fetch(
                source_name=src["name"],
                url=src["url"],
                source_type=src.get("source_type", "html"),
                priority=src.get("priority", "medium"),
                is_primary=src.get("is_primary", False),
                max_retries=max_retries,
            )
            if job_id:
                count += 1
        return count

    async def get_pending_jobs(self) -> list[dict[str, Any]]:
        """Get all pending or retryable jobs."""
        cursor = await self._db.execute(
            """
            SELECT * FROM fetch_jobs
            WHERE status IN ('pending', 'failed')
              AND retries < max_retries
            ORDER BY
                CASE priority
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                END,
                is_primary DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_completed_jobs(self) -> list[dict[str, Any]]:
        """Get all completed fetch jobs."""
        cursor = await self._db.execute(
            "SELECT * FROM fetch_jobs WHERE status = 'completed'"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_in_progress(self, job_id: int) -> None:
        """Mark a job as in-progress."""
        now = datetime.utcnow().isoformat() + "Z"
        await self._db.execute(
            "UPDATE fetch_jobs SET status = 'in_progress', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        await self._db.commit()

    async def mark_complete(self, job_id: int, content_path: str) -> None:
        """Mark a job as successfully completed."""
        now = datetime.utcnow().isoformat() + "Z"
        await self._db.execute(
            """
            UPDATE fetch_jobs
            SET status = 'completed', content_path = ?, error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (content_path, now, job_id),
        )
        await self._db.commit()

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Mark a job as failed and increment retry count."""
        now = datetime.utcnow().isoformat() + "Z"
        await self._db.execute(
            """
            UPDATE fetch_jobs
            SET status = 'failed', error = ?, retries = retries + 1, updated_at = ?
            WHERE id = ?
            """,
            (error, now, job_id),
        )
        await self._db.commit()

    async def reset_stale_jobs(self, timeout_minutes: int = 30) -> int:
        """Reset jobs stuck in 'in_progress' for too long back to 'pending'."""
        now = datetime.utcnow().isoformat() + "Z"
        cursor = await self._db.execute(
            """
            UPDATE fetch_jobs
            SET status = 'pending', updated_at = ?
            WHERE status = 'in_progress'
              AND datetime(updated_at) < datetime('now', ?)
            """,
            (now, f"-{timeout_minutes} minutes"),
        )
        await self._db.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Parse Results
    # ------------------------------------------------------------------

    async def record_parse_result(
        self, fetch_job_id: int, source_name: str, record_count: int, status: str = "completed", error: str = ""
    ) -> int:
        """Record parsing results for a fetched source."""
        now = datetime.utcnow().isoformat() + "Z"
        cursor = await self._db.execute(
            """
            INSERT INTO parse_results (fetch_job_id, source_name, record_count, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fetch_job_id, source_name, record_count, status, error, now),
        )
        await self._db.commit()
        return cursor.lastrowid

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    async def save_checkpoint(self, stage: str, data_path: str, row_count: int = 0) -> None:
        """Save/update a pipeline checkpoint."""
        now = datetime.utcnow().isoformat() + "Z"
        await self._db.execute(
            """
            INSERT INTO checkpoints (stage, data_path, row_count, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stage) DO UPDATE SET data_path = ?, row_count = ?, created_at = ?
            """,
            (stage, data_path, row_count, now, data_path, row_count, now),
        )
        await self._db.commit()

    async def get_checkpoint(self, stage: str) -> Optional[dict[str, Any]]:
        """Get checkpoint for a pipeline stage."""
        cursor = await self._db.execute(
            "SELECT * FROM checkpoints WHERE stage = ?", (stage,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_job_stats(self) -> dict[str, int]:
        """Get counts by status."""
        cursor = await self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM fetch_jobs GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {r["status"]: r["cnt"] for r in rows}
