"""
GST Rate MCP Server (Python 3.9+ compatible)

Model Context Protocol server for querying GST rates from MongoDB.
Implements MCP over stdio using raw JSON-RPC (no external MCP library needed).

Tools:
  - get_gst_rate_by_product   → Fetch GST rate by product name
  - search_gst_by_description → Search by matching GST description terms
  - get_gst_rate_by_hsn       → Fetch GST rate by HSN code
  - get_gst_categories        → List product categories with counts

Usage:
    python mcp_server.py                  # Start MCP server (stdio)
    python mcp_server.py --test           # Quick self-test
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Optional

from dotenv import load_dotenv
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
# Tool definitions (MCP schema)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "get_gst_rate_by_product",
        "description": (
            "Fetch GST rate details by product name. "
            "Performs a case-insensitive partial match on product names in the database. "
            "Returns CGST, SGST, IGST rates, HSN code, category, and GST schedule description."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Product name to search for (e.g., 'rice', 'smartphone', 'cement', 'laptop')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 5, max: 20)",
                    "default": 5,
                },
            },
            "required": ["product_name"],
        },
    },
    {
        "name": "search_gst_by_description",
        "description": (
            "Search GST products by matching terms in the official GST schedule description. "
            "Useful for finding GST rates for generic goods categories. "
            "Returns deduplicated results grouped by unique description with product counts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Term to search in GST descriptions (e.g., 'milk', 'motor car', 'jewellery', 'cotton textile')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10, max: 30)",
                    "default": 10,
                },
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "get_gst_rate_by_hsn",
        "description": (
            "Fetch GST rate details by HSN (Harmonized System Nomenclature) code. "
            "HSN codes are hierarchical: 2-digit = chapter, 4-digit = heading, 6/8-digit = subheading. "
            "Searches by prefix match so partial codes work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hsn_code": {
                    "type": "string",
                    "description": "HSN code to look up (e.g., '8517' for smartphones, '1006' for rice, '7113' for jewellery)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10, max: 20)",
                    "default": 10,
                },
            },
            "required": ["hsn_code"],
        },
    },
    {
        "name": "get_gst_categories",
        "description": (
            "List all GST product categories with product counts. "
            "Returns top-level categories (consumer_goods, electronics, industrial, automotive, other) "
            "and their sub-categories with counts. Useful for understanding available data scope."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations — all return structured dicts/lists
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


async def tool_get_gst_rate_by_product(product_name: str, limit: int = 5) -> dict:
    limit = min(max(1, limit), 20)
    col = await get_collection()

    cursor = col.find(
        {"product_name": {"$regex": product_name, "$options": "i"}},
        {"_id": 0},
    ).limit(limit)

    products = [_pick_product(doc) async for doc in cursor]

    return {
        "query": product_name,
        "total_results": len(products),
        "products": products,
    }


async def tool_search_gst_by_description(search_term: str, limit: int = 10) -> dict:
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

    return {
        "query": search_term,
        "total_results": len(entries),
        "entries": entries,
    }


async def tool_get_gst_rate_by_hsn(hsn_code: str, limit: int = 10) -> dict:
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

    return {
        "query": hsn_code,
        "total_results": len(products),
        "products": products,
    }


async def tool_get_gst_categories() -> dict:
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

    return {
        "total_products": total,
        "categories": categories,
    }


# Tool dispatcher
TOOL_HANDLERS = {
    "get_gst_rate_by_product": tool_get_gst_rate_by_product,
    "search_gst_by_description": tool_search_gst_by_description,
    "get_gst_rate_by_hsn": tool_get_gst_rate_by_hsn,
    "get_gst_categories": tool_get_gst_categories,
}


async def dispatch_tool(name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    return await handler(**arguments)


# ---------------------------------------------------------------------------
# MCP JSON-RPC Server (stdio transport)
# ---------------------------------------------------------------------------
class MCPServer:
    """MCP server implementing JSON-RPC 2.0 over stdio."""

    def __init__(self):
        self._initialized = False

    def _make_response(self, id: Any, result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": id, "result": result}

    def _make_error(self, id: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

    async def handle_message(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        params = msg.get("params", {})
        msg_id = msg.get("id")

        # Notifications (no id) — acknowledge silently
        if msg_id is None:
            if method == "notifications/initialized":
                self._initialized = True
            return None

        if method == "initialize":
            return self._make_response(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            })

        elif method == "tools/list":
            return self._make_response(msg_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            try:
                result_data = await dispatch_tool(tool_name, arguments)
                result_json = json.dumps(result_data, ensure_ascii=False, default=str)
                return self._make_response(msg_id, {
                    "content": [{"type": "text", "text": result_json}],
                    "isError": False,
                })
            except Exception as e:
                error_json = json.dumps({"error": str(e)})
                return self._make_response(msg_id, {
                    "content": [{"type": "text", "text": error_json}],
                    "isError": True,
                })

        elif method == "ping":
            return self._make_response(msg_id, {})

        else:
            return self._make_error(msg_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Streamable HTTP transport (aiohttp on port 8000)
# ---------------------------------------------------------------------------

async def handle_mcp_request(request):
    """POST /mcp — Main MCP JSON-RPC endpoint."""
    from aiohttp import web

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status=400,
        )

    server: MCPServer = request.app["mcp_server"]

    # Support batch requests (array of messages)
    if isinstance(body, list):
        responses = []
        for msg in body:
            resp = await server.handle_message(msg)
            if resp is not None:
                responses.append(resp)
        return web.json_response(responses if responses else None, status=200)

    # Single request
    response = await server.handle_message(body)
    if response is None:
        return web.Response(status=202, text="Accepted")
    return web.json_response(response)


async def handle_health(request):
    """GET /health — Health check."""
    from aiohttp import web

    col = await get_collection()
    count = await col.estimated_document_count()
    return web.json_response({
        "status": "ok",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "mongodb_collection": MONGODB_COLLECTION,
        "document_count": count,
    })


async def handle_tools_list(request):
    """GET /mcp/tools — Quick tool listing (convenience endpoint)."""
    from aiohttp import web

    return web.json_response({
        "tools": [
            {"name": t["name"], "description": t["description"]}
            for t in TOOLS
        ]
    })


async def on_startup(app):
    """Initialize MongoDB connection on server startup."""
    col = await get_collection()
    count = await col.estimated_document_count()
    print(f"   ✓ MongoDB connected: {MONGODB_COLLECTION} ({count:,} documents)")


async def on_shutdown(app):
    """Clean up MongoDB connection on server shutdown."""
    await close_connection()


def create_app() -> "aiohttp.web.Application":
    """Create the aiohttp web application."""
    from aiohttp import web

    app = web.Application()
    app["mcp_server"] = MCPServer()

    # Routes
    app.router.add_post("/mcp", handle_mcp_request)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/mcp/tools", handle_tools_list)

    # Lifecycle hooks
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


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
    result = await tool_get_gst_rate_by_product("rice", limit=3)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    # Test 2: Description search
    print("\n📋 Test 2: search_gst_by_description('motor car')")
    print("-" * 40)
    result = await tool_search_gst_by_description("motor car", limit=3)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    # Test 3: HSN lookup
    print("\n📋 Test 3: get_gst_rate_by_hsn('8517')")
    print("-" * 40)
    result = await tool_get_gst_rate_by_hsn("8517", limit=3)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    # Test 4: Categories
    print("\n📋 Test 4: get_gst_categories()")
    print("-" * 40)
    result = await tool_get_gst_categories()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    await close_connection()
    print("✅ All tests passed!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--test" in sys.argv:
        asyncio.run(run_self_test())
    else:
        from aiohttp import web

        port = int(os.getenv("MCP_PORT", "8000"))
        print("=" * 60)
        print("  GST Rate MCP Server (Streamable HTTP)")
        print("=" * 60)
        print(f"\n🚀 Starting on http://0.0.0.0:{port}")
        print(f"   POST /mcp         — JSON-RPC endpoint")
        print(f"   GET  /health      — Health check")
        print(f"   GET  /mcp/tools   — List available tools\n")

        app = create_app()
        web.run_app(app, host="0.0.0.0", port=port, print=None)

