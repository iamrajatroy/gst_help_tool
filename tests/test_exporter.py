"""Tests for the Exporter module."""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from gst_scraper.exporter import Exporter
from gst_scraper.models import ExportConfig, GSTRecord, ValidationReport, ValidationIssue


@pytest.fixture
def test_output_dir(tmp_path):
    """Temporary output directory for tests."""
    return str(tmp_path / "test_export")


@pytest.fixture
def exporter(test_output_dir):
    """Exporter with test output directory."""
    config = ExportConfig(output_dir=test_output_dir)
    return Exporter(config)


class TestExcelExport:
    """Test Excel file generation."""

    def test_export_creates_xlsx(self, exporter, sample_gst_records, test_output_dir):
        path = exporter.export_excel(sample_gst_records)
        assert path.exists()
        assert path.suffix == ".xlsx"

    def test_export_correct_row_count(self, exporter, sample_gst_records):
        path = exporter.export_excel(sample_gst_records)
        df = pd.read_excel(path)
        assert len(df) == len(sample_gst_records)

    def test_export_has_all_columns(self, exporter, sample_gst_records):
        path = exporter.export_excel(sample_gst_records)
        df = pd.read_excel(path)
        expected_cols = {
            "product_id", "product_name", "top_category", "sub_category",
            "hsn_code", "gst_description", "cgst_rate", "sgst_rate",
            "igst_rate", "cess_rate", "source_name",
        }
        assert expected_cols.issubset(set(df.columns))

    def test_export_with_validation_sheet(self, exporter, sample_gst_records):
        report = ValidationReport(
            total_records=5,
            valid_records=4,
            issues=[
                ValidationIssue(
                    issue_type="test",
                    severity="warning",
                    description="Test issue",
                )
            ],
        )
        path = exporter.export_excel(sample_gst_records, validation_report=report)
        # Check that validation sheet exists
        xl = pd.ExcelFile(path)
        assert "Validation Report" in xl.sheet_names


class TestCSVExport:
    """Test CSV file generation."""

    def test_export_creates_csv(self, exporter, sample_gst_records):
        path = exporter.export_csv(sample_gst_records)
        assert path.exists()
        assert path.suffix == ".csv"

    def test_csv_correct_row_count(self, exporter, sample_gst_records):
        path = exporter.export_csv(sample_gst_records)
        df = pd.read_csv(path)
        assert len(df) == len(sample_gst_records)


class TestExportAll:
    """Test combined export."""

    def test_export_all_returns_paths(self, exporter, sample_gst_records):
        outputs = exporter.export_all(sample_gst_records)
        assert "xlsx" in outputs
        assert "csv" in outputs
        assert Path(outputs["xlsx"]).exists()
        assert Path(outputs["csv"]).exists()


class TestDataIntegrity:
    """Test that exported data maintains integrity."""

    def test_rates_are_numeric(self, exporter, sample_gst_records):
        path = exporter.export_csv(sample_gst_records)
        df = pd.read_csv(path)
        assert pd.api.types.is_numeric_dtype(df["cgst_rate"])
        assert pd.api.types.is_numeric_dtype(df["sgst_rate"])
        assert pd.api.types.is_numeric_dtype(df["igst_rate"])

    def test_no_missing_hsn_in_data(self, exporter, sample_gst_records):
        path = exporter.export_csv(sample_gst_records)
        df = pd.read_csv(path)
        # All sample records should have HSN codes
        assert df["hsn_code"].notna().all()

    def test_category_values_valid(self, exporter, sample_gst_records):
        path = exporter.export_csv(sample_gst_records)
        df = pd.read_csv(path)
        valid_categories = {"consumer_goods", "electronics", "industrial", "automotive", "other"}
        assert set(df["top_category"].unique()).issubset(valid_categories)
