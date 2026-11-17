# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Real MCP SDK stdio checks. Protocol mode requires a disconnected app bridge."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def result_payload(result):
    structured = getattr(result, "structuredContent", None)
    if structured:
        # FastMCP may wrap dict returns as result depending on annotations.
        return structured.get("result", structured)
    for block in result.content:
        if getattr(block, "type", None) == "text":
            try:
                return json.loads(block.text)
            except ValueError:
                continue
    raise ValueError("MCP tool returned no JSON result")


async def smoke(app, live=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is required for the pinned MCP server environment")
    server = ROOT / app / "server.py"
    if not server.is_file():
        raise ValueError(f"{app} server is not built yet")
    tool = {"aftereffects": "aftereffects_session_info", "premiere": "premiere_session_info", "photoshop": None}[app]
    parameters = StdioServerParameters(command=uv, args=["run", "--script", str(server)], cwd=str(ROOT))
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = {item.name for item in listed.tools}
            if not names:
                raise ValueError("MCP server exposed no tools")
            if app == "photoshop":
                print(f"PASS photoshop: SDK initialize ({initialized.protocolVersion}), tools/list ({len(names)} tools); COM operations not invoked")
                return
            if tool not in names:
                raise ValueError(f"Required read-only tool absent: {tool}")
            payload = result_payload(await session.call_tool(tool, {}))
            if not isinstance(payload, dict):
                raise ValueError("Tool result must be a JSON object")
            error = payload.get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
            if live:
                if payload.get("success") is not True:
                    raise ValueError(f"LIVE FAIL {app}: {code or 'unsuccessful response'}; start bridge and load panel/plugin")
            elif payload.get("success") is not False or code != "disconnected":
                raise ValueError(f"Expected explicit disconnected result for {app}; stop its bridge/plugin or use --live")
            # Never print raw tool results, project names, paths or bridge credentials.
            print(f"PASS {app}: SDK initialize ({initialized.protocolVersion}), tools/list ({len(names)} tools), {tool} {'live read-only' if live else 'explicit disconnected response'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=("aftereffects", "premiere", "photoshop"), action="append")
    parser.add_argument("--live", action="store_true", help="Require real loaded Adobe plugin; disconnected is failure")
    args = parser.parse_args()
    if args.live and (not args.app or "photoshop" in args.app):
        parser.error("--live requires --app aftereffects or --app premiere; Photoshop smoke only checks protocol without invoking COM")
    async def run():
        for app in args.app or ("aftereffects", "premiere", "photoshop"):
            await asyncio.wait_for(smoke(app, args.live), timeout=90)
    try:
        asyncio.run(run())
        return 0
    except Exception as exc:
        # SDK exception groups can contain transport text: don't emit them verbatim.
        if isinstance(exc, (ValueError, TimeoutError)):
            print(f"FAIL: {exc}", file=sys.stderr)
        else:
            def own_live_failure(error):
                if isinstance(error, ValueError) and str(error).startswith(("LIVE FAIL aftereffects:", "LIVE FAIL premiere:")):
                    return str(error)
                for child in getattr(error, "exceptions", ()):
                    found = own_live_failure(child)
                    if found:
                        return found
                return None
            # Only our own live status message is safe to expose from task-group errors.
            message = own_live_failure(exc)
            print(f"FAIL: {message}" if message else f"FAIL: MCP transport/session error ({type(exc).__name__}); inspect server stderr locally.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
