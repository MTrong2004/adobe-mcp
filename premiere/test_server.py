# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Real MCP SDK stdio handshake/tool schema test; does not exercise live Adobe."""
import asyncio
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("server.py"))])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            tools = {t.name: t for t in result.tools}
            expected = {"premiere_health", "premiere_session_info", "premiere_project_info", "premiere_import_media", "premiere_create_sequence", "premiere_insert_clip", "premiere_export_sequence", "premiere_save_project"}
            assert set(tools) == expected, set(tools)
            assert "companion_track_index" in tools["premiere_insert_clip"].inputSchema["properties"]
            print("PASS: real SDK stdio initialize/list_tools; 8 Premiere tool schemas. No live host call.")

if __name__ == "__main__":
    asyncio.run(main())
