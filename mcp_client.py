"""
MCP Client — Test script for the GST Rate MCP Server (HTTP)

Connects to the MCP server over HTTP and exercises all 4 tools.

Usage:
    python mcp_client.py
    python mcp_client.py --url http://localhost:8000
    python mcp_client.py --tool get_gst_rate_by_product --args '{"product_name": "laptop"}'
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# MCP Client (JSON-RPC over HTTP)
# ---------------------------------------------------------------------------
class MCPClient:
    """Connects to an MCP server over HTTP."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/mcp"
        self._request_id = 0
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self._http.aclose()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send(self, method: str, params: dict | None = None, is_notification: bool = False) -> dict | None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        if not is_notification:
            msg["id"] = self._next_id()

        resp = await self._http.post(self.endpoint, json=msg)

        if is_notification:
            return None

        resp.raise_for_status()
        return resp.json()

    async def initialize(self) -> dict:
        resp = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-test-client", "version": "1.0.0"},
        })
        # Send initialized notification
        await self._send("notifications/initialized", is_notification=True)
        return resp

    async def list_tools(self) -> list[dict]:
        resp = await self._send("tools/list")
        return resp.get("result", {}).get("tools", []) if resp else []

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Call a tool and return the parsed JSON response."""
        resp = await self._send("tools/call", {"name": name, "arguments": arguments or {}})
        if not resp:
            return {"error": "No response"}
        result = resp.get("result", {})
        content = result.get("content", [])
        text = content[0].get("text", "{}") if content else "{}"
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"raw": text}
        if result.get("isError"):
            data["_is_error"] = True
        return data

    async def ping(self) -> bool:
        resp = await self._send("ping")
        return resp is not None and "result" in resp

    async def health(self) -> dict:
        """Check server health via GET /health."""
        resp = await self._http.get(f"{self.base_url}/health")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
async def run_tests(base_url: str, tool_filter: str | None = None, custom_args: dict | None = None):
    client = MCPClient(base_url)

    print("=" * 60)
    print("  MCP Client — GST Rate Server Test (HTTP)")
    print("=" * 60)

    # Health check
    print(f"\n🏥 Health check ({base_url}/health)...")
    try:
        health = await client.health()
        print(f"   ✓ Status: {health.get('status')}")
        print(f"   ✓ Server: {health.get('server')} v{health.get('version')}")
        print(f"   ✓ Documents: {health.get('document_count', 0):,}")
    except Exception as e:
        print(f"   ✗ Health check failed: {e}")
        print(f"\n   Is the server running? Start it with: python mcp_server.py")
        await client.close()
        return

    # Initialize
    print("\n🔌 Initializing MCP session...")
    init_resp = await client.initialize()
    server_info = init_resp.get("result", {}).get("serverInfo", {})
    print(f"   ✓ Server: {server_info.get('name')} v{server_info.get('version')}")

    # Ping
    print("\n📡 Ping...")
    ok = await client.ping()
    print(f"   ✓ Pong!" if ok else "   ✗ No response")

    # List tools
    print("\n🔧 Available tools:")
    tools = await client.list_tools()
    for t in tools:
        print(f"   • {t['name']}: {t['description'][:80]}...")
    print(f"   Total: {len(tools)} tools")

    # If user specified a specific tool, run only that
    if tool_filter:
        print(f"\n{'─' * 60}")
        print(f"📋 Calling: {tool_filter}")
        print(f"   Args: {json.dumps(custom_args or {})}")
        print(f"{'─' * 60}")
        result = await client.call_tool(tool_filter, custom_args or {})
        print(json.dumps(result, indent=2, ensure_ascii=False))
        await client.close()
        return

    # Run all tool tests
    tests = [
        ("get_gst_rate_by_product", {"product_name": "laptop", "limit": 3}),
        ("get_gst_rate_by_product", {"product_name": "rice", "limit": 3}),
        ("search_gst_by_description", {"search_term": "motor car", "limit": 5}),
        ("search_gst_by_description", {"search_term": "jewellery", "limit": 3}),
        ("search_gst_by_description", {"search_term": "smartphone", "limit": 3}),
        ("get_gst_rate_by_hsn", {"hsn_code": "8517", "limit": 3}),
        ("get_gst_rate_by_hsn", {"hsn_code": "7113", "limit": 3}),
        ("get_gst_categories", {}),
    ]

    for i, (tool_name, args) in enumerate(tests, 1):
        print(f"\n{'─' * 60}")
        print(f"📋 Test {i}/{len(tests)}: {tool_name}({json.dumps(args)})")
        print(f"{'─' * 60}")

        result = await client.call_tool(tool_name, args)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    await client.close()

    print(f"\n{'=' * 60}")
    print(f"  ✅ All {len(tests)} tests completed!")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the GST Rate MCP Server (HTTP)")
    parser.add_argument("--url", "-u", default="http://localhost:8000", help="MCP server URL")
    parser.add_argument("--tool", "-t", help="Run a specific tool (e.g., get_gst_rate_by_product)")
    parser.add_argument("--args", "-a", help="JSON arguments for the tool", default="{}")
    parsed = parser.parse_args()

    custom_args = json.loads(parsed.args) if parsed.args else {}

    asyncio.run(run_tests(base_url=parsed.url, tool_filter=parsed.tool, custom_args=custom_args))
