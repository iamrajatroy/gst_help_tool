"""Tests for the Validator module."""

from decimal import Decimal

import pytest

from gst_scraper.models import ConfidenceFlag, GSTRecord, TopCategory, SubCategory
from gst_scraper.validator import Validator


class TestMissingHSN:
    """Test detection of missing HSN codes."""

    def test_detects_missing_hsn(self):
        records = [
            GSTRecord(product_id="1", hsn_code="", gst_description="Test item"),
            GSTRecord(product_id="2", hsn_code="1006", gst_description="Rice"),
        ]
        v = Validator()
        report = v.validate(records)
        assert report.missing_hsn_count == 1

    def test_no_missing_hsn(self, sample_gst_records):
        v = Validator()
        report = v.validate(sample_gst_records)
        assert report.missing_hsn_count == 0


class TestNegativeRates:
    """Test detection of negative rate values."""

    def test_detects_negative_rate(self):
        records = [
            GSTRecord(
                product_id="neg_1",
                hsn_code="1006",
                cgst_rate=Decimal("-5"),
                sgst_rate=Decimal("5"),
                igst_rate=Decimal("0"),
            )
        ]
        v = Validator()
        report = v.validate(records)
        assert report.negative_rate_count > 0

    def test_no_negative_rates(self, sample_gst_records):
        v = Validator()
        report = v.validate(sample_gst_records)
        assert report.negative_rate_count == 0


class TestDuplicates:
    """Test duplicate detection."""

    def test_detects_duplicate(self):
        records = [
            GSTRecord(
                product_id="dup_1",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("5"),
            ),
            GSTRecord(
                product_id="dup_2",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("5"),
            ),
        ]
        v = Validator()
        report = v.validate(records)
        assert report.duplicates_found == 1

    def test_no_duplicate_with_different_rates(self):
        records = [
            GSTRecord(
                product_id="nd_1",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("5"),
            ),
            GSTRecord(
                product_id="nd_2",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("12"),
            ),
        ]
        v = Validator()
        report = v.validate(records)
        assert report.duplicates_found == 0


class TestConflicts:
    """Test cross-source rate conflict detection."""

    def test_detects_conflict(self):
        records = [
            GSTRecord(
                product_id="c1",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("5"),
                source_name="CBIC GST Goods Rates",
            ),
            GSTRecord(
                product_id="c2",
                hsn_code="1006",
                gst_description="Rice paddy",
                igst_rate=Decimal("12"),
                source_name="ClearTax GST Rates",
            ),
        ]
        v = Validator()
        report = v.validate(records)
        assert report.conflicts_found > 0

    def test_cbic_takes_precedence(self):
        records = [
            GSTRecord(
                product_id="p1",
                hsn_code="8517",
                gst_description="Smartphones",
                igst_rate=Decimal("18"),
                cgst_rate=Decimal("9"),
                sgst_rate=Decimal("9"),
                source_name="CBIC GST Goods Rates",
            ),
            GSTRecord(
                product_id="p2",
                hsn_code="8517",
                gst_description="Mobile phones",
                igst_rate=Decimal("12"),
                cgst_rate=Decimal("6"),
                sgst_rate=Decimal("6"),
                source_name="ClearTax GST Rates",
            ),
        ]
        v = Validator()
        v.validate(records)
        # After validation, the ClearTax record should be overridden to CBIC rate
        assert records[1].igst_rate == Decimal("18")


class TestValidCategories:
    """Test category enum validation."""

    def test_valid_categories_pass(self, sample_gst_records):
        v = Validator()
        report = v.validate(sample_gst_records)
        invalid = [i for i in report.issues if i.issue_type == "invalid_category"]
        assert len(invalid) == 0


class TestConflictResolution:
    """Test deduplication with CBIC preference."""

    def test_resolve_prefers_cbic(self):
        records = [
            GSTRecord(
                product_id="r1",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("5"),
                source_name="ClearTax GST Rates",
            ),
            GSTRecord(
                product_id="r2",
                hsn_code="1006",
                gst_description="Rice",
                igst_rate=Decimal("5"),
                source_name="CBIC GST Goods Rates",
            ),
        ]
        v = Validator()
        resolved = v.resolve_conflicts(records)
        assert len(resolved) == 1
        assert resolved[0].source_name == "CBIC GST Goods Rates"


class TestOverallReport:
    """Test the overall validation report."""

    def test_report_passes_with_clean_data(self, sample_gst_records):
        v = Validator()
        report = v.validate(sample_gst_records)
        assert report.total_records == len(sample_gst_records)
        assert report.passed is True

    def test_report_fails_with_errors(self):
        records = [
            GSTRecord(
                product_id="err_1",
                hsn_code="1006",
                cgst_rate=Decimal("-5"),
                igst_rate=Decimal("5"),
            ),
        ]
        v = Validator()
        report = v.validate(records)
        assert report.passed is False
