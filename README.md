# GST Rate Scraping & Excel Generation Tool

A modular Python CLI tool that scrapes GST goods rate data from official Indian government and reference sources, normalizes it into a structured dataset, classifies products into business categories, generates large Excel/CSV files, migrates data to MongoDB, and exposes an **MCP server** for AI-driven GST rate lookups.

## Features

- **Async scraping** — Concurrent source fetching with `httpx` and `aiosqlite` batch job tracking
- **Multi-source parsing** — HTML tables (pandas + BeautifulSoup) and PDF tables (pdfplumber + camelot)
- **HSN-based classification** — Maps all 97 HSN chapters to 5 top-level and 20+ sub-categories
- **Synthetic expansion** — Generates 100,000+ realistic product-variant rows from GST base records
- **Data validation** — Duplicate detection, conflict resolution (CBIC takes precedence), schema checks
- **Formatted Excel export** — Styled headers, auto-width columns, summary and validation sheets
- **Resumable pipeline** — SQLite-backed checkpointing after each stage
- **Fallback resilience** — Embedded 400+ entry GST dataset ensures output even when scraping fails
- **MongoDB migration** — Bulk-inserts 100K documents to MongoDB Atlas with Beanie ODM
- **MCP Server** — Model Context Protocol server for AI-driven GST rate queries (JSON responses)

## Quick Start

### 1. Install dependencies

```bash
cd gst_help_tool
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
pip install beanie motor python-dotenv  # For MongoDB & MCP
```

### 2. Configure environment

Create a `.env` file with your MongoDB credentials:

```env
MONGODB_USERNAME=your_username
MONGODB_PASSWORD=your_password
MONGODB_CLUSTER_URL=your_cluster.mongodb.net
MONGODB_DATABASE=VyapaarMitra
MONGODB_COLLECTION=gst_products
```

### 3. Run the full pipeline

```bash
./run.sh              # Full pipeline (scrape → build → export)
./run.sh fresh        # Clean previous output and run from scratch
```

Or use Python directly:

```bash
python main.py full-run --config config/config.yaml --target-rows 100000
```

### 4. Migrate to MongoDB

```bash
python migrate_to_mongo.py --drop          # Fresh migration (drops existing)
python migrate_to_mongo.py                 # Append to existing collection
python migrate_to_mongo.py --batch-size 10000  # Custom batch size
```

### 5. Start the MCP Server

```bash
python mcp_server.py          # Start MCP server (stdio transport)
python mcp_server.py --test   # Self-test all tools against MongoDB
```

### 6. Test with the MCP Client

```bash
python mcp_client.py          # Run all 8 tool tests

# Test a specific tool
python mcp_client.py --tool search_gst_by_description --args '{"search_term": "cement"}'
python mcp_client.py --tool get_gst_rate_by_product --args '{"product_name": "laptop"}'
python mcp_client.py --tool get_gst_rate_by_hsn --args '{"hsn_code": "8517"}'
python mcp_client.py --tool get_gst_categories
```

## CLI Commands

```bash
python main.py scrape           # Scrape sources only
python main.py build-products   # Normalize + classify + expand
python main.py export           # Export to Excel/CSV
python main.py status           # Check pipeline status
python main.py full-run         # Complete pipeline
```

## MCP Server Tools

The MCP server exposes 4 tools that connect to MongoDB and return structured JSON:

| Tool | Description | Example Query |
|------|-------------|---------------|
| `get_gst_rate_by_product` | Lookup GST rate by product name | `{"product_name": "laptop", "limit": 5}` |
| `search_gst_by_description` | Search by GST schedule description | `{"search_term": "motor car", "limit": 10}` |
| `get_gst_rate_by_hsn` | Lookup by HSN code (prefix match) | `{"hsn_code": "8517", "limit": 10}` |
| `get_gst_categories` | List all categories with counts | `{}` |

**Sample JSON response** (`search_gst_by_description`):

```json
{
  "query": "motor car",
  "total_results": 3,
  "entries": [
    {
      "gst_description": "Motor cars (petrol ≤1200cc, ≤4000mm)",
      "hsn_code": "8703",
      "igst_rate": 18.0,
      "cgst_rate": 9.0,
      "sgst_rate": 9.0,
      "cess_rate": 0.0,
      "top_category": "automotive",
      "sub_category": "vehicles_transport",
      "schedule": "II",
      "product_count": 245
    }
  ]
}
```

### Integrating with AI Clients

Add to your Claude Desktop / Cursor MCP settings (see `mcp_config.json`):

