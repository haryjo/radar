"""Client MCP : le graphe de veille passe par le serveur MCP maison pour lire et écrire les offres."""
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ..config import settings


class MCPError(Exception):
    pass


async def mcp_call(tool: str, arguments: dict[str, Any]) -> Any:
    async with streamablehttp_client(settings.mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
    text = "".join(getattr(c, "text", "") for c in result.content)
    if result.isError:
        raise MCPError(text or f"Erreur MCP sur {tool}")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP enveloppe les valeurs non-dict dans {"result": ...}
        if isinstance(structured, dict) and list(structured.keys()) == ["result"]:
            return structured["result"]
        return structured
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
