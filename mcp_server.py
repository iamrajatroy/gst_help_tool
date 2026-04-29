"""
GST Rate MCP Server (FastMCP)

Model Context Protocol server for querying GST rates from MongoDB.
Uses FastMCP for standard MCP protocol compliance.

Tools:
  - get_gst_rate_by_product   → Fetch GST rate by product name
  - search_gst_by_description → Search by matching GST description terms
  - get_gst_rate_by_hsn       → Fetch GST rate by HSN code
  - get_gst_categories        → List product categories with counts

Usage:
    fastmcp run mcp_server.py          # Start MCP server
    python mcp_server.py --test        # Quick self-test
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP
from motor.motor_asyncio import AsyncIOMotorClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
MONGODB_CLUSTER_URL = os.getenv("MONGODB_CLUSTER_URL")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "VyapaarMitra")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "gst_products")

MONGO_URI = (
    f"mongodb+srv://{MONGODB_USERNAME}:{MONGODB_PASSWORD}"
    f"@{MONGODB_CLUSTER_URL}/?retryWrites=true&w=majority"
)

SERVER_NAME = "gst-rate-lookup"
SERVER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# FastMCP server instance (standard variable name for auto-discovery)
# ---------------------------------------------------------------------------
mcp = FastMCP(SERVER_NAME)

# ---------------------------------------------------------------------------
# MongoDB connection
# ---------------------------------------------------------------------------
_client: Optional[AsyncIOMotorClient] = None


async def get_collection():
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI)
    return _client[MONGODB_DATABASE][MONGODB_COLLECTION]


async def close_connection():
    global _client
    if _client:
        _client.close()
        _client = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _pick_product(doc: dict) -> dict:
    """Extract relevant fields from a MongoDB product document."""
    return {
        "product_id": doc.get("product_id", ""),
        "product_name": doc.get("product_name", ""),
        "hsn_code": doc.get("hsn_code", ""),
        "gst_description": doc.get("gst_description", ""),
        "cgst_rate": doc.get("cgst_rate", 0),
        "sgst_rate": doc.get("sgst_rate", 0),
        "igst_rate": doc.get("igst_rate", 0),
        "cess_rate": doc.get("cess_rate", 0),
        "top_category": doc.get("top_category", ""),
        "sub_category": doc.get("sub_category", ""),
        "schedule": doc.get("schedule", ""),
        "confidence_flag": doc.get("confidence_flag", ""),
    }


# ---------------------------------------------------------------------------
# MCP Tools (registered with FastMCP)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_gst_rate_by_product(product_name: str, limit: int = 5) -> str:
    """Fetch GST rate details by product name.
    Performs a case-insensitive partial match on product names in the database.
    Returns CGST, SGST, IGST rates, HSN code, category, and GST schedule description.

    Args:
        product_name: Product name to search for (e.g., 'rice', 'smartphone', 'cement', 'laptop')
        limit: Maximum results to return (default: 5, max: 20)
    """
    limit = min(max(1, limit), 20)
    col = await get_collection()

    cursor = col.find(
        {"product_name": {"$regex": product_name, "$options": "i"}},
        {"_id": 0},
    ).limit(limit)

    products = [_pick_product(doc) async for doc in cursor]

    result = {
        "query": product_name,
        "total_results": len(products),
        "products": products,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def search_gst_by_description(search_term: str, limit: int = 10) -> str:
    """Search GST products by matching terms in the official GST schedule description.
    Useful for finding GST rates for generic goods categories.
    Returns deduplicated results grouped by unique description with product counts.

    Args:
        search_term: Term to search in GST descriptions (e.g., 'milk', 'motor car', 'jewellery', 'cotton textile')
        limit: Maximum results to return (default: 10, max: 30)
    """
    limit = min(max(1, limit), 30)
    col = await get_collection()

    pipeline = [
        {"$match": {"gst_description": {"$regex": search_term, "$options": "i"}}},
        {
            "$group": {
                "_id": "$gst_description",
                "hsn_code": {"$first": "$hsn_code"},
                "igst_rate": {"$first": "$igst_rate"},
                "cgst_rate": {"$first": "$cgst_rate"},
                "sgst_rate": {"$first": "$sgst_rate"},
                "cess_rate": {"$first": "$cess_rate"},
                "top_category": {"$first": "$top_category"},
                "sub_category": {"$first": "$sub_category"},
                "schedule": {"$first": "$schedule"},
                "product_count": {"$sum": 1},
            }
        },
        {"$sort": {"product_count": -1}},
        {"$limit": limit},
    ]

    results = await col.aggregate(pipeline).to_list(length=limit)

    entries = [
        {
            "gst_description": r["_id"],
            "hsn_code": r["hsn_code"],
            "igst_rate": r["igst_rate"],
            "cgst_rate": r["cgst_rate"],
            "sgst_rate": r["sgst_rate"],
            "cess_rate": r.get("cess_rate", 0),
            "top_category": r["top_category"],
            "sub_category": r["sub_category"],
            "schedule": r["schedule"],
            "product_count": r["product_count"],
        }
        for r in results
    ]

    result = {
        "query": search_term,
        "total_results": len(entries),
        "entries": entries,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def get_gst_rate_by_hsn(hsn_code: str, limit: int = 10) -> str:
    """Fetch GST rate details by HSN (Harmonized System Nomenclature) code.
    HSN codes are hierarchical: 2-digit = chapter, 4-digit = heading, 6/8-digit = subheading.
    Searches by prefix match so partial codes work.

    Args:
        hsn_code: HSN code to look up (e.g., '8517' for smartphones, '1006' for rice, '7113' for jewellery)
        limit: Maximum results to return (default: 10, max: 20)
    """
    limit = min(max(1, limit), 20)
    col = await get_collection()

    cursor = col.find(
        {"hsn_code": {"$regex": f"^{hsn_code}"}},
        {"_id": 0},
    ).limit(limit)

    seen = set()
    products = []
    async for doc in cursor:
        key = doc.get("gst_description", "")
        if key not in seen:
            seen.add(key)
            products.append(_pick_product(doc))

    result = {
        "query": hsn_code,
        "total_results": len(products),
        "products": products,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
async def get_gst_categories() -> str:
    """List all GST product categories with product counts.
    Returns top-level categories (consumer_goods, electronics, industrial, automotive, other)
    and their sub-categories with counts. Useful for understanding available data scope.
    """
    col = await get_collection()

    pipeline = [
        {
            "$group": {
                "_id": {"top": "$top_category", "sub": "$sub_category"},
                "count": {"$sum": 1},
                "sample_hsn": {"$first": "$hsn_code"},
            }
        },
        {"$sort": {"_id.top": 1, "count": -1}},
    ]

    results = await col.aggregate(pipeline).to_list(length=100)

    categories = {}
    total = 0
    for r in results:
        top = r["_id"]["top"]
        sub = r["_id"]["sub"]
        count = r["count"]
        total += count
        if top not in categories:
            categories[top] = {"total_products": 0, "sub_categories": []}
        categories[top]["total_products"] += count
        categories[top]["sub_categories"].append({
            "name": sub,
            "product_count": count,
            "sample_hsn": r["sample_hsn"],
        })

    result = {
        "total_products": total,
        "categories": categories,
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------
async def run_self_test():
    """Quick test of all tools against the live MongoDB."""
    print("=" * 60)
    print("  GST MCP Server — Self Test")
    print("=" * 60)

    print("\n🔌 Connecting to MongoDB...")
    col = await get_collection()
    count = await col.count_documents({})
    print(f"   ✓ Collection '{MONGODB_COLLECTION}' has {count:,} documents\n")

    # Test 1: Product name search
    print("📋 Test 1: get_gst_rate_by_product('rice')")
    print("-" * 40)
    result = await get_gst_rate_by_product("rice", limit=3)
    print(result)

    # Test 2: Description search
    print("\n📋 Test 2: search_gst_by_description('motor car')")
    print("-" * 40)
    result = await search_gst_by_description("motor car", limit=3)
    print(result)

    # Test 3: HSN lookup
    print("\n📋 Test 3: get_gst_rate_by_hsn('8517')")
    print("-" * 40)
    result = await get_gst_rate_by_hsn("8517", limit=3)
    print(result)

    # Test 4: Categories
    print("\n📋 Test 4: get_gst_categories()")
    print("-" * 40)
    result = await get_gst_categories()
    print(result)

    await close_connection()
    print("✅ All tests passed!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--test" in sys.argv:
        asyncio.run(run_self_test())
    else:
        # Default to streamable-http transport on port 10000
        port = int(os.getenv("PORT", 10000))
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