```json
{
  "mcpServers": {
    "gst-rate-lookup": {
      "command": "/path/to/gst_help_tool/.venv/bin/python",
      "args": ["/path/to/gst_help_tool/mcp_server.py"]
    }
  }
}
```

## Configuration

Edit `config/config.yaml` to customize:

| Section | Purpose |
|---------|---------|
| `sources` | Data source URLs, types (html/pdf), priorities |
| `network` | Timeout, retries, rate limiting, User-Agent |
| `classification` | HSN prefix → category rules, keyword overrides |
| `expansion` | Mode (synthetic/catalog), target row count |
| `export` | Output directory, filenames, sheet chunking |
| `logging` | Log level, directory, JSON format toggle |

## Project Structure

```
gst_help_tool/
├── main.py                    # CLI entry point (typer)
├── mcp_server.py              # MCP server (JSON-RPC over stdio)
├── mcp_client.py              # MCP client test script
├── migrate_to_mongo.py        # MongoDB migration (Beanie ODM)
├── mcp_config.json            # MCP client config for AI tools
├── .env                       # MongoDB credentials (gitignored)
├── config/
│   └── config.yaml            # Pipeline configuration
├── gst_scraper/
│   ├── __init__.py
│   ├── models.py              # Pydantic models, enums, exceptions
│   ├── db.py                  # SQLite async job manager
│   ├── fetcher.py             # Async HTTP fetcher (httpx)
│   ├── parser_html.py         # HTML table parser
│   ├── parser_pdf.py          # PDF table parser (dual-engine)
│   ├── normalizer.py          # Field mapping & rate conversion
│   ├── classifier.py          # HSN → category classification
│   ├── expander.py            # Synthetic product generation
│   ├── validator.py           # Data quality validation
│   ├── exporter.py            # Excel/CSV export
│   ├── fallback_data.py       # Embedded 408-entry GST fallback dataset
│   └── logger.py              # Structured logging
├── tests/
│   ├── conftest.py            # Shared fixtures
│   ├── test_normalizer.py     # Normalizer tests
│   ├── test_classifier.py     # Classifier tests
│   ├── test_validator.py      # Validator tests
│   └── test_exporter.py       # Exporter tests
├── output/                    # Generated files (gitignored)
├── run.sh                     # Shell runner script
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Output Files

After a full run, the `output/` directory contains:

| File | Description |
|------|-------------|
| `gst_products.xlsx` | Main Excel workbook with Data, Summary, and Validation sheets |
| `gst_products.csv` | CSV snapshot for machine processing |
| `validation_report.csv` | Detailed validation issues |
| `run_summary.json` | Pipeline metrics (timings, counts, errors) |
| `logs/run_*.log` | Structured JSON log files |
| `cache/` | Cached fetched source files |
| `parsed/` | Intermediate parsed JSON data |
| `checkpoints/` | Pipeline stage checkpoints (pickle) |

## Data Model

Each output row contains:

| Field | Type | Description |
|-------|------|-------------|
| `product_id` | string | Unique identifier |
| `product_name` | string | Product name (synthetic or catalog) |
| `top_category` | enum | consumer_goods, electronics, industrial, automotive, other |
| `sub_category` | enum | ~20 sub-categories (textiles_apparel, computers_electronics, etc.) |
| `hsn_code` | string | Harmonized System Nomenclature code |
| `gst_description` | string | Original GST schedule description |
| `cgst_rate` | decimal | Central GST percentage |
| `sgst_rate` | decimal | State GST percentage |
| `igst_rate` | decimal | Integrated GST percentage |
| `cess_rate` | decimal | Compensation cess percentage |
| `effective_from` | date | Effective date (when available) |
| `source_name` | string | Data source label |
| `confidence_flag` | enum | high, medium, review_required |

## Running Tests

```bash
./run.sh test                    # Via runner script
pytest tests/ -v --cov=gst_scraper  # Directly
python mcp_server.py --test      # MCP server self-test
python mcp_client.py             # MCP client integration test
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| CLI | Typer |
| HTTP | httpx (async) |
| Job DB | aiosqlite |
| Parsing | pandas, BeautifulSoup, pdfplumber, camelot-py |
| Models | Pydantic v2 |
| MongoDB | Motor (async), Beanie (ODM) |
| MCP | Custom JSON-RPC 2.0 over stdio |
| Excel | openpyxl |
| Testing | pytest |

## License

See [LICENSE](LICENSE) for details.
