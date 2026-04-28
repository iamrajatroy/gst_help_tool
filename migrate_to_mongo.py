"""
GST Products → MongoDB Migration Script (Beanie ODM)

Reads the "GST Products" sheet from the generated Excel file and
bulk-inserts all rows into a MongoDB collection using Beanie.

Usage:
    python migrate_to_mongo.py
    python migrate_to_mongo.py --file output/gst_products.xlsx --batch-size 5000 --drop
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time
from datetime import datetime
from typing import Optional

import pandas as pd
from beanie import Document, init_beanie
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import Field

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
load_dotenv()

MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
MONGODB_CLUSTER_URL = os.getenv("MONGODB_CLUSTER_URL")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "VyapaarMitra")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "gst_products")

if not all([MONGODB_USERNAME, MONGODB_PASSWORD, MONGODB_CLUSTER_URL]):
    print("❌ Missing MongoDB credentials in .env file")
    print("Required: MONGODB_USERNAME, MONGODB_PASSWORD, MONGODB_CLUSTER_URL")
    sys.exit(1)

MONGO_URI = (
    f"mongodb+srv://{MONGODB_USERNAME}:{MONGODB_PASSWORD}"
    f"@{MONGODB_CLUSTER_URL}/?retryWrites=true&w=majority"
)


# ---------------------------------------------------------------------------
# Beanie Document Model
# ---------------------------------------------------------------------------
class GSTProduct(Document):
    """MongoDB document model for GST product records."""

    product_id: str = Field(..., description="Unique product identifier")
    product_name: str = Field(..., description="Product name")
    top_category: str = Field(..., description="Top-level category (consumer_goods, electronics, etc.)")
    sub_category: str = Field(..., description="Sub-category (textiles_apparel, chemicals_pharma, etc.)")
    hsn_code: str = Field(..., description="HSN code")
    gst_description: str = Field(default="", description="GST schedule description")
    schedule: Optional[str] = Field(default=None, description="GST schedule number")
    serial_no: Optional[str] = Field(default=None, description="Serial number in schedule")
    cgst_rate: float = Field(default=0.0, description="Central GST rate (%)")
    sgst_rate: float = Field(default=0.0, description="State GST rate (%)")
    igst_rate: float = Field(default=0.0, description="Integrated GST rate (%)")
    cess_rate: float = Field(default=0.0, description="Compensation cess rate (%)")
    effective_from: Optional[str] = Field(default=None, description="Effective date")
    source_name: str = Field(default="", description="Data source label")
    source_url: Optional[str] = Field(default=None, description="Data source URL")
    confidence_flag: str = Field(default="medium", description="Data quality flag")
    migrated_at: datetime = Field(default_factory=datetime.utcnow, description="Migration timestamp")

    class Settings:
        name = MONGODB_COLLECTION
        indexes = [
            "product_id",
            "hsn_code",
            "top_category",
            "sub_category",
            [("hsn_code", 1), ("igst_rate", 1)],
        ]


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------
def clean_value(val):
    """Convert NaN and numpy types to Python-native types."""
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return val
    return str(val)


def row_to_document(row: dict) -> GSTProduct:
    """Convert a pandas row dict to a GSTProduct Beanie document."""
    return GSTProduct(
        product_id=str(clean_value(row.get("product_id", "")) or ""),
        product_name=str(clean_value(row.get("product_name", "")) or ""),
        top_category=str(clean_value(row.get("top_category", "other")) or "other"),
        sub_category=str(clean_value(row.get("sub_category", "uncategorized")) or "uncategorized"),
        hsn_code=str(clean_value(row.get("hsn_code", "")) or ""),
        gst_description=str(clean_value(row.get("gst_description", "")) or ""),
        schedule=str(clean_value(row.get("schedule"))) if clean_value(row.get("schedule")) else None,
        serial_no=str(clean_value(row.get("serial_no"))) if clean_value(row.get("serial_no")) else None,
        cgst_rate=float(clean_value(row.get("cgst_rate", 0)) or 0),
        sgst_rate=float(clean_value(row.get("sgst_rate", 0)) or 0),
        igst_rate=float(clean_value(row.get("igst_rate", 0)) or 0),
        cess_rate=float(clean_value(row.get("cess_rate", 0)) or 0),
        effective_from=str(clean_value(row.get("effective_from"))) if clean_value(row.get("effective_from")) else None,
        source_name=str(clean_value(row.get("source_name", "")) or ""),
        source_url=str(clean_value(row.get("source_url"))) if clean_value(row.get("source_url")) else None,
        confidence_flag=str(clean_value(row.get("confidence_flag", "medium")) or "medium"),
    )


async def migrate(
    excel_path: str = "output/gst_products.xlsx",
    sheet_name: str = "GST Products",
    batch_size: int = 5000,
    drop_existing: bool = False,
):
    """
    Main migration coroutine.

    Args:
        excel_path: Path to the Excel file
        sheet_name: Sheet name to read
        batch_size: Number of documents per bulk insert
        drop_existing: If True, drop the collection before inserting
    """
    print("=" * 60)
    print("  GST Products → MongoDB Migration (Beanie)")
    print("=" * 60)

    # ── Read Excel ──────────────────────────────────────────────
    print(f"\n📖 Reading '{sheet_name}' from {excel_path}...")
    t0 = time.time()
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    read_time = time.time() - t0
    print(f"   Loaded {len(df):,} rows in {read_time:.1f}s")

    # ── Connect to MongoDB ──────────────────────────────────────
    print(f"\n🔌 Connecting to MongoDB Atlas ({MONGODB_CLUSTER_URL})...")
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[MONGODB_DATABASE]

    # Initialize Beanie with our document model
    await init_beanie(database=db, document_models=[GSTProduct])
    print(f"   ✓ Connected to database '{MONGODB_DATABASE}'")
    print(f"   ✓ Collection: '{MONGODB_COLLECTION}'")

    # ── Drop existing if requested ──────────────────────────────
    if drop_existing:
        existing_count = await GSTProduct.count()
        if existing_count > 0:
            print(f"\n🗑  Dropping existing {existing_count:,} documents...")
            await GSTProduct.delete_all()
            print("   ✓ Collection cleared")

    # ── Batch insert ────────────────────────────────────────────
    total_rows = len(df)
    num_batches = math.ceil(total_rows / batch_size)
    print(f"\n📤 Inserting {total_rows:,} documents in {num_batches} batches (batch_size={batch_size})...")

    inserted = 0
    failed = 0
    t_start = time.time()

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total_rows)
        batch_df = df.iloc[start:end]

        # Convert rows to Beanie documents
        documents = []
        for _, row in batch_df.iterrows():
            try:
                doc = row_to_document(row.to_dict())
                documents.append(doc)
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"   ⚠ Row {start + _} failed: {e}")

        # Bulk insert
        if documents:
            await GSTProduct.insert_many(documents)
            inserted += len(documents)

        # Progress
        elapsed = time.time() - t_start
        rate = inserted / elapsed if elapsed > 0 else 0
        pct = (end / total_rows) * 100
        print(f"   [{batch_idx + 1}/{num_batches}] {end:,}/{total_rows:,} ({pct:.0f}%) — {rate:,.0f} docs/sec", end="\r")

    print()  # newline after progress

    # ── Create indexes ──────────────────────────────────────────
    print("\n📇 Ensuring indexes...")
    # Beanie auto-creates indexes defined in Settings, but we trigger it explicitly
    collection = db[MONGODB_COLLECTION]
    await collection.create_index("product_id")
    await collection.create_index("hsn_code")
    await collection.create_index("top_category")
    await collection.create_index("sub_category")
    await collection.create_index([("hsn_code", 1), ("igst_rate", 1)])
    await collection.create_index([("top_category", 1), ("sub_category", 1)])
    print("   ✓ Indexes created (product_id, hsn_code, categories, composite)")

    # ── Verify ──────────────────────────────────────────────────
    final_count = await GSTProduct.count()
    total_time = time.time() - t_start

    print(f"\n{'=' * 60}")
    print(f"  ✅ Migration complete!")
    print(f"     Documents inserted: {inserted:,}")
    print(f"     Failed rows:        {failed}")
    print(f"     Total in collection: {final_count:,}")
    print(f"     Time:               {total_time:.1f}s")
    print(f"     Rate:               {inserted / total_time:,.0f} docs/sec")
    print(f"{'=' * 60}")

    # ── Sample verification ─────────────────────────────────────
    print("\n📊 Sample verification:")
    sample = await GSTProduct.find_one(GSTProduct.hsn_code == "8517")
    if sample:
        print(f"   HSN 8517: {sample.product_name} | IGST {sample.igst_rate}% | {sample.top_category}")

    # Category distribution
    pipeline = [
        {"$group": {"_id": "$top_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    dist = await collection.aggregate(pipeline).to_list(length=10)
    print("\n   Category distribution:")
    for d in dist:
        print(f"     {d['_id']}: {d['count']:,}")

    client.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate GST Products Excel to MongoDB")
    parser.add_argument(
        "--file", "-f",
        default="output/gst_products.xlsx",
        help="Path to Excel file (default: output/gst_products.xlsx)",
    )
    parser.add_argument(
        "--sheet", "-s",
        default="GST Products",
        help="Sheet name to read (default: 'GST Products')",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=5000,
        help="Batch size for bulk inserts (default: 5000)",
    )
    parser.add_argument(
        "--drop", "-d",
        action="store_true",
        help="Drop existing collection before inserting",
    )

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ File not found: {args.file}")
        sys.exit(1)

    asyncio.run(migrate(
        excel_path=args.file,
        sheet_name=args.sheet,
        batch_size=args.batch_size,
        drop_existing=args.drop,
    ))


if __name__ == "__main__":
    main()
