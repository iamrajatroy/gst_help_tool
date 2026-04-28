"""
Structured logging setup with JSON formatting and run summary collection.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


class JSONFormatter(logging.Formatter):
    """Emit log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include extra fields if present
        for key in ("source", "stage", "count", "url", "elapsed"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry, default=str)


class RunSummaryCollector:
    """
    Collects pipeline metrics across stages and writes a summary at the end.
    Thread-safe via simple attribute writes (GIL-protected for single-writer).
    """

    def __init__(self) -> None:
        self.start_time: datetime | None = None
        self.end_time: datetime | None = None
        self.source_results: list[dict[str, Any]] = []
        self.parse_counts: dict[str, int] = {}
        self.normalization_count: int = 0
        self.classification_distribution: dict[str, int] = {}
        self.expansion_count: int = 0
        self.validation_passed: bool = False
        self.final_row_count: int = 0
        self.errors: list[str] = []

    def start(self) -> None:
        self.start_time = datetime.utcnow()

    def stop(self) -> None:
        self.end_time = datetime.utcnow()

    def record_source(self, name: str, url: str, status: str, rows: int = 0, error: str = "") -> None:
        self.source_results.append({
            "name": name,
            "url": url,
            "status": status,
            "rows_extracted": rows,
            "error": error,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    def record_parse(self, source_name: str, row_count: int) -> None:
        self.parse_counts[source_name] = row_count

    def record_error(self, error: str) -> None:
        self.errors.append(error)

    def to_dict(self) -> dict[str, Any]:
        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        return {
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
            "duration_seconds": duration,
            "sources": {
                "attempted": len(self.source_results),
                "succeeded": sum(1 for s in self.source_results if s["status"] == "completed"),
                "failed": sum(1 for s in self.source_results if s["status"] == "failed"),
                "details": self.source_results,
            },
            "parse_counts": self.parse_counts,
            "normalization_count": self.normalization_count,
            "classification_distribution": self.classification_distribution,
            "expansion_count": self.expansion_count,
            "final_row_count": self.final_row_count,
            "validation_passed": self.validation_passed,
            "errors": self.errors,
        }

    def save(self, output_dir: str) -> Path:
        """Write run summary as JSON."""
        out_path = Path(output_dir) / "run_summary.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        return out_path


def setup_logging(
    level: str = "INFO",
    log_dir: str = "output/logs",
    json_format: bool = True,
) -> logging.Logger:
    """
    Configure root logger with console and file handlers.

    Returns the root 'gst_scraper' logger.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("gst_scraper")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Prevent duplicate handlers on re-init
    if logger.handlers:
        return logger

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))

    # File handler with timestamp
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.FileHandler(log_path / f"run_{ts}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    if json_format:
        fmt = JSONFormatter()
        console.setFormatter(fmt)
        file_handler.setFormatter(fmt)
    else:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console.setFormatter(fmt)
        file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger
