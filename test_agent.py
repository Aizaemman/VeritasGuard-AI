
import asyncio
import json

from mcp_client import search_claim_evidence
from agent import analyze_claim


async def main():
    claim = "The Great Wall of China is visible from the Moon"

    print("\nSearching evidence through MCP...")

    result = await search_claim_evidence(claim)

    # MCP v1 returns text content, so parse the JSON.
    if isinstance(result, list):
        evidence_data = json.loads(result[0])
    else:
        evidence_data = result

    if evidence_data.get("error"):
        print("Search error:", evidence_data["error"])
        return

    sources = evidence_data.get("sources", [])

    if not sources:
        print("No evidence found.")
        return

    print(f"Found {len(sources)} sources.")
    print("\nAnalyzing evidence with Groq AI...")

    analysis = analyze_claim(claim, sources)

    print("\n===== VERITASGUARD AI REPORT =====")
    print(json.dumps(analysis, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
