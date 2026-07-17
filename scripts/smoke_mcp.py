from __future__ import annotations

import argparse
import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run_smoke(endpoint: str, health_url: str) -> None:
    health = httpx.get(health_url, timeout=5)
    health.raise_for_status()
    payload = health.json()
    if payload.get("status") != "ok":
        raise RuntimeError(f"Unexpected health payload: {payload}")

    async with streamablehttp_client(endpoint) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {
                "capture_work_product",
                "record_skill_run",
                "recommend_skills",
                "refresh_skill_catalog",
                "list_skill_catalog",
                "set_skill_update_policy",
                "list_skill_update_policies",
            }
            missing = required - names
            if missing:
                raise RuntimeError(f"Missing required tools: {sorted(missing)}")
            result = await session.call_tool("list_skill_catalog", {"limit": 1})
            if result.isError:
                raise RuntimeError("list_skill_catalog returned an MCP error")
            policies = await session.call_tool("list_skill_update_policies", {})
            if policies.isError:
                raise RuntimeError("list_skill_update_policies returned an MCP error")
    print(f"ok endpoint={endpoint} tools={len(names)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8794/mcp")
    parser.add_argument("--health", default="http://127.0.0.1:8794/health")
    args = parser.parse_args()
    asyncio.run(run_smoke(args.endpoint, args.health))


if __name__ == "__main__":
    main()
