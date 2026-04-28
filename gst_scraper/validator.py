"""
Validator: performs data quality checks on GSTRecord datasets.

Detects duplicates, missing fields, negative rates, conflicts across sources,
and invalid category values. CBIC source takes precedence in conflicts.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

from gst_scraper.models import (
    ConfidenceFlag,
    GSTRecord,
    SubCategory,
    TopCategory,
    ValidationIssue,
    ValidationReport,
)

logger = logging.getLogger("gst_scraper.validator")


class Validator:
    """
    Validates GSTRecord datasets for data quality.

    Checks:
    1. No blank hsn_code in accepted final rows
    2. No negative GST values
    3. Valid category enum values
    4. Duplicate HSN-description-rate detection
    5. Cross-source rate conflict detection (CBIC takes precedence)
    6. Missing rate fields
    """

    def __init__(self, primary_source_name: str = "CBIC GST Goods Rates"):
        self.primary_source = primary_source_name

    def validate(self, records: list[GSTRecord]) -> ValidationReport:
        """
        Run all validation checks and return a report.

        Args:
            records: list of GSTRecord instances to validate

        Returns:
            ValidationReport with issues and statistics
        """
        report = ValidationReport(total_records=len(records))
        issues: list[ValidationIssue] = []

        # Run checks
        issues.extend(self._check_missing_hsn(records))
        issues.extend(self._check_negative_rates(records))
        issues.extend(self._check_valid_categories(records))
        issues.extend(self._check_missing_rates(records))
        issues.extend(self._check_duplicates(records))
        issues.extend(self._check_conflicts(records))

        # Update report
        report.issues = issues
        report.missing_hsn_count = sum(1 for i in issues if i.issue_type == "missing_hsn")
        report.negative_rate_count = sum(1 for i in issues if i.issue_type == "negative_rate")
        report.duplicates_found = sum(1 for i in issues if i.issue_type == "duplicate")
        report.conflicts_found = sum(1 for i in issues if i.issue_type == "conflict")

        error_count = sum(1 for i in issues if i.severity == "error")
        report.valid_records = report.total_records - error_count
        report.passed = error_count == 0

        logger.info(
            f"Validation complete: {report.valid_records}/{report.total_records} valid, "
            f"{len(issues)} issues ({error_count} errors)",
            extra={"stage": "validate", "count": report.total_records},
        )

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_missing_hsn(self, records: list[GSTRecord]) -> list[ValidationIssue]:
        """Check for blank HSN codes."""
        issues = []
        for rec in records:
            if not rec.hsn_code or not rec.hsn_code.strip():
                issues.append(ValidationIssue(
                    issue_type="missing_hsn",
                    severity="warning",
                    record_id=rec.product_id,
                    description=f"Missing HSN code. Description: {rec.gst_description[:80]}",
                    source_name=rec.source_name,
                ))
        return issues

    def _check_negative_rates(self, records: list[GSTRecord]) -> list[ValidationIssue]:
        """Check for negative rate values."""
        issues = []
        for rec in records:
            for field_name in ("cgst_rate", "sgst_rate", "igst_rate", "cess_rate"):
                val = getattr(rec, field_name)
                if isinstance(val, str):
                    try:
                        val = Decimal(val)
                    except Exception:
                        continue
                if val < 0:
                    issues.append(ValidationIssue(
                        issue_type="negative_rate",
                        severity="error",
                        record_id=rec.product_id,
                        hsn_code=rec.hsn_code,
                        description=f"Negative {field_name}: {val}",
                        source_name=rec.source_name,
                    ))
        return issues

    def _check_valid_categories(self, records: list[GSTRecord]) -> list[ValidationIssue]:
        """Check that category values are valid enums."""
        valid_top = {e.value for e in TopCategory}
        valid_sub = {e.value for e in SubCategory}
        issues = []

        for rec in records:
            top = rec.top_category if isinstance(rec.top_category, str) else rec.top_category.value
            sub = rec.sub_category if isinstance(rec.sub_category, str) else rec.sub_category.value

            if top not in valid_top:
                issues.append(ValidationIssue(
                    issue_type="invalid_category",
                    severity="error",
                    record_id=rec.product_id,
                    hsn_code=rec.hsn_code,
                    description=f"Invalid top_category: {top}",
                ))
            if sub not in valid_sub:
                issues.append(ValidationIssue(
                    issue_type="invalid_category",
                    severity="error",
                    record_id=rec.product_id,
                    hsn_code=rec.hsn_code,
                    description=f"Invalid sub_category: {sub}",
                ))
        return issues

    def _check_missing_rates(self, records: list[GSTRecord]) -> list[ValidationIssue]:
        """Check for records with all-zero rates (may be legitimate exempt goods)."""
        issues = []
        for rec in records:
            cgst = Decimal(str(rec.cgst_rate))
            sgst = Decimal(str(rec.sgst_rate))
            igst = Decimal(str(rec.igst_rate))
            if cgst == 0 and sgst == 0 and igst == 0:
                issues.append(ValidationIssue(
                    issue_type="zero_rates",
                    severity="warning",
                    record_id=rec.product_id,
                    hsn_code=rec.hsn_code,
                    description=f"All rates are zero. May be exempt. Desc: {rec.gst_description[:60]}",
                    source_name=rec.source_name,
                ))
        return issues

    def _check_duplicates(self, records: list[GSTRecord]) -> list[ValidationIssue]:
        """Detect duplicate HSN-description-rate combinations."""
        seen: dict[str, str] = {}  # key → first product_id
        issues = []

        for rec in records:
            key = f"{rec.hsn_code}|{rec.gst_description.strip().lower()}|{rec.igst_rate}"
            if key in seen:
                issues.append(ValidationIssue(
                    issue_type="duplicate",
                    severity="warning",
                    record_id=rec.product_id,
                    hsn_code=rec.hsn_code,
                    description=(
                        f"Duplicate of record {seen[key]}. "
                        f"HSN={rec.hsn_code}, Rate={rec.igst_rate}%"
                    ),
                    source_name=rec.source_name,
                ))
            else:
                seen[key] = rec.product_id

        return issues

    def _check_conflicts(self, records: list[GSTRecord]) -> list[ValidationIssue]:
        """
        Detect conflicting rates for the same HSN across different sources.
        CBIC source takes precedence.
        """
        # Group by HSN
        by_hsn: dict[str, list[GSTRecord]] = defaultdict(list)
        for rec in records:
            if rec.hsn_code:
                by_hsn[rec.hsn_code].append(rec)

        issues = []
        for hsn, hsn_records in by_hsn.items():
            # Get unique source-rate combos
            source_rates: dict[str, Decimal] = {}
            for rec in hsn_records:
                if rec.source_name not in source_rates:
                    source_rates[rec.source_name] = Decimal(str(rec.igst_rate))

            # Check for conflicts
            unique_rates = set(source_rates.values())
            if len(unique_rates) > 1:
                primary_rate = source_rates.get(self.primary_source)
                conflict_desc = ", ".join(
                    f"{src}={rate}%" for src, rate in source_rates.items()
                )
                for rec in hsn_records:
                    if rec.source_name != self.primary_source:
                        rec_rate = Decimal(str(rec.igst_rate))
                        if primary_rate is not None and rec_rate != primary_rate:
                            issues.append(ValidationIssue(
                                issue_type="conflict",
                                severity="warning",
                                record_id=rec.product_id,
                                hsn_code=hsn,
                                description=(
                                    f"Rate conflict for HSN {hsn}: {conflict_desc}. "
                                    f"CBIC rate ({primary_rate}%) takes precedence."
                                ),
                                source_name=rec.source_name,
                            ))
                            # Override with CBIC rate
                            rec.igst_rate = primary_rate
                            rec.cgst_rate = primary_rate / 2
                            rec.sgst_rate = primary_rate / 2
                            rec.confidence_flag = ConfidenceFlag.REVIEW_REQUIRED.value

        return issues

    def resolve_conflicts(self, records: list[GSTRecord]) -> list[GSTRecord]:
        """
        Resolve cross-source conflicts by preferring CBIC source.
        Returns deduplicated list.
        """
        # Build preferred records: CBIC first, then by order
        best: dict[str, GSTRecord] = {}

        for rec in records:
            key = f"{rec.hsn_code}|{rec.gst_description.strip().lower()}"
            existing = best.get(key)

            if existing is None:
                best[key] = rec
            elif rec.source_name == self.primary_source and existing.source_name != self.primary_source:
                best[key] = rec
            # Keep existing otherwise (first seen)

        resolved = list(best.values())
        logger.info(
            f"Conflict resolution: {len(records)} → {len(resolved)} records",
            extra={"stage": "validate"},
        )
        return resolved
