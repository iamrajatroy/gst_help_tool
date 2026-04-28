"""Tests for the Normalizer module."""

from decimal import Decimal

import pytest

from gst_scraper.models import ConfidenceFlag, GSTRecord
from gst_scraper.normalizer import Normalizer


class TestRateConversion:
    """Test rate string → Decimal conversion."""

    def test_numeric_rate(self):
        n = Normalizer()
        assert n._parse_rate("18") == Decimal("18")

    def test_percentage_rate(self):
        n = Normalizer()
        assert n._parse_rate("18%") == Decimal("18")

    def test_nil_rate(self):
        n = Normalizer()
        assert n._parse_rate("Nil") == Decimal("0")

    def test_exempt_rate(self):
        n = Normalizer()
        assert n._parse_rate("Exempt") == Decimal("0")

    def test_free_rate(self):
        n = Normalizer()
        assert n._parse_rate("Free") == Decimal("0")

    def test_none_rate(self):
        n = Normalizer()
        assert n._parse_rate(None) == Decimal("0")

    def test_empty_rate(self):
        n = Normalizer()
        assert n._parse_rate("") == Decimal("0")

    def test_dash_rate(self):
        n = Normalizer()
        assert n._parse_rate("-") == Decimal("0")

    def test_float_rate(self):
        n = Normalizer()
        assert n._parse_rate("2.5") == Decimal("2.5")

    def test_range_rate_takes_first(self):
        n = Normalizer()
        assert n._parse_rate("5% to 12%") == Decimal("5")

    def test_integer_input(self):
        n = Normalizer()
        assert n._parse_rate(18) == Decimal("18")

    def test_float_input(self):
        n = Normalizer()
        assert n._parse_rate(2.5) == Decimal("2.5")


class TestHSNCleaning:
    """Test HSN code normalization."""

    def test_clean_hsn_normal(self):
        assert Normalizer._clean_hsn("1006") == "1006"

    def test_clean_hsn_with_dots(self):
        assert Normalizer._clean_hsn("71.13") == "7113"

    def test_clean_hsn_with_spaces(self):
        assert Normalizer._clean_hsn("85 17") == "8517"

    def test_clean_hsn_with_prefix(self):
        assert Normalizer._clean_hsn("Chapter 01") == "01"

    def test_clean_hsn_none(self):
        assert Normalizer._clean_hsn(None) == ""

    def test_clean_hsn_empty(self):
        assert Normalizer._clean_hsn("") == ""

    def test_clean_hsn_with_dashes(self):
        assert Normalizer._clean_hsn("84-51") == "8451"


class TestNormalization:
    """Test full row normalization."""

    def test_normalize_basic_row(self, sample_raw_rows):
        n = Normalizer(source_name="Test", source_url="https://test.com")
        records = n.normalize([sample_raw_rows[0]])
        assert len(records) == 1
        rec = records[0]
        assert rec.hsn_code == "1006"
        assert rec.igst_rate == Decimal("5")
        assert rec.cgst_rate == Decimal("2.5")
        assert rec.sgst_rate == Decimal("2.5")

    def test_normalize_cgst_sgst_fields(self, sample_raw_rows):
        n = Normalizer(source_name="Test", source_url="https://test.com")
        records = n.normalize([sample_raw_rows[1]])
        assert len(records) == 1
        rec = records[0]
        assert rec.hsn_code == "8517"
        assert rec.cgst_rate == Decimal("9")
        assert rec.sgst_rate == Decimal("9")
        assert rec.igst_rate == Decimal("18")

    def test_normalize_dotted_hsn(self, sample_raw_rows):
        n = Normalizer()
        records = n.normalize([sample_raw_rows[2]])
        assert len(records) == 1
        assert records[0].hsn_code == "7113"

    def test_normalize_nil_rate(self, sample_raw_rows):
        n = Normalizer()
        records = n.normalize([sample_raw_rows[3]])
        assert len(records) == 1
        rec = records[0]
        assert rec.igst_rate == Decimal("0")
        assert rec.cgst_rate == Decimal("0")

    def test_normalize_skips_empty_rows(self):
        n = Normalizer()
        rows = [{"col1": "", "col2": ""}]
        records = n.normalize(rows)
        assert len(records) == 0

    def test_normalize_preserves_raw_text(self, sample_raw_rows):
        n = Normalizer()
        records = n.normalize([sample_raw_rows[0]])
        assert records[0].raw_text != ""

    def test_confidence_high_with_complete_data(self):
        n = Normalizer()
        flag = n._assess_confidence("1006", "Rice", Decimal("2.5"), Decimal("2.5"), Decimal("5"))
        assert flag == ConfidenceFlag.HIGH

    def test_confidence_review_with_missing_data(self):
        n = Normalizer()
        flag = n._assess_confidence("", "", Decimal("0"), Decimal("0"), Decimal("0"))
        assert flag == ConfidenceFlag.REVIEW_REQUIRED

    def test_batch_normalize(self, sample_raw_rows):
        n = Normalizer(source_name="Batch Test")
        records = n.normalize(sample_raw_rows)
        assert len(records) == 4
