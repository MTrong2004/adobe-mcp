# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Real MCP SDK stdio checks. Protocol mode requires a disconnected app bridge."""
from __future__ import annotations
import argparse
import asyncio
import json
import re
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


class LiveSmokeFailure(ValueError):
    """A sanitized diagnostic owned by this script, safe to unwrap from SDK groups."""


def photoshop_live_version(payload, is_error=False):
    if is_error or not isinstance(payload, dict) or payload.get("success") is not True or payload.get("is_running") is not True:
        raise LiveSmokeFailure("LIVE FAIL photoshop: session check unsuccessful; inspect Photoshop launch, dialogs and COM availability locally")
    version = payload.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+(?:\.\d+){0,3}", version):
        raise LiveSmokeFailure("LIVE FAIL photoshop: invalid app version in session response")
    return version


def own_live_failure(error):
    if isinstance(error, LiveSmokeFailure):
        return str(error)
    for child in getattr(error, "exceptions", ()):
        found = own_live_failure(child)
        if found:
            return found
    return None


async def smoke(app, live=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is required for the pinned MCP server environment")
    server = ROOT / app / "server.py"
    if not server.is_file():
        raise ValueError(f"{app} server is not built yet")
    tool = {"aftereffects": "aftereffects_session_info", "premiere": "premiere_session_info", "photoshop": "photoshop_get_session_info"}[app]
    parameters = StdioServerParameters(command=uv, args=["run", "--script", str(server)], cwd=str(ROOT))
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = {item.name for item in listed.tools}
            if not names:
                raise ValueError("MCP server exposed no tools")
            if app == "photoshop" and not live:
                print(f"PASS photoshop: SDK initialize ({initialized.protocolVersion}), tools/list ({len(names)} tools); COM operations not invoked")
                return
            if tool not in names:
                raise ValueError(f"Required read-only tool absent: {tool}")
            response = await session.call_tool(tool, {})
            payload = result_payload(response)
            if app == "photoshop":
                version = photoshop_live_version(payload, getattr(response, "isError", False))
                print(f"PASS photoshop: SDK initialize ({initialized.protocolVersion}), tools/list ({len(names)} tools), {tool} live read-only; version {version}; success/is_running/version checks passed")
                return
            if not isinstance(payload, dict):
                raise ValueError("Tool result must be a JSON object")
            error = payload.get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
            if live:
                if payload.get("success") is not True:
                    raise LiveSmokeFailure(f"LIVE FAIL {app}: disconnected or unsuccessful session check; start bridge and load panel/plugin")
            elif payload.get("success") is not False or code != "disconnected":
                raise ValueError(f"Expected explicit disconnected result for {app}; stop its bridge/plugin or use --live")
            # Never print raw tool results, project names, paths or bridge credentials.
            print(f"PASS {app}: SDK initialize ({initialized.protocolVersion}), tools/list ({len(names)} tools), {tool} {'live read-only' if live else 'explicit disconnected response'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=("aftereffects", "premiere", "photoshop"), action="append")
    parser.add_argument("--live", action="store_true", help="Require a real Adobe session; Photoshop uses read-only COM and may launch the app")
    args = parser.parse_args()
    if args.live and not args.app:
        parser.error("--live requires an explicit --app; Photoshop may launch via COM")
    async def run():
        for app in args.app or ("aftereffects", "premiere", "photoshop"):
            timeout = 90
            try:
                await asyncio.wait_for(smoke(app, args.live), timeout=timeout)
            except TimeoutError:
                raise LiveSmokeFailure(f"LIVE FAIL {app}: bounded session timeout ({timeout}s); inspect the app locally") from None
    try:
        asyncio.run(run())
        return 0
    except Exception as exc:
        # SDK exception groups can contain transport text: don't emit them verbatim.
        if isinstance(exc, (ValueError, TimeoutError)):
            print(f"FAIL: {exc}", file=sys.stderr)
        else:
            # Only our own live status message is safe to expose from task-group errors.
            message = own_live_failure(exc)
            print(f"FAIL: {message}" if message else f"FAIL: MCP transport/session error ({type(exc).__name__}); inspect server stderr locally.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
