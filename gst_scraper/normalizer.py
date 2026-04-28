"""
Normalizer: maps raw extracted rows into the canonical GSTRecord schema.

Handles field mapping, HSN cleaning, rate conversion, date parsing,
and IGST → CGST/SGST splitting.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import pandas as pd

from gst_scraper.models import ConfidenceFlag, GSTRecord

logger = logging.getLogger("gst_scraper.normalizer")

# Common column name aliases → canonical field
_FIELD_ALIASES: dict[str, list[str]] = {
    "hsn_code": [
        "hsn", "hsn_code", "hsn_sac", "hsn_sac_code", "hsncode",
        "chapter_heading", "heading", "tariff", "tariff_item",
    ],
    "description": [
        "description", "desc", "goods_description", "description_of_goods",
        "particulars", "commodity", "item", "product",
        "description_of_supply", "name_of_commodity",
    ],
    "rate": [
        "rate", "gst_rate", "tax_rate", "rate_of_tax",
        "rate_of_gst", "applicable_rate", "gst",
    ],
    "cgst_rate": [
        "cgst", "cgst_rate", "cgst_percent", "central_gst",
    ],
    "sgst_rate": [
        "sgst", "sgst_rate", "sgst_percent", "state_gst", "utgst",
    ],
    "igst_rate": [
        "igst", "igst_rate", "igst_percent", "integrated_gst",
    ],
    "cess_rate": [
        "cess", "cess_rate", "compensation_cess", "cess_percent",
    ],
    "serial_no": [
        "serial_no", "sr_no", "s_no", "sl_no", "sno", "sr",
        "serial", "no", "serial_number",
    ],
    "schedule": [
        "schedule", "sched", "schedule_no", "annexure",
    ],
    "effective_from": [
        "effective_from", "effective_date", "w_e_f", "wef",
        "date", "notification_date",
    ],
}


class Normalizer:
    """
    Transforms raw parsed rows into canonical GSTRecord instances.

    Steps:
    1. Map source-specific column names to canonical fields
    2. Clean and pad HSN codes
    3. Convert rates to Decimal percentages
    4. Split IGST into CGST/SGST if only IGST is available
    5. Parse effective dates
    6. Generate product_id
    7. Assign confidence flags
    """

    def __init__(self, source_name: str = "", source_url: str = ""):
        self.source_name = source_name
        self.source_url = source_url

    def normalize(self, raw_rows: list[dict[str, Any]]) -> list[GSTRecord]:
        """
        Normalize a batch of raw rows into GSTRecord instances.

        Args:
            raw_rows: list of dicts from parser output

        Returns:
            list of validated GSTRecord instances
        """
        records = []
        skipped = 0

        for i, row in enumerate(raw_rows):
            try:
                record = self._normalize_row(row, index=i)
                if record:
                    records.append(record)
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(
                    f"Skipping row {i}: {e}",
                    extra={"source": self.source_name, "stage": "normalize"},
                )
                skipped += 1

        logger.info(
            f"Normalized {len(records)} records from {self.source_name} "
            f"({skipped} skipped)",
            extra={
                "source": self.source_name,
                "count": len(records),
                "stage": "normalize",
            },
        )
        return records

    def _normalize_row(self, row: dict[str, Any], index: int = 0) -> Optional[GSTRecord]:
        """Normalize a single raw row."""
        # Step 1: Map columns
        mapped = self._map_fields(row)

        # Step 2: Extract and clean HSN
        hsn = self._clean_hsn(mapped.get("hsn_code", ""))

        # Step 3: Extract description
        description = str(mapped.get("description", "")).strip()

        # Skip rows with no useful data
        if not hsn and not description:
            return None

        # Step 4: Extract and convert rates
        cgst = self._parse_rate(mapped.get("cgst_rate"))
        sgst = self._parse_rate(mapped.get("sgst_rate"))
        igst = self._parse_rate(mapped.get("igst_rate"))
        cess = self._parse_rate(mapped.get("cess_rate"))

        # If only a combined "rate" field exists, treat it as IGST
        if cgst == 0 and sgst == 0 and igst == 0:
            combined_rate = self._parse_rate(mapped.get("rate"))
            if combined_rate > 0:
                igst = combined_rate

        # Step 5: Split IGST → CGST/SGST
        if igst > 0 and cgst == 0 and sgst == 0:
            cgst = igst / 2
            sgst = igst / 2

        # Derive IGST from CGST+SGST if missing
        if igst == 0 and (cgst > 0 or sgst > 0):
            igst = cgst + sgst

        # Step 6: Parse date
        effective = self._parse_date(mapped.get("effective_from"))

        # Step 7: Confidence flag
        confidence = self._assess_confidence(hsn, description, cgst, sgst, igst)

        # Step 8: Build record
        raw_text = mapped.get("_raw_text", "") or row.get("_raw_text", "")
        source = mapped.get("_source_name", "") or self.source_name

        record = GSTRecord(
            product_id=self._generate_id(hsn, description, str(igst)),
            product_name="",  # Will be set during expansion
            hsn_code=hsn,
            gst_description=description,
            schedule=str(mapped.get("schedule", "")).strip(),
            serial_no=str(mapped.get("serial_no", "")).strip(),
            cgst_rate=cgst,
            sgst_rate=sgst,
            igst_rate=igst,
            cess_rate=cess,
            effective_from=effective,
            source_name=source,
            source_url=self.source_url,
            raw_text=raw_text,
            confidence_flag=confidence,
        )
        return record

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    def _map_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        """Map raw column names to canonical field names using aliases."""
        mapped: dict[str, Any] = {}
        used_keys: set[str] = set()

        for canonical, aliases in _FIELD_ALIASES.items():
            for alias in aliases:
                for key in row:
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    normalized_alias = re.sub(r"[^a-z0-9]", "", alias)
                    if normalized_key == normalized_alias and key not in used_keys:
                        mapped[canonical] = row[key]
                        used_keys.add(key)
                        break
                if canonical in mapped:
                    break

        # Carry through internal fields
        for key in row:
            if key.startswith("_"):
                mapped[key] = row[key]

        return mapped

    # ------------------------------------------------------------------
    # HSN cleaning
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_hsn(value: Any) -> str:
        """Clean HSN code: strip whitespace, dots, and non-numeric prefixes."""
        if value is None:
            return ""
        s = str(value).strip()
        # Remove dots, spaces, dashes
        s = re.sub(r"[.\s\-]", "", s)
        # Remove leading/trailing non-digit characters (like "Chapter")
        s = re.sub(r"^[^0-9]*", "", s)
        s = re.sub(r"[^0-9]*$", "", s)
        return s

    # ------------------------------------------------------------------
    # Rate conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_rate(value: Any) -> Decimal:
        """Convert a rate value to Decimal percentage."""
        if value is None:
            return Decimal("0")

        if isinstance(value, (int, float)):
            return Decimal(str(value))

        if isinstance(value, Decimal):
            return value

        s = str(value).strip().lower()

        # Handle nil/exempt
        if s in ("nil", "exempt", "exempted", "-", "", "n/a", "na", "free", "0"):
            return Decimal("0")

        # Handle percentage strings
        s = s.replace("%", "").strip()

        # Handle ranges like "5% to 12%" → take the first
        if "to" in s:
            s = s.split("to")[0].strip()

        # Handle "or" like "12 or 18" → take first
        if " or " in s:
            s = s.split(" or ")[0].strip()

        # Extract numeric part
        match = re.search(r"[\d.]+", s)
        if match:
            try:
                return Decimal(match.group())
            except InvalidOperation:
                return Decimal("0")

        return Decimal("0")

    # ------------------------------------------------------------------
    # Date parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        """Parse date from various formats."""
        if value is None:
            return None

        if isinstance(value, date):
            return value

        if isinstance(value, datetime):
            return value.date()

        s = str(value).strip()
        if not s or s.lower() in ("", "-", "n/a", "na"):
            return None

        # Try common date formats
        formats = [
            "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y",
            "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y",
            "%d-%b-%Y", "%d-%B-%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue

        return None

    # ------------------------------------------------------------------
    # Confidence assessment
    # ------------------------------------------------------------------

    @staticmethod
    def _assess_confidence(
        hsn: str,
        description: str,
        cgst: Decimal,
        sgst: Decimal,
        igst: Decimal,
    ) -> ConfidenceFlag:
        """Assess data quality confidence level."""
        issues = 0

        if not hsn:
            issues += 2
        elif len(hsn) < 2:
            issues += 1

        if not description:
            issues += 1

        if cgst == 0 and sgst == 0 and igst == 0:
            issues += 1  # Could be exempt, but flag for review

        if cgst < 0 or sgst < 0 or igst < 0:
            issues += 2

        if issues == 0:
            return ConfidenceFlag.HIGH
        elif issues <= 1:
            return ConfidenceFlag.MEDIUM
        else:
            return ConfidenceFlag.REVIEW_REQUIRED

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id(hsn: str, description: str, rate: str) -> str:
        """Generate a deterministic product ID from key fields."""
        seed = f"{hsn}|{description}|{rate}"
        return hashlib.sha256(seed.encode()).hexdigest()[:16]
