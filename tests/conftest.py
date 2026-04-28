"""Shared pytest fixtures for GST scraper tests."""

import pytest
from decimal import Decimal

from gst_scraper.models import (
    AppConfig,
    ClassificationConfig,
    ConfidenceFlag,
    ExportConfig,
    ExpansionConfig,
    GSTRecord,
    LoggingConfig,
    NetworkConfig,
    SourceConfig,
    TopCategory,
    SubCategory,
)


@pytest.fixture
def sample_config() -> AppConfig:
    """Minimal test configuration."""
    return AppConfig(
        sources=[
            SourceConfig(
                name="Test Source",
                url="https://example.com/gst-rates",
                source_type="html",
                priority="high",
                is_primary=True,
            ),
        ],
        network=NetworkConfig(timeout=5, retries=1, crawl_delay=0),
        export=ExportConfig(output_dir="test_output"),
        logging=LoggingConfig(level="DEBUG", log_dir="test_output/logs"),
    )


@pytest.fixture
def sample_gst_records() -> list[GSTRecord]:
    """Sample GST records for testing."""
    return [
        GSTRecord(
            product_id="test_001",
            product_name="Basmati Rice 5kg",
            top_category=TopCategory.CONSUMER_GOODS,
            sub_category=SubCategory.VEGETABLE_PRODUCTS,
            hsn_code="1006",
            gst_description="Rice in the husk (paddy or rough)",
            cgst_rate=Decimal("2.5"),
            sgst_rate=Decimal("2.5"),
            igst_rate=Decimal("5"),
            cess_rate=Decimal("0"),
            source_name="CBIC GST Goods Rates",
            source_url="https://cbic-gst.gov.in/rates",
            confidence_flag=ConfidenceFlag.HIGH,
        ),
        GSTRecord(
            product_id="test_002",
            product_name="Samsung Galaxy S24",
            top_category=TopCategory.ELECTRONICS,
            sub_category=SubCategory.COMPUTERS_ELECTRONICS,
            hsn_code="8517",
            gst_description="Telephone sets, including smartphones",
            cgst_rate=Decimal("9"),
            sgst_rate=Decimal("9"),
            igst_rate=Decimal("18"),
            cess_rate=Decimal("0"),
            source_name="CBIC GST Goods Rates",
            source_url="https://cbic-gst.gov.in/rates",
            confidence_flag=ConfidenceFlag.HIGH,
        ),
        GSTRecord(
            product_id="test_003",
            product_name="Gold Necklace 22K",
            top_category=TopCategory.CONSUMER_GOODS,
            sub_category=SubCategory.JEWELRY,
            hsn_code="7113",
            gst_description="Articles of jewellery",
            cgst_rate=Decimal("1.5"),
            sgst_rate=Decimal("1.5"),
            igst_rate=Decimal("3"),
            cess_rate=Decimal("0"),
            source_name="CBIC GST Goods Rates",
            source_url="https://cbic-gst.gov.in/rates",
            confidence_flag=ConfidenceFlag.HIGH,
        ),
        GSTRecord(
            product_id="test_004",
            product_name="Cement 50kg Bag",
            top_category=TopCategory.INDUSTRIAL,
            sub_category=SubCategory.CONSTRUCTION_MATERIALS,
            hsn_code="2523",
            gst_description="Portland cement",
            cgst_rate=Decimal("14"),
            sgst_rate=Decimal("14"),
            igst_rate=Decimal("28"),
            cess_rate=Decimal("0"),
            source_name="CBIC GST Goods Rates",
            source_url="https://cbic-gst.gov.in/rates",
            confidence_flag=ConfidenceFlag.HIGH,
        ),
        GSTRecord(
            product_id="test_005",
            product_name="Cotton T-Shirt",
            top_category=TopCategory.CONSUMER_GOODS,
            sub_category=SubCategory.TEXTILES_APPAREL,
            hsn_code="6109",
            gst_description="T-shirts, singlets and other vests, knitted",
            cgst_rate=Decimal("2.5"),
            sgst_rate=Decimal("2.5"),
            igst_rate=Decimal("5"),
            cess_rate=Decimal("0"),
            source_name="CBIC GST Goods Rates",
            source_url="https://cbic-gst.gov.in/rates",
            confidence_flag=ConfidenceFlag.HIGH,
        ),
    ]


@pytest.fixture
def sample_raw_rows() -> list[dict]:
    """Sample raw parsed rows for normalizer tests."""
    return [
        {
            "sr_no": "1",
            "description": "Rice in the husk (paddy or rough)",
            "hsn_code": "1006",
            "rate": "5%",
            "_source_name": "Test Source",
            "_raw_text": "1 | Rice in the husk | 1006 | 5%",
        },
        {
            "s_no": "2",
            "description_of_goods": "Telephone sets, including smartphones",
            "hsn": "8517",
            "cgst": "9",
            "sgst": "9",
            "_source_name": "Test Source",
            "_raw_text": "2 | Telephone sets | 8517 | 9 | 9",
        },
        {
            "serial_no": "3",
            "particulars": "Articles of jewellery",
            "tariff": "71.13",
            "gst_rate": "3%",
            "_source_name": "Test Source",
            "_raw_text": "3 | Articles of jewellery | 71.13 | 3%",
        },
        {
            "no": "4",
            "description": "Exempt - Fresh milk",
            "hsn_code": "0401",
            "rate": "Nil",
            "_source_name": "Test Source",
            "_raw_text": "4 | Fresh milk | 0401 | Nil",
        },
    ]


@pytest.fixture
def sample_html_content() -> str:
    """Sample HTML with a GST rate table."""
    return """
    <html>
    <body>
        <h1>GST Rates</h1>
        <table>
            <thead>
                <tr>
                    <th>S. No.</th>
                    <th>Description</th>
                    <th>HSN Code</th>
                    <th>CGST Rate</th>
                    <th>SGST Rate</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>1</td>
                    <td>Rice</td>
                    <td>1006</td>
                    <td>2.5%</td>
                    <td>2.5%</td>
                </tr>
                <tr>
                    <td>2</td>
                    <td>Smartphones</td>
                    <td>8517</td>
                    <td>9%</td>
                    <td>9%</td>
                </tr>
                <tr>
                    <td>3</td>
                    <td>Gold Jewellery</td>
                    <td>7113</td>
                    <td>1.5%</td>
                    <td>1.5%</td>
                </tr>
                <tr>
                    <td>4</td>
                    <td>Motor Cars</td>
                    <td>8703</td>
                    <td>14%</td>
                    <td>14%</td>
                </tr>
                <tr>
                    <td>5</td>
                    <td>Cotton Textiles</td>
                    <td>5208</td>
                    <td>2.5%</td>
                    <td>2.5%</td>
                </tr>
            </tbody>
        </table>
    </body>
    </html>
    """
