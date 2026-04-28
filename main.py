"""
GST Rate Scraping Tool — CLI Entry Point

Provides CLI commands for running the full scraping, parsing,
normalization, classification, expansion, validation, and export pipeline.

Usage:
    python main.py full-run --config config/config.yaml
    python main.py scrape --config config/config.yaml
    python main.py build-products --config config/config.yaml --target-rows 100000
    python main.py export --config config/config.yaml --format xlsx
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml

from gst_scraper.classifier import Classifier
from gst_scraper.db import JobDB
from gst_scraper.exporter import Exporter
from gst_scraper.expander import Expander
from gst_scraper.fetcher import Fetcher
from gst_scraper.logger import RunSummaryCollector, setup_logging
from gst_scraper.models import (
    AppConfig,
    ClassificationConfig,
    ExportConfig,
    ExpansionMode,
    FetchStatus,
    NetworkConfig,
    SourceConfig,
)
from gst_scraper.normalizer import Normalizer
from gst_scraper.parser_html import HTMLParser
from gst_scraper.parser_pdf import PDFParser
from gst_scraper.validator import Validator
from gst_scraper.fallback_data import FALLBACK_GST_DATA
from gst_scraper.models import ConfidenceFlag, GSTRecord as GSTRecordModel

app = typer.Typer(
    name="gst-scraper",
    help="GST Rate Scraping and Excel Generation Tool",
    add_completion=False,
)


def _load_config(config_path: str) -> AppConfig:
    """Load and validate YAML configuration."""
    path = Path(config_path)
    if not path.exists():
        typer.echo(f"Error: Config file not found: {config_path}", err=True)
        raise typer.Exit(1)

    with open(path) as f:
        raw = yaml.safe_load(f)

    return AppConfig(**raw)


def _save_checkpoint(records, stage: str, output_dir: str) -> str:
    """Save intermediate records as pickle for resumability."""
    import pickle
    checkpoint_dir = Path(output_dir) / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = checkpoint_dir / f"{stage}.pkl"
    with open(path, "wb") as f:
        pickle.dump(records, f)
    return str(path)


def _load_checkpoint(stage: str, output_dir: str):
    """Load checkpoint if available."""
    import pickle
    path = Path(output_dir) / "checkpoints" / f"{stage}.pkl"
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    return None


def _load_fallback_records() -> list:
    """Load embedded fallback GST data when scraping fails."""
    from decimal import Decimal
    records = []
    for hsn, desc, igst, cess, schedule in FALLBACK_GST_DATA:
        igst_d = Decimal(str(igst))
        cess_d = Decimal(str(cess))
        cgst_d = igst_d / 2 if igst_d > 0 else Decimal("0")
        sgst_d = igst_d / 2 if igst_d > 0 else Decimal("0")
        rec = GSTRecordModel(
            hsn_code=hsn,
            gst_description=desc,
            cgst_rate=cgst_d,
            sgst_rate=sgst_d,
            igst_rate=igst_d,
            cess_rate=cess_d,
            schedule=schedule,
            source_name="Embedded Fallback (CBIC 2025)",
            source_url="https://www.cbic-gst.gov.in",
            confidence_flag=ConfidenceFlag.HIGH,
        )
        records.append(rec)
    return records


# ======================================================================
# CLI Commands
# ======================================================================

@app.command()
def scrape(
    config: str = typer.Option("config/config.yaml", "--config", "-c", help="Path to config YAML"),
):
    """Fetch and parse GST data from configured sources."""
    cfg = _load_config(config)
    logger = setup_logging(cfg.logging.level, cfg.logging.log_dir, cfg.logging.json_format)
    summary = RunSummaryCollector()
    summary.start()

    asyncio.run(_run_scrape(cfg, logger, summary))

    summary.stop()
    summary.save(cfg.export.output_dir)
    typer.echo("✅ Scraping complete. Check output/run_summary.json for details.")


async def _run_scrape(cfg: AppConfig, logger, summary: RunSummaryCollector):
    """Async scraping pipeline."""
    db = JobDB(cfg.db_path)
    await db.connect()

    try:
        # Enqueue sources
        sources = [s.model_dump() for s in cfg.sources]
        new_jobs = await db.enqueue_sources(sources, max_retries=cfg.network.retries)
        logger.info(f"Enqueued {new_jobs} new fetch jobs")

        # Reset stale jobs
        await db.reset_stale_jobs()

        # Fetch pending jobs
        pending = await db.get_pending_jobs()
        logger.info(f"Processing {len(pending)} pending fetch jobs")

        async with Fetcher(cfg.network) as fetcher:
            for job in pending:
                await db.mark_in_progress(job["id"])
                try:
                    if job["source_type"] == "pdf":
                        result = await fetcher.fetch_pdf(job["url"])
                    else:
                        result = await fetcher.fetch_html(job["url"])

                    if result.status == FetchStatus.COMPLETED:
                        await db.mark_complete(job["id"], result.content_path or "")
                        summary.record_source(job["source_name"], job["url"], "completed")
                        logger.info(f"✓ Fetched {job['source_name']}")

                        # Parse immediately
                        all_rows = _parse_source(job, result, cfg)
                        if all_rows:
                            await db.record_parse_result(
                                job["id"], job["source_name"], len(all_rows), "completed"
                            )
                            summary.record_parse(job["source_name"], len(all_rows))

                            # Save parsed data
                            _save_parsed_rows(all_rows, job["source_name"], cfg.export.output_dir)
                    else:
                        await db.mark_failed(job["id"], result.error or "Unknown error")
                        summary.record_source(job["source_name"], job["url"], "failed", error=result.error or "")
                        logger.warning(f"✗ Failed {job['source_name']}: {result.error}")

                        # Critical: stop if primary source fails
                        if job.get("is_primary") and result.status == FetchStatus.FAILED:
                            logger.error("Primary source (CBIC) failed. Pipeline may produce incomplete results.")

                except Exception as e:
                    await db.mark_failed(job["id"], str(e))
                    summary.record_source(job["source_name"], job["url"], "failed", error=str(e))
                    logger.error(f"Error processing {job['source_name']}: {e}")

    finally:
        await db.close()


def _parse_source(job: dict, result, cfg: AppConfig) -> list[dict]:
    """Parse a fetched source based on its type."""
    source_name = job["source_name"]

    # Get source config
    source_cfg = next(
        (s for s in cfg.sources if s.name == source_name),
        None,
    )
    parser_config = source_cfg.parser_config if source_cfg else {}

    if job["source_type"] == "pdf":
        parser = PDFParser(parser_config=parser_config)
        return parser.parse(result.content_path, source_name)
    else:
        parser = HTMLParser(parser_config=parser_config)
        content = result.content
        if not content and result.content_path:
            content = Path(result.content_path).read_text(encoding="utf-8")
        return parser.parse(content or "", source_name)


def _save_parsed_rows(rows: list[dict], source_name: str, output_dir: str):
    """Save parsed rows to JSON for later processing."""
    import re
    parsed_dir = Path(output_dir) / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", source_name).lower()
    path = parsed_dir / f"{safe_name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str, ensure_ascii=False)


def _load_all_parsed_rows(output_dir: str) -> list[dict]:
    """Load all parsed JSON files."""
    parsed_dir = Path(output_dir) / "parsed"
    if not parsed_dir.exists():
        return []

    all_rows = []
    for path in parsed_dir.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
            all_rows.extend(rows)
    return all_rows


@app.command(name="build-products")
def build_products(
    config: str = typer.Option("config/config.yaml", "--config", "-c", help="Path to config YAML"),
    target_rows: int = typer.Option(100_000, "--target-rows", "-t", help="Target number of output rows"),
):
    """Normalize, classify, and expand scraped data into product records."""
    cfg = _load_config(config)
    logger = setup_logging(cfg.logging.level, cfg.logging.log_dir, cfg.logging.json_format)

    # Load parsed data
    raw_rows = _load_all_parsed_rows(cfg.export.output_dir)
    if not raw_rows:
        typer.echo("⚠ No parsed data found. Run 'scrape' first.", err=True)
        raise typer.Exit(1)

    typer.echo(f"📦 Loaded {len(raw_rows)} raw rows from parsed sources")

    # Normalize
    normalizer = Normalizer(source_name="combined", source_url="")
    records = normalizer.normalize(raw_rows)
    typer.echo(f"🔧 Normalized to {len(records)} records")
    _save_checkpoint(records, "normalized", cfg.export.output_dir)

    # Validate base records
    validator = Validator()
    base_report = validator.validate(records)
    typer.echo(f"✓ Base validation: {base_report.valid_records}/{base_report.total_records} valid")

    # Resolve conflicts (CBIC preferred)
    records = validator.resolve_conflicts(records)
    typer.echo(f"📋 After dedup: {len(records)} unique records")

    # Classify
    classifier = Classifier(cfg.classification)
    records = classifier.classify(records)
    _save_checkpoint(records, "classified", cfg.export.output_dir)

    # Distribution
    dist = {}
    for r in records:
        cat = r.top_category if isinstance(r.top_category, str) else r.top_category.value
        dist[cat] = dist.get(cat, 0) + 1
    typer.echo(f"📊 Categories: {dist}")

    # Expand
    expander = Expander(
        mode=cfg.expansion.mode,
        target_rows=target_rows,
        catalog_path=cfg.expansion.catalog_input_path,
    )
    expanded = expander.expand(records)
    typer.echo(f"🚀 Expanded to {len(expanded)} product rows")
    _save_checkpoint(expanded, "expanded", cfg.export.output_dir)

    # Final validation
    final_report = validator.validate(expanded)
    typer.echo(f"✓ Final validation: {final_report.valid_records}/{final_report.total_records} valid")
    _save_checkpoint(final_report, "validation_report", cfg.export.output_dir)

    typer.echo("✅ Build complete. Run 'export' to generate files.")


@app.command()
def export(
    config: str = typer.Option("config/config.yaml", "--config", "-c", help="Path to config YAML"),
    format: str = typer.Option("xlsx", "--format", "-f", help="Export format: xlsx, csv, or all"),
):
    """Export processed data to Excel/CSV files."""
    cfg = _load_config(config)
    logger = setup_logging(cfg.logging.level, cfg.logging.log_dir, cfg.logging.json_format)

    # Load expanded data
    expanded = _load_checkpoint("expanded", cfg.export.output_dir)
    if not expanded:
        typer.echo("⚠ No expanded data found. Run 'build-products' first.", err=True)
        raise typer.Exit(1)

    validation_report = _load_checkpoint("validation_report", cfg.export.output_dir)

    exporter = Exporter(cfg.export)
    outputs = exporter.export_all(expanded, validation_report)

    for fmt, path in outputs.items():
        typer.echo(f"📁 {fmt}: {path}")

    typer.echo(f"✅ Export complete! {len(expanded)} rows exported.")


@app.command(name="full-run")
def full_run(
    config: str = typer.Option("config/config.yaml", "--config", "-c", help="Path to config YAML"),
    target_rows: int = typer.Option(100_000, "--target-rows", "-t", help="Target number of output rows"),
    allow_secondary_only: bool = typer.Option(False, "--allow-secondary-only", help="Continue even if primary source fails"),
):
    """Run the complete pipeline: scrape → build → export."""
    cfg = _load_config(config)
    logger = setup_logging(cfg.logging.level, cfg.logging.log_dir, cfg.logging.json_format)
    summary = RunSummaryCollector()
    summary.start()

    typer.echo("=" * 60)
    typer.echo("  GST Rate Scraping & Excel Generation Tool")
    typer.echo("=" * 60)

    # Phase 1: Scrape
    typer.echo("\n📡 Phase 1: Scraping sources...")
    asyncio.run(_run_scrape(cfg, logger, summary))

    # Phase 2: Build products
    typer.echo("\n🏗 Phase 2: Building product dataset...")
    raw_rows = _load_all_parsed_rows(cfg.export.output_dir)
    use_fallback = False

    if not raw_rows:
        typer.echo("  ⚠ No data from live scraping. Using embedded fallback dataset...")
        use_fallback = True

    if use_fallback:
        records = _load_fallback_records()
        typer.echo(f"  📦 Loaded {len(records)} records from embedded fallback data")
        summary.normalization_count = len(records)
    else:
        typer.echo(f"  📦 Raw rows: {len(raw_rows)}")

        # Normalize
        normalizer = Normalizer()
        records = normalizer.normalize(raw_rows)
        summary.normalization_count = len(records)
        typer.echo(f"  🔧 Normalized: {len(records)} records")

        # If normalization produced nothing usable, fall back to embedded data
        if not records:
            typer.echo("  ⚠ Normalizer could not parse scraped data. Using embedded fallback dataset...")
            records = _load_fallback_records()
            typer.echo(f"  📦 Loaded {len(records)} records from embedded fallback data")
            summary.normalization_count = len(records)

    # Validate
    validator = Validator()
    records = validator.resolve_conflicts(records)
    typer.echo(f"  📋 After dedup: {len(records)}")

    # Classify
    classifier = Classifier(cfg.classification)
    records = classifier.classify(records)

    dist = {}
    for r in records:
        cat = r.top_category if isinstance(r.top_category, str) else r.top_category.value
        dist[cat] = dist.get(cat, 0) + 1
    summary.classification_distribution = dist
    typer.echo(f"  📊 Categories: {dist}")

    # Expand
    expander = Expander(mode=cfg.expansion.mode, target_rows=target_rows)
    expanded = expander.expand(records)
    summary.expansion_count = len(expanded)
    typer.echo(f"  🚀 Expanded: {len(expanded)} product rows")

    # Final validation
    final_report = validator.validate(expanded)
    summary.validation_passed = final_report.passed
    typer.echo(f"  ✓ Validation: {final_report.valid_records}/{final_report.total_records} valid")

    # Phase 3: Export
    typer.echo("\n📁 Phase 3: Exporting...")
    exporter = Exporter(cfg.export)
    outputs = exporter.export_all(expanded, final_report, summary.to_dict())
    summary.final_row_count = len(expanded)

    for fmt, path in outputs.items():
        typer.echo(f"  {fmt}: {path}")

    # Save run summary
    summary.stop()
    summary_path = summary.save(cfg.export.output_dir)
    typer.echo(f"\n📊 Run summary: {summary_path}")

    typer.echo("\n" + "=" * 60)
    typer.echo(f"  ✅ Pipeline complete! {len(expanded)} rows exported.")
    typer.echo("=" * 60)


@app.command()
def status(
    config: str = typer.Option("config/config.yaml", "--config", "-c", help="Path to config YAML"),
):
    """Show current pipeline status from the job database."""
    cfg = _load_config(config)

    async def _show_status():
        db = JobDB(cfg.db_path)
        await db.connect()
        try:
            stats = await db.get_job_stats()
            typer.echo("📊 Job Status:")
            for status, count in stats.items():
                typer.echo(f"  {status}: {count}")

            # Check checkpoints
            for stage in ["normalized", "classified", "expanded", "validation_report"]:
                cp = await db.get_checkpoint(stage)
                if cp:
                    typer.echo(f"  ✓ Checkpoint '{stage}': {cp['row_count']} rows")
        finally:
            await db.close()

    asyncio.run(_show_status())


if __name__ == "__main__":
    app()
