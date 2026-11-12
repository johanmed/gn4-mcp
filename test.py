import argparse
import asyncio
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

results = []


def record(name, ok, detail=""):
    results.append(ok)
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else "")
    )


def result_text(res):
    return "\n".join(getattr(b, "text", "") for b in (res.content or []))


async def check(client, name, tool, args, predicate, detail_fn=None):
    try:
        res = await client.call_tool(tool, args, raise_on_error=False)
        text = result_text(res)
        detail = detail_fn(text)[:120] if detail_fn else text[:120]
        record(name, predicate(res, text), detail.replace("\n", " "))
    except Exception as e:
        record(name, False, f"{type(e).__name__}: {e}")


async def run_checks(url, token):
    headers = {"Authorization": f"Bearer {token}"} if token else None
    transport = StreamableHttpTransport(url=url, headers=headers)
    try:
        async with Client(transport=transport) as client:
            tools = await client.list_tools()
            record(
                "list_tools",
                len(tools) > 30,
                f"{len(tools)} tools, e.g. "
                f"{', '.join(t.name for t in tools[:5])}...",
            )

            await check(
                client,
                "call version (no token)",
                "version",
                {},
                lambda res, text: "GeneNetwork4" in text,
            )
            await check(
                client,
                "species without token -> 401 surfaced",
                "species",
                {},
                lambda res, text: res.is_error
                and ("401" in text or "unauthorized" in text.lower()),
            )

            if not token:
                print(
                    "\nGN4_AUTH_TOKEN not set: skipping token-carrying "
                    "checks (4, 5). Re-run with a token to complete the suite."
                )
                return

            await check(
                client,
                "species with token",
                "species",
                {},
                lambda res, text: not res.is_error and "mouse" in text.lower(),
            )
            await check(
                client,
                "group_traits BXD truncated",
                "group_traits",
                {"group": "BXD"},
                lambda res, text: (not res.is_error) and "TRUNCATED" in text,
                lambda text: f"{len(text)} chars returned",
            )
            await check(
                client,
                "version with token",
                "version",
                {},
                lambda res, text: "GeneNetwork4" in text,
            )
    except Exception as e:
        record("connect to MCP server", False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/gn4-mcp/mcp")
    args = parser.parse_args()

    token = os.environ.get("GN4_AUTH_TOKEN")
    print(f"Smoke-testing MCP at {args.url}")
    print(f"Token: {'provided' if token else 'not set'}\n")

    asyncio.run(run_checks(args.url, token))

    failed = len(results) - sum(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)
