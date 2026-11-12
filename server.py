"""MCP server for GN4"""

import argparse
import json
from typing import Any

import httpx2
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult

from mcp import types


class BearerPassThrough(httpx2.Auth):
    # get_http_headers() strips credential headers unless opted in
    async def async_auth_flow(self, request):
        auth = get_http_headers(include={"authorization"}).get("authorization")
        if auth:
            request.headers["Authorization"] = auth
        yield request


class TruncateResults(Middleware):
    def __init__(self, max_chars):
        self.max_chars = max_chars

    def _text(self, text):
        if len(text) <= self.max_chars:
            return text, False
        note = (
            f"\n... [TRUNCATED by the MCP server: the full response was "
            f"{len(text)} characters, only the first {self.max_chars} are "
            f"shown. Use a more specific query, a filter parameter, or "
            f"fetch a single item instead of a listing.]"
        )
        return text[: self.max_chars] + note, True

    async def on_call_tool(self, context, call_next):
        result = await call_next(context)
        truncated = False

        content = []
        for block in result.content or []:
            if isinstance(block, types.TextContent):
                text, did = self._text(block.text)
                if did:
                    truncated = True
                    block = types.TextContent(type="text", text=text)
            content.append(block)

        structured = result.structured_content
        if structured is not None:
            dumped = json.dumps(structured, default=str)
            if len(dumped) > self.max_chars:
                truncated = True
                structured = {
                    "gn4_mcp_notice": (
                        f"Structured payload dropped by the MCP server: it was "
                        f"{len(dumped)} characters (limit {self.max_chars}). "
                        f"The truncated text content carries the visible preview."
                    )
                }
                if not any(isinstance(c, types.TextContent) for c in content):
                    text, _ = self._text(dumped)
                    content.append(types.TextContent(type="text", text=text))

        if truncated:
            return ToolResult(
                content=content,
                structured_content=structured,
                meta=result.meta,
                is_error=result.is_error,
            )
        return result


def build_mcp(
    client: httpx2.AsyncClient, openapi_spec: dict[str, Any], max_chars: int
) -> FastMCP:
    mcp = FastMCP.from_openapi(
        openapi_spec=openapi_spec,
        client=client,
        name="GN4 MCP",
        validate_output=False,
    )
    mcp.add_middleware(TruncateResults(max_chars))
    return mcp


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("api", help="API base")
    parser.add_argument(
        "--target-port", type=int, default=9000, help="Port to expose MCP"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind")
    parser.add_argument("--path", default="/gn4-mcp/mcp", help="Path to expose MCP")
    parser.add_argument("--max-chars", type=int, default=60000, help="Truncation limit")
    parser.add_argument(
        "--timeout", type=float, default=900, help="Upstream API timeout in seconds"
    )
    args = parser.parse_args()

    client = httpx2.AsyncClient(
        base_url=args.api,
        auth=BearerPassThrough(),
        timeout=httpx2.Timeout(args.timeout, connect=30.0),
        headers={"Accept": "application/json"},
    )
    openapi_spec = httpx2.get(f"{args.api.rstrip('/')}/openapi.json").json()
    mcp = build_mcp(client, openapi_spec, args.max_chars)
    mcp.run(
        transport="http",
        host=args.host,
        port=args.target_port,
        path=args.path,
        stateless_http=True,
        json_response=True,
        show_banner=False,
    )
