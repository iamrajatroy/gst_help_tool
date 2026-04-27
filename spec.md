# Software Specification: Python GST Rate Scraping and Excel Generation Tool

## Document Purpose
This specification defines a Python-based scraping and data processing tool that collects GST goods rate data from official and reference sources, normalizes the results, classifies products into business categories, and generates a large Excel dataset suitable for analytics or downstream enrichment.[1][2]

## Background
The official CBIC GST Goods and Services Rates page is the primary authoritative source for GST rate information for goods in India.[1] Secondary references such as ClearTax provide current slab interpretations and practical summaries, while domain-specific electronics references can help with category-level validation for product families like mobile phones, laptops, and televisions.[2][3][4]

## Objectives
- Scrape GST goods rate data from official and supporting sources.[1][2]
- Normalize HSN- and description-level tax data into a structured dataset.[1]
- Map goods into top-level categories such as consumer goods, electronics, and others.[1][3][4]
- Generate synthetic or catalog-enriched product-level records that can exceed 100,000 rows while preserving traceability to the original HSN/rate source.[1][2]
- Export the final dataset to Excel for business use.[1]

## Scope
### In Scope
- Web scraping of public GST rate tables and downloadable reference documents.[1][2]
- Parsing HTML tables and PDF-extracted tabular data where legally and technically feasible.[1][2]
- Data cleaning, normalization, classification, deduplication, and export to `.xlsx`.[1]
- Logging, retry handling, schema validation, and resumable scraping jobs.

### Out of Scope
- Legal certification of GST applicability for invoicing or tax filing.
- Real-time tax advisory or automatic interpretation of ambiguous HSN classifications.
- Private or paywalled catalog scraping.
- End-user GUI in version 1.

## Stakeholders
- Data engineering teams building GST product masters.
- Analysts requiring category-wise GST datasets.
- Internal catalog enrichment teams.
- Compliance support teams needing source-traceable HSN-rate mappings.[1]

## Primary Data Sources
| Source | Role | Priority |
|---|---|---|
| CBIC GST Goods and Services Rates page | Primary authoritative source for goods GST rates | High [1] |
| ClearTax GST rates guide | Secondary reference for slab interpretation and changes | Medium [2] |
| Electronics GST reference pages | Validation aid for electronics categories and common HSNs | Medium [3][4] |
| Product-wise GST PDFs or HSN-wise PDF lists | Supplemental extraction source when structured tables are missing | Medium [5][6] |

## Functional Requirements
### FR1: Source Acquisition
The system shall fetch HTML content from the CBIC GST goods rates page and any configured reference pages.[1] The system shall optionally download configured PDF sources for offline extraction where structured HTML coverage is incomplete.[5][6]

### FR2: Parsing
The system shall parse HTML tables using robust selectors and fallback table detection. The system shall parse PDF tabular data through a pluggable extraction layer, with OCR explicitly disabled unless separately approved because OCR may reduce accuracy.

### FR3: Normalization
The system shall normalize fields into a canonical schema including `source_name`, `source_url`, `source_date`, `schedule`, `serial_no`, `hsn_code`, `description`, `cgst_rate`, `sgst_rate`, `igst_rate`, `cess_rate`, and `effective_from`.[1][2] The system shall convert rates into numeric percentages and preserve raw source text for auditability.[1]

### FR4: Classification
The system shall classify each normalized record into top-level categories: `consumer_goods`, `electronics`, or `other`. Classification shall use a combination of HSN chapter rules from official schedules and keyword-based overrides informed by domain references for electronics-oriented products.[1][3][4]

### FR5: Product Expansion
The system shall support two expansion modes:
- `catalog_mode`: enrich existing input SKUs with GST mappings.
- `synthetic_mode`: generate product-variant rows from HSN descriptions and category templates to create a large analytics dataset above 100,000 rows.[1][2]

### FR6: Validation
The system shall detect duplicate HSN-description-rate combinations, missing rate fields, malformed HSN codes, and conflicting mappings across sources. Conflicts shall be flagged for manual review and the official CBIC source shall take precedence when discrepancies exist.[1][2]

