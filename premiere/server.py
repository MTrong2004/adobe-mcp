# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Premiere UXP FastMCP stdio tools. Start root broker separately; never replay mutations."""
from pathlib import Path
import sys
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.client import BridgeClient
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Premiere Pro UXP")
client = BridgeClient("premiere")

@mcp.tool()
def premiere_health() -> dict:
    """Read authenticated broker health and last receipt; does not open Premiere."""
    return client.health()

@mcp.tool()
def premiere_session_info() -> dict:
    """Read UXP session availability and supported capabilities."""
    return client.call("session_info", {})

@mcp.tool()
def premiere_project_info() -> dict:
    """Read active project, live item IDs (getId), media paths, and sequence GUIDs."""
    return client.call("project_info", {})

@mcp.tool()
def premiere_import_media(paths: list[str], bin_name: str | None = None) -> dict:
    """Import existing absolute media paths into root or a named root bin; verify new items."""
    args = {"paths": paths}
    if bin_name is not None:
        args["bin_name"] = bin_name
    return client.call("import_media", args, timeout=120)

@mcp.tool()
def premiere_create_sequence(name: str, item_node_ids: list[str]) -> dict:
    """Create sequence from live clip item IDs returned by project_info/import_media."""
    return client.call("create_sequence", {"name": name, "item_node_ids": item_node_ids}, timeout=120)

@mcp.tool()
def premiere_insert_clip(sequence_id: str, project_item_id: str, track_type: Literal["video", "audio"], track_index: int, time_seconds: float, companion_track_index: int | None = None) -> dict:
    """Insert into existing zero-based track. Mixed AV requires explicit opposite companion track; ripple insert, limitShift true. Verify both streams."""
    args = {"sequence_id": sequence_id, "project_item_id": project_item_id, "track_type": track_type, "track_index": track_index, "time_seconds": time_seconds}
    if companion_track_index is not None:
        args["companion_track_index"] = companion_track_index
    return client.call("insert_clip", args, timeout=120)

@mcp.tool()
def premiere_export_sequence(sequence_id: str, output_path: str, preset_path: str) -> dict:
    """Immediate export with existing .epr preset to new absolute path; verify nonempty output. Timeout may leave export running; never blindly retry."""
    return client.call("export_sequence", {"sequence_id": sequence_id, "output_path": output_path, "preset_path": preset_path}, timeout=300)

@mcp.tool()
def premiere_save_project(path: str, overwrite: bool = False) -> dict:
    """Save As to absolute .prproj path; saved copy becomes active. Verify project path and nonempty file."""
    return client.call("save_project", {"path": path, "overwrite": overwrite}, timeout=120)

if __name__ == "__main__":
    mcp.run(transport="stdio")
