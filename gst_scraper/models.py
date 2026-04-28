"""
Pydantic data models, enums, and custom exceptions for the GST scraper pipeline.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TopCategory(str, Enum):
    """Top-level product classification."""
    CONSUMER_GOODS = "consumer_goods"
    ELECTRONICS = "electronics"
    INDUSTRIAL = "industrial"
    AUTOMOTIVE = "automotive"
    OTHER = "other"


class SubCategory(str, Enum):
    """Fine-grained product sub-categories mapped from HSN chapters."""
    ANIMAL_PRODUCTS = "animal_products"
    VEGETABLE_PRODUCTS = "vegetable_products"
    FOOD_BEVERAGES = "food_beverages"
    MINERALS_FUELS = "minerals_fuels"
    CHEMICALS_PHARMA = "chemicals_pharma"
    PLASTICS_RUBBER = "plastics_rubber"
    LEATHER_GOODS = "leather_goods"
    WOOD_PAPER = "wood_paper"
    TEXTILES_APPAREL = "textiles_apparel"
    FOOTWEAR_ACCESSORIES = "footwear_accessories"
    CONSTRUCTION_MATERIALS = "construction_materials"
    JEWELRY = "jewelry"
    METALS = "metals"
    MACHINERY = "machinery"
    COMPUTERS_ELECTRONICS = "computers_electronics"
    CONSUMER_APPLIANCES = "consumer_appliances"
    VEHICLES_TRANSPORT = "vehicles_transport"
    INSTRUMENTS = "instruments"
    ARMS_AMMUNITION = "arms_ammunition"
    FURNITURE_MISC = "furniture_misc"
    ART_ANTIQUES = "art_antiques"
    UNCATEGORIZED = "uncategorized"


class ConfidenceFlag(str, Enum):
    """Data-quality confidence level."""
    HIGH = "high"
    MEDIUM = "medium"
    REVIEW_REQUIRED = "review_required"


class FetchStatus(str, Enum):
    """Status of a fetch job in the SQLite queue."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExpansionMode(str, Enum):
    """Product expansion strategy."""
    SYNTHETIC = "synthetic_mode"
    CATALOG = "catalog_mode"


class PDFEngine(str, Enum):
    """PDF parsing engine selection."""
    PDFPLUMBER = "pdfplumber"
    CAMELOT = "camelot"
    AUTO = "auto"


# ---------------------------------------------------------------------------
# Core Data Models
# ---------------------------------------------------------------------------

class GSTRecord(BaseModel):
    """Canonical GST product record matching the spec data model."""

    product_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    product_name: str = ""
    top_category: TopCategory = TopCategory.OTHER
    sub_category: SubCategory = SubCategory.UNCATEGORIZED
    hsn_code: str = ""
    gst_description: str = ""
    schedule: str = ""
    serial_no: str = ""
    cgst_rate: Decimal = Decimal("0")
    sgst_rate: Decimal = Decimal("0")
    igst_rate: Decimal = Decimal("0")
    cess_rate: Decimal = Decimal("0")
    effective_from: Optional[date] = None
    source_name: str = ""
    source_url: str = ""
    raw_text: str = ""
    confidence_flag: ConfidenceFlag = ConfidenceFlag.MEDIUM

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("cgst_rate", "sgst_rate", "igst_rate", "cess_rate", mode="before")
    @classmethod
    def coerce_rate(cls, v: Any) -> Decimal:
        """Convert rate values to Decimal, handling strings like 'Nil', 'Exempt'."""
        if v is None:
            return Decimal("0")
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        if isinstance(v, Decimal):
            return v
        s = str(v).strip().lower()
        if s in ("nil", "exempt", "exempted", "-", "", "n/a", "na"):
            return Decimal("0")
        # Handle percentage strings like "18%"
        s = s.replace("%", "").strip()
        try:
            return Decimal(s)
        except Exception:
            return Decimal("0")

    @field_validator("hsn_code", mode="before")
    @classmethod
    def clean_hsn(cls, v: Any) -> str:
        """Strip whitespace and dots from HSN codes."""
        if v is None:
            return ""
        return str(v).strip().replace(".", "").replace(" ", "")