### FR7: Export
The system shall export:
- Excel workbook (`.xlsx`) containing the final dataset.
- CSV snapshot for machine processing.
- Run log and exception report for traceability.

### FR8: Observability
The system shall record job start/end time, source fetch results, parser success/failure counts, normalization counts, category distribution, and final row counts.

## Non-Functional Requirements
### Performance
- The tool should process at least 100,000 expanded rows in a single batch run on a standard developer machine with 8 GB RAM.
- A full scrape-and-build run should complete within 30 minutes under normal network conditions.

### Reliability
- Source requests shall use retry with exponential backoff.
- Partial failures in secondary sources shall not block export if the primary source has been processed.
- The pipeline shall support checkpointing after acquisition, normalization, and expansion stages.

### Maintainability
- The system shall be modular, with separate packages for acquisition, parsing, normalization, classification, expansion, validation, and export.
- Source-specific parsers shall be configurable and isolated to minimize breakage from site layout changes.

### Security and Compliance
- The scraper shall respect robots.txt and site terms where applicable.
- The tool shall avoid aggressive concurrency against government domains.
- No personal data shall be collected or stored.

## System Architecture
### Components
1. `config` — YAML/JSON configuration for sources, selectors, category rules, and output paths.
2. `fetcher` — HTTP client with retries, caching, headers, and rate limiting.
3. `parser_html` — HTML table extraction using `pandas.read_html` and BeautifulSoup fallback.
4. `parser_pdf` — PDF extraction adapter using Camelot/Tabula/pdfplumber where applicable.
5. `normalizer` — canonical field mapping and datatype cleanup.
6. `classifier` — HSN chapter mapping plus keyword overrides for product families.[1][3][4]
7. `expander` — synthetic product variant generation or catalog enrichment engine.
8. `validator` — rule checks, duplicate detection, conflict flags.
9. `exporter` — Excel/CSV writer using pandas and openpyxl.
10. `logger` — structured logs and run summaries.

### Processing Flow
1. Load configuration.
2. Fetch source pages and files.[1][5][6]
3. Parse raw tables.
4. Normalize into canonical schema.[1]
5. Validate base GST records.
6. Classify into business categories.[1][3][4]
7. Expand to product-level rows if requested.
8. Run final validation and generate reports.
9. Export `.xlsx` and `.csv`.

## Suggested Tech Stack
| Layer | Recommendation |
|---|---|
| Language | Python 3.11+ |
| HTTP | `requests`, optional `httpx` |
| HTML Parsing | `BeautifulSoup4`, `lxml`, `pandas.read_html` |
| PDF Parsing | `pdfplumber`, `camelot`, optional `tabula-py` |
| Data Processing | `pandas`, `numpy` |
| Excel Export | `openpyxl`, `xlsxwriter` |
| CLI | `typer` or `argparse` |
| Validation | `pydantic` or schema checks in pandas |
| Logging | `logging` with JSON formatter |
| Testing | `pytest` |

## Canonical Data Model
| Field | Type | Description |
|---|---|---|
| product_id | string | Unique generated identifier |
| product_name | string | Catalog or synthetic product name |
| top_category | enum | `consumer_goods`, `electronics`, `other` |
| sub_category | string | Optional finer grouping |
| hsn_code | string | Normalized HSN code |
| gst_description | string | Source GST description text |
| schedule | string | GST schedule bucket if present |
| serial_no | string | Serial number from source table |
| cgst_rate | decimal | CGST percentage |
| sgst_rate | decimal | SGST percentage |
| igst_rate | decimal | IGST percentage |
| cess_rate | decimal | Cess percentage if applicable |
| effective_from | date | Effective date when available |
| source_name | string | Source system label |
| source_url | string | Source URL |
| raw_text | string | Original extracted row text |
| confidence_flag | string | `high`, `medium`, `review_required` |

## Category Mapping Rules
### Consumer Goods
Likely includes food items, packaged goods, personal care, apparel, footwear, and household products based on HSN chapters commonly associated with retail consumption categories in the GST schedules.[1]

