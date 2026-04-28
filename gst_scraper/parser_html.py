"""
HTML table parser with pandas.read_html primary strategy and BeautifulSoup fallback.

Handles source-specific table layouts for CBIC, ClearTax, and generic HTML tables.
"""

from __future__ import annotations

import logging
import re
from io import StringIO
from typing import Any, Optional

import pandas as pd
from bs4 import BeautifulSoup, Tag

from gst_scraper.models import ParseError

logger = logging.getLogger("gst_scraper.parser_html")


class HTMLParser:
    """
    Extracts tabular GST rate data from HTML content.

    Supports two strategies:
    1. pandas.read_html() for well-structured tables
    2. BeautifulSoup manual extraction as fallback
    """

    def __init__(self, parser_config: dict[str, Any] | None = None):
        self.config = parser_config or {}

    def parse(self, html_content: str, source_name: str = "") -> list[dict[str, Any]]:
        """
        Parse HTML content and extract table rows.

        Args:
            html_content: raw HTML string
            source_name: label for the source (for logging)

        Returns:
            List of dicts, each representing a raw extracted row.
        """
        if not html_content or not html_content.strip():
            raise ParseError(source_name, "Empty HTML content")

        rows = []

        # Strategy 1: pandas.read_html
        try:
            rows = self._parse_with_pandas(html_content, source_name)
            if rows:
                logger.info(
                    f"pandas.read_html extracted {len(rows)} rows from {source_name}",
                    extra={"source": source_name, "count": len(rows), "stage": "parse"},
                )
                return rows
        except Exception as e:
            logger.warning(
                f"pandas.read_html failed for {source_name}: {e}. Trying BeautifulSoup fallback.",
                extra={"source": source_name, "stage": "parse"},
            )

        # Strategy 2: BeautifulSoup fallback
        try:
            rows = self._parse_with_bs4(html_content, source_name)
            if rows:
                logger.info(
                    f"BeautifulSoup extracted {len(rows)} rows from {source_name}",
                    extra={"source": source_name, "count": len(rows), "stage": "parse"},
                )
                return rows
        except Exception as e:
            logger.error(
                f"BeautifulSoup fallback also failed for {source_name}: {e}",
                extra={"source": source_name, "stage": "parse"},
            )

        if not rows:
            logger.warning(
                f"No table data found in {source_name}",
                extra={"source": source_name, "stage": "parse"},
            )
        return rows

    # ------------------------------------------------------------------
    # Strategy 1: pandas
    # ------------------------------------------------------------------

    def _parse_with_pandas(self, html: str, source_name: str) -> list[dict[str, Any]]:
        """Use pandas.read_html to extract all tables, then pick the best one."""
        table_selector = self.config.get("table_selector")

        # Use match parameter if selector is available
        try:
            if table_selector:
                dfs = pd.read_html(StringIO(html), match=None, flavor="lxml")
            else:
                dfs = pd.read_html(StringIO(html), flavor="lxml")
        except ImportError:
            # Fallback to html.parser if lxml not available
            dfs = pd.read_html(StringIO(html))

        if not dfs:
            return []

        # Pick the largest table that looks like a rate table
        best_df = self._select_best_table(dfs)
        if best_df is None or best_df.empty:
            return []

        # Normalize column names
        best_df = self._normalize_columns(best_df)

        # Convert to list of dicts, dropping all-NaN rows
        best_df = best_df.dropna(how="all")
        rows = best_df.to_dict(orient="records")

        # Attach raw text for auditability
        for row in rows:
            row["_raw_text"] = " | ".join(str(v) for v in row.values() if pd.notna(v))
            row["_source_name"] = source_name

        return rows

    def _select_best_table(self, dfs: list[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Select the table most likely to contain GST rate data."""
        candidates = []
        gst_keywords = {"hsn", "rate", "gst", "cgst", "sgst", "igst", "description", "goods", "tax", "cess", "slab"}

        for i, df in enumerate(dfs):
            if df.empty or len(df) < 2:
                continue

            # Score based on column name matches
            col_text = " ".join(str(c).lower() for c in df.columns)
            # Also check first few rows for keywords
            sample_text = " ".join(
                str(v).lower() for v in df.head(3).values.flatten() if pd.notna(v)
            )
            combined = col_text + " " + sample_text

            score = sum(1 for kw in gst_keywords if kw in combined)
            candidates.append((score, len(df), i, df))

        if not candidates:
            # Fallback: pick the largest table
            return max(dfs, key=lambda d: len(d)) if dfs else None

        # Sort by keyword score (desc), then by row count (desc)
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][3]

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names to lowercase snake_case."""
        col_map = {}
        for col in df.columns:
            clean = str(col).strip().lower()
            clean = re.sub(r"[^a-z0-9]+", "_", clean)
            clean = clean.strip("_")
            col_map[col] = clean
        return df.rename(columns=col_map)

    # ------------------------------------------------------------------
    # Strategy 2: BeautifulSoup
    # ------------------------------------------------------------------

    def _parse_with_bs4(self, html: str, source_name: str) -> list[dict[str, Any]]:
        """Manual table extraction via BeautifulSoup."""
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")

        if not tables:
            # Try finding divs with table-like structures
            tables = soup.find_all("div", class_=re.compile(r"table|rate|schedule", re.I))

        if not tables:
            return []

        # Pick the largest table
        best_table = max(tables, key=lambda t: len(t.find_all("tr")))
        return self._extract_table_rows(best_table, source_name)

    def _extract_table_rows(self, table: Tag, source_name: str) -> list[dict[str, Any]]:
        """Extract rows from a <table> element."""
        rows_data = []
        trs = table.find_all("tr")

        if not trs:
            return []

        # Determine headers from first row or thead
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
        else:
            header_row = trs[0]

        headers = []
        for cell in header_row.find_all(["th", "td"]):
            text = cell.get_text(strip=True)
            clean = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
            headers.append(clean or f"col_{len(headers)}")

        # Extract data rows
        data_rows = trs[1:] if not thead else table.find("tbody", recursive=False)
        if isinstance(data_rows, Tag):
            data_rows = data_rows.find_all("tr")
        elif data_rows is None:
            data_rows = trs[1:]

        for tr in data_rows:
            if isinstance(tr, Tag):
                cells = tr.find_all(["td", "th"])
                values = [cell.get_text(strip=True) for cell in cells]

                if len(values) >= len(headers):
                    row = dict(zip(headers, values[:len(headers)]))
                elif values:
                    # Pad with empty strings
                    padded = values + [""] * (len(headers) - len(values))
                    row = dict(zip(headers, padded))
                else:
                    continue

                row["_raw_text"] = " | ".join(v for v in values if v)
                row["_source_name"] = source_name
                rows_data.append(row)

        return rows_data
