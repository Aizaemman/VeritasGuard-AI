
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient

load_dotenv()

mcp = FastMCP("VeritasGuard")


@mcp.tool()
def search_evidence(query: str) -> dict:
    """Search online sources to verify a factual claim."""

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        return {"error": "Tavily API key is missing"}

    try:
        client = TavilyClient(api_key=api_key)

        response = client.search(
            query=query,
            search_depth="basic",
            max_results=5
        )

        sources = []

        for result in response.get("results", []):
            sources.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "content": result.get("content", "")
            })

        return {
            "query": query,
            "sources": sources
        }

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