### Electronics
Likely includes HSN groups covering computers, mobile devices, televisions, consumer appliances, and accessories; electronics-specific references can be used to validate rules for common items such as mobiles, laptops, and TVs.[3][4]

### Other
Includes industrial materials, chemicals, construction goods, components, and uncategorized entries not covered by the first two classes.[1]

## Configuration Requirements
The tool shall accept configuration for:
- Source URLs and parser types.
- Request timeout, retry count, and crawl delay.
- Category mapping rules by HSN prefix.
- Keyword override dictionaries.
- Expansion templates and target row count.
- Output file names and directories.
- Logging level.

Example configuration blocks should include:
- `sources`
- `network`
- `classification`
- `expansion`
- `export`
- `logging`

## Command-Line Interface
Example commands:

```bash
python main.py scrape --config config.yaml
python main.py build-products --config config.yaml --target-rows 100000
python main.py export --config config.yaml --format xlsx
python main.py full-run --config config.yaml
```

## Error Handling
The system shall define explicit exception classes for:
- Network failures
- Source format changes
- Empty extraction results
- Schema validation failures
- Export failures

On parser failure for a non-primary source, the system shall continue and mark the source as failed in the run report. On parser failure for the primary CBIC source, the run shall stop unless `--allow-secondary-only` is explicitly enabled.[1]

## Logging and Auditability
Each run shall produce:
- A timestamped log file.
- A source acquisition report.
- A validation report listing conflicts and null rates.
- A run summary with counts by category and source.
- Optional row-level lineage linking each output record to source URL and extraction timestamp.[1]

## Testing Requirements
### Unit Tests
- HSN parsing and normalization.
- Rate extraction and numeric conversion.
- Category mapping by HSN prefix.
- Keyword override precedence.
- Excel export schema integrity.

### Integration Tests
- Live fetch smoke test against configured public sources.
- End-to-end pipeline from scrape to export using a reduced sample.
- Parser regression tests using stored HTML/PDF fixtures.

### Data Quality Tests
- No blank `hsn_code` in accepted final rows.
- No negative GST values.
- Duplicate rate rows detected and reported.
- Category values constrained to allowed enums.
- Final output row count meets configured threshold in synthetic mode.

## Deliverables
Version 1 shall deliver:
- Python source code repository.
- Configuration template.
- Markdown setup and usage guide.
- Excel and CSV output artifacts.
- Test suite.
- Sample run log and validation report.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Source HTML structure changes | Parser breakage | Use parser abstraction, fallback selectors, regression fixtures |
| PDF table extraction quality issues | Misparsed rows | Keep PDF extraction optional, store raw text, require review flag |
| Conflicting rates across secondary sources | Data inconsistency | Prioritize CBIC and flag discrepancies for review [1][2] |
| Synthetic product generation creates unrealistic names | Low data usability | Keep template dictionaries versioned and category-specific |
| Very large Excel files become slow | Usability issues | Offer CSV export and chunked workbook sheets |

## Acceptance Criteria
The system will be accepted when it:
- Successfully extracts GST rate data from the configured CBIC goods rate source.[1]
- Produces a normalized dataset with correct rate columns and source lineage.[1]
- Correctly classifies records into consumer goods, electronics, and other categories using configured rules.[1][3][4]
- Generates an Excel file exceeding 100,000 product-level rows in synthetic or enriched mode.
- Produces logs and validation reports for the full run.
- Passes unit and integration test suites.

## Recommended Project Structure
```text
python-gst-scraper/
├── main.py
├── config/
│   └── config.yaml
├── gst_scraper/
│   ├── fetcher.py
│   ├── parser_html.py
│   ├── parser_pdf.py
│   ├── normalizer.py
│   ├── classifier.py
│   ├── expander.py
│   ├── validator.py
│   ├── exporter.py
│   └── models.py
├── tests/
├── output/
└── README.md
```

## Future Enhancements
- Scheduled runs via Airflow or cron.
- Database persistence to PostgreSQL.
- Streamlit or FastAPI front end.
- HSN search API.
- Delta comparison between successive GST notification snapshots.[1][2]
