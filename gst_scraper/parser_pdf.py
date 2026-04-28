"""
PDF table parser with pdfplumber (primary) and camelot-py (secondary fallback).

Extracts tabular data from PDF files containing GST rate schedules without OCR.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from gst_scraper.models import PDFEngine, ParseError

logger = logging.getLogger("gst_scraper.parser_pdf")


class PDFParser:
    """
    Dual-engine PDF table extractor.

    Engines:
    - pdfplumber (primary): pure Python, no external deps
    - camelot-py (secondary): lattice/stream mode fallback

    Set engine='auto' to try pdfplumber first, fallback to camelot.
    """

    def __init__(
        self,
        engine: PDFEngine | str = PDFEngine.AUTO,
        parser_config: dict[str, Any] | None = None,
    ):
        if isinstance(engine, str):
            engine = PDFEngine(engine)
        self.engine = engine
        self.config = parser_config or {}

    def parse(self, pdf_path: str, source_name: str = "") -> list[dict[str, Any]]:
        """
        Extract table rows from a PDF file.

        Args:
            pdf_path: path to the PDF file
            source_name: label for the source (for logging)

        Returns:
            List of dicts representing raw extracted rows.
        """
        path = Path(pdf_path)
        if not path.exists():
            raise ParseError(source_name, f"PDF file not found: {pdf_path}")

        rows = []

        if self.engine == PDFEngine.PDFPLUMBER:
            rows = self._parse_pdfplumber(path, source_name)
        elif self.engine == PDFEngine.CAMELOT:
            rows = self._parse_camelot(path, source_name)
        elif self.engine == PDFEngine.AUTO:
            # Try pdfplumber first
            try:
                rows = self._parse_pdfplumber(path, source_name)
                if rows:
                    return rows
            except Exception as e:
                logger.warning(
                    f"pdfplumber failed for {source_name}: {e}. Trying camelot.",
                    extra={"source": source_name, "stage": "parse_pdf"},
                )

            # Fallback to camelot
            try:
                rows = self._parse_camelot(path, source_name)
            except Exception as e:
                logger.error(
                    f"Both PDF engines failed for {source_name}: {e}",
                    extra={"source": source_name, "stage": "parse_pdf"},
                )

        return rows

    # ------------------------------------------------------------------
    # pdfplumber engine
    # ------------------------------------------------------------------

    def _parse_pdfplumber(self, path: Path, source_name: str) -> list[dict[str, Any]]:
        """Extract tables using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            raise ParseError(source_name, "pdfplumber is not installed")

        rows = []
        table_settings = self.config.get("table_settings", {})

        with pdfplumber.open(path) as pdf:
            logger.info(
                f"Processing PDF {path.name} with pdfplumber ({len(pdf.pages)} pages)",
                extra={"source": source_name, "stage": "parse_pdf"},
            )

            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    tables = page.extract_tables(table_settings) if table_settings else page.extract_tables()

                    if not tables:
                        continue

                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        # First row as headers
                        headers = self._clean_headers(table[0])

                        for row_data in table[1:]:
                            if not row_data or all(not cell for cell in row_data):
                                continue

                            # Pad or trim to match headers
                            if len(row_data) < len(headers):
                                row_data = list(row_data) + [""] * (len(headers) - len(row_data))
                            row_data = row_data[:len(headers)]

                            row = dict(zip(headers, [str(c).strip() if c else "" for c in row_data]))
                            row["_raw_text"] = " | ".join(str(c) for c in row_data if c)
                            row["_source_name"] = source_name
                            row["_page"] = page_num
                            rows.append(row)

                except Exception as e:
                    logger.warning(
                        f"Error on page {page_num} of {path.name}: {e}",
                        extra={"source": source_name, "stage": "parse_pdf"},
                    )

        logger.info(
            f"pdfplumber extracted {len(rows)} rows from {path.name}",
            extra={"source": source_name, "count": len(rows), "stage": "parse_pdf"},
        )
        return rows

    # ------------------------------------------------------------------
    # camelot engine
    # ------------------------------------------------------------------

    def _parse_camelot(self, path: Path, source_name: str) -> list[dict[str, Any]]:
        """Extract tables using camelot-py."""
        try:
            import camelot
        except ImportError:
            raise ParseError(source_name, "camelot-py is not installed")

        rows = []
        flavor = self.config.get("camelot_flavor", "lattice")

        try:
            tables = camelot.read_pdf(
                str(path),
                pages="all",
                flavor=flavor,
            )

            logger.info(
                f"camelot found {len(tables)} tables in {path.name}",
                extra={"source": source_name, "stage": "parse_pdf"},
            )

            for tbl_idx, table in enumerate(tables):
                df = table.df

                if df.empty or len(df) < 2:
                    continue

                # First row as headers
                headers = self._clean_headers(df.iloc[0].tolist())
                df = df.iloc[1:]
                df.columns = headers

                for _, row_series in df.iterrows():
                    row = row_series.to_dict()
                    row["_raw_text"] = " | ".join(str(v) for v in row_series if v)
                    row["_source_name"] = source_name
                    row["_table_idx"] = tbl_idx
                    rows.append(row)

        except Exception as e:
            logger.error(
                f"camelot extraction failed for {path.name}: {e}",
                extra={"source": source_name, "stage": "parse_pdf"},
            )

        logger.info(
            f"camelot extracted {len(rows)} rows from {path.name}",
            extra={"source": source_name, "count": len(rows), "stage": "parse_pdf"},
        )
        return rows

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_headers(raw_headers: list) -> list[str]:
        """Clean and normalize header strings."""
        import re

        headers = []
        for h in raw_headers:
            text = str(h).strip() if h else ""
            clean = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
            headers.append(clean or f"col_{len(headers)}")
        return headers
