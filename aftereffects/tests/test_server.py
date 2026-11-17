"""Run: uv run --with mcp==1.30.0 python -m unittest discover -s aftereffects/tests."""
import importlib.util
import math
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError

spec = importlib.util.spec_from_file_location("ae_server", Path(__file__).parents[1] / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_allowlist_and_schemas(self):
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        self.assertEqual(set(tools), {"aftereffects_" + op for op in ("health", "session_info", "project_info", "create_comp", "import_media", "add_layer", "set_layer_transform", "save_project", "render_comp")})
        props = tools["aftereffects_add_layer"].inputSchema["properties"]
        self.assertEqual(props["comp_id"]["type"], "integer")
        self.assertEqual(props["comp_id"]["exclusiveMinimum"], 0)
        self.assertFalse(tools["aftereffects_save_project"].inputSchema["properties"]["overwrite"]["default"])

    async def test_bad_ids_and_nonfinite_are_rejected_before_bridge(self):
        with patch.object(server, "bridge") as bridge:
            for bad in [0, -1, True, "7", 1.5]:
                with self.assertRaises(Exception):
                    await server.mcp.call_tool("aftereffects_add_layer", {"comp_id": bad, "item_id": 2})
            for bad in [math.nan, math.inf, -math.inf]:
                with self.assertRaises(Exception):
                    await server.mcp.call_tool("aftereffects_set_layer_transform", {"comp_id": 7, "layer_index": 1, "opacity": bad})
            bridge.call.assert_not_called()

    async def test_tool_dispatches_only_expected_operation(self):
        bridge = Mock()
        bridge.call.return_value = {"success": True, "data": {"id": 7}}
        with patch.object(server, "bridge", bridge):
            server.aftereffects_session_info()
            bridge.call.assert_called_with("session_info", {})
            server.aftereffects_set_layer_transform(7, 1, position=[10, 20], opacity=50)
            bridge.call.assert_called_with("set_layer_transform", {"comp_id": 7, "layer_index": 1, "position": [10, 20], "opacity": 50})
            server.aftereffects_render_comp(7, "C:/new.mov")
            bridge.call.assert_called_with("render_comp", {"comp_id": 7, "output_path": "C:/new.mov"}, timeout=300)
            server.aftereffects_save_project("C:/new.aep")
            bridge.call.assert_called_with("save_project", {"path": "C:/new.aep", "overwrite": False})


if __name__ == "__main__":
    unittest.main()
