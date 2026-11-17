# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Allowlisted After Effects tools. Run with uv run aftereffects/server.py."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field, StrictBool, StrictInt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.client import BridgeClient

mcp = FastMCP("After Effects MCP")
bridge = BridgeClient("aftereffects")
ItemID = Annotated[StrictInt, Field(gt=0, le=2147483647)]
Dimension = Annotated[StrictInt, Field(ge=4, le=30000)]
PositiveText = Annotated[str, Field(min_length=1, max_length=32768)]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Vector = Annotated[list[Annotated[float, Field(ge=-1000000, le=1000000, allow_inf_nan=False)]], Field(min_length=2, max_length=3)]


@mcp.tool()
def aftereffects_health() -> dict:
    """Read bridge health and last_result to reconcile uncertain operations without queuing a job."""
    return bridge.health()


@mcp.tool()
def aftereffects_session_info() -> dict:
    """Read AE version and whether a project is open; requires the CEP panel."""
    return bridge.call("session_info", {})


@mcp.tool()
def aftereffects_project_info() -> dict:
    """Read project items, integer item IDs and composition layer indexes."""
    return bridge.call("project_info", {})


@mcp.tool()
def aftereffects_create_comp(name: PositiveText, width: Dimension, height: Dimension,
                            pixel_aspect: Annotated[float, Field(ge=.01, le=100, allow_inf_nan=False)],
                            duration: Annotated[float, Field(ge=.001, le=10800, allow_inf_nan=False)],
                            frame_rate: Annotated[float, Field(ge=1, le=99, allow_inf_nan=False)]) -> dict:
    """Create a composition in the current project; return its item ID."""
    return bridge.call("create_comp", dict(name=name, width=width, height=height, pixel_aspect=pixel_aspect, duration=duration, frame_rate=frame_rate))


@mcp.tool()
def aftereffects_import_media(path: PositiveText) -> dict:
    """Import an existing absolute local media file; image sequences are disabled."""
    return bridge.call("import_media", {"path": path})


@mcp.tool()
def aftereffects_add_layer(comp_id: ItemID, item_id: ItemID) -> dict:
    """Add footage or a composition by project item IDs, without changing selection."""
    return bridge.call("add_layer", {"comp_id": comp_id, "item_id": item_id})


@mcp.tool()
def aftereffects_set_layer_transform(comp_id: ItemID, layer_index: ItemID,
                                    position: Vector | None = None, scale: Vector | None = None,
                                    rotation: Annotated[float, Field(ge=-1000000, le=1000000, allow_inf_nan=False)] | None = None,
                                    opacity: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None) -> dict:
    """Set static layer transforms. Vector dimensions must match 2D/3D layer. Animated, expression, separated and locked properties are rejected."""
    args = {"comp_id": comp_id, "layer_index": layer_index}
    args.update({key: value for key, value in dict(position=position, scale=scale, rotation=rotation, opacity=opacity).items() if value is not None})
    return bridge.call("set_layer_transform", args)


@mcp.tool()
def aftereffects_save_project(path: PositiveText, overwrite: StrictBool = False) -> dict:
    """Save to an absolute local .aep path. Existing files require overwrite=true."""
    return bridge.call("save_project", {"path": path, "overwrite": overwrite})


@mcp.tool()
def aftereffects_render_comp(comp_id: ItemID, output_path: PositiveText,
                            output_module_template: PositiveText | None = None) -> dict:
    """Render one comp to a new single movie file; never overwrites. Existing queue flags are restored. Synchronous render may outlast timeout: inspect AE/output before retrying."""
    args = {"comp_id": comp_id, "output_path": output_path}
    if output_module_template is not None:
        args["output_module_template"] = output_module_template
    return bridge.call("render_comp", args, timeout=300)


if __name__ == "__main__":
    mcp.run(transport="stdio")
