
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def search_claim_evidence(query: str):
    server_path = Path(__file__).with_name("mcp_server.py")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_evidence",
                arguments={"query": query}
            )

            if result.isError:
                raise RuntimeError(str(result.content))

            return result.structuredContent or [
                item.text for item in result.content
                if item.type == "text"
            ]


if __name__ == "__main__":
    test_claim = "The Great Wall of China is visible from the Moon"
    result = asyncio.run(search_claim_evidence(test_claim))
    print(result)