class FetchResult(BaseModel):
    """Result from fetching a single source."""
    url: str
    status: FetchStatus
    content_path: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = 0


class ValidationIssue(BaseModel):
    """A single validation problem found in the dataset."""
    issue_type: str  # e.g. "duplicate", "missing_hsn", "negative_rate", "conflict"
    severity: str = "warning"  # "error" or "warning"
    record_id: Optional[str] = None
    hsn_code: Optional[str] = None
    description: str = ""
    source_name: Optional[str] = None


class ValidationReport(BaseModel):
    """Summary of validation results."""
    total_records: int = 0
    valid_records: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)
    duplicates_found: int = 0
    conflicts_found: int = 0
    missing_hsn_count: int = 0
    negative_rate_count: int = 0
    passed: bool = True


class RunSummary(BaseModel):
    """Pipeline run metrics."""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    raw_rows_extracted: int = 0
    normalized_rows: int = 0
    expanded_rows: int = 0
    final_export_rows: int = 0
    category_distribution: dict[str, int] = Field(default_factory=dict)
    validation_passed: bool = False
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Configuration Models
# ---------------------------------------------------------------------------

class SourceConfig(BaseModel):
    """Configuration for a single data source."""
    name: str
    url: str
    source_type: str = "html"  # "html" or "pdf"
    priority: str = "medium"   # "high", "medium", "low"
    is_primary: bool = False
    parser_config: dict[str, Any] = Field(default_factory=dict)


class NetworkConfig(BaseModel):
    """Network/HTTP settings."""
    timeout: int = 30
    retries: int = 3
    backoff_factor: float = 1.5
    crawl_delay: float = 2.0
    max_concurrent: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


class ClassificationRule(BaseModel):
    """HSN prefix to category mapping rule."""
    hsn_prefix_start: int
    hsn_prefix_end: int
    top_category: TopCategory
    sub_category: SubCategory


class ClassificationConfig(BaseModel):
    """Classification rules and keyword overrides."""
    hsn_rules: list[ClassificationRule] = Field(default_factory=list)
    keyword_overrides: dict[str, str] = Field(default_factory=dict)


class ExpansionConfig(BaseModel):
    """Product expansion settings."""
    mode: ExpansionMode = ExpansionMode.SYNTHETIC
    target_rows: int = 100_000
    catalog_input_path: Optional[str] = None


class ExportConfig(BaseModel):
    """Output export settings."""
    output_dir: str = "output"
    excel_filename: str = "gst_products.xlsx"
    csv_filename: str = "gst_products.csv"
    chunk_size: int = 500_000
    include_validation_sheet: bool = True
    include_summary_sheet: bool = True


class LoggingConfig(BaseModel):
    """Logging settings."""
    level: str = "INFO"
    log_dir: str = "output/logs"
    json_format: bool = True


class AppConfig(BaseModel):
    """Root application configuration."""
    sources: list[SourceConfig] = Field(default_factory=list)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    expansion: ExpansionConfig = Field(default_factory=ExpansionConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    db_path: str = "output/gst_scraper.db"


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class GSTScraperError(Exception):
    """Base exception for the GST scraper."""
    pass


class FetchError(GSTScraperError):
    """Raised when fetching a source fails after all retries."""

    def __init__(self, url: str, message: str = "", status_code: int | None = None):
        self.url = url
        self.status_code = status_code
        super().__init__(f"Fetch failed for {url}: {message}")


class ParseError(GSTScraperError):
    """Raised when parsing source content fails."""

    def __init__(self, source_name: str, message: str = ""):
        self.source_name = source_name
        super().__init__(f"Parse failed for {source_name}: {message}")


class EmptyExtractionError(GSTScraperError):
    """Raised when a source yields zero usable rows."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        super().__init__(f"No data extracted from {source_name}")


class SchemaValidationError(GSTScraperError):
    """Raised when records fail schema validation."""

    def __init__(self, message: str = "", errors: list[str] | None = None):
        self.errors = errors or []
        super().__init__(f"Schema validation failed: {message}")


class ExportError(GSTScraperError):
    """Raised when export to file fails."""

    def __init__(self, filepath: str, message: str = ""):
        self.filepath = filepath
        super().__init__(f"Export failed for {filepath}: {message}")
