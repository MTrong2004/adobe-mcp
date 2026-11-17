"""Operational contracts independent of an installed Adobe app."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adobe_ops", ROOT / "scripts" / "adobe.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
smoke_spec = importlib.util.spec_from_file_location("mcp_smoke_ops", ROOT / "scripts" / "mcp_smoke.py")
smoke = importlib.util.module_from_spec(smoke_spec)
smoke_spec.loader.exec_module(smoke)


class OperationalTests(unittest.TestCase):
    def test_photoshop_live_requires_actual_session_contract_and_safe_version(self):
        valid = {"success": True, "is_running": True, "version": "28.0.0", "documents": [{"name": "DO_NOT_PRINT"}]}
        self.assertEqual(smoke.photoshop_live_version(valid), "28.0.0")
        for bad in ({}, {**valid, "success": False}, {**valid, "is_running": False}, {**valid, "version": "28.0 DO_NOT_PRINT"}, {**valid, "version": None}):
            with self.subTest(bad=bad), self.assertRaises(smoke.LiveSmokeFailure) as caught:
                smoke.photoshop_live_version(bad)
            self.assertNotIn("DO_NOT_PRINT", str(caught.exception))
        with self.assertRaises(smoke.LiveSmokeFailure):
            smoke.photoshop_live_version(valid, is_error=True)

    def test_only_owned_live_failures_unwrap_from_sdk_exception_groups(self):
        safe = smoke.LiveSmokeFailure("LIVE FAIL photoshop: invalid app version in session response")
        group = ExceptionGroup("DO_NOT_PRINT", [ValueError("DO_NOT_PRINT"), ExceptionGroup("private", [safe])])
        self.assertEqual(smoke.own_live_failure(group), str(safe))
        self.assertIsNone(smoke.own_live_failure(ExceptionGroup("private", [ValueError("LIVE FAIL photoshop: DO_NOT_PRINT")])))

    def test_config_runs_from_an_unrelated_directory_with_space(self):
        with tempfile.TemporaryDirectory(prefix="adobe cwd ") as unrelated:
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "adobe.py"), "config", "--app", "premiere"], cwd=unrelated, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)["mcpServers"]["adobe-premiere"]
        self.assertEqual(config["args"], ["run", "--script", str(ROOT / "premiere" / "server.py")])
        self.assertTrue(Path(config["args"][-1]).is_absolute())

    def test_installer_refuses_overwrite_then_backs_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "repo" / "aftereffects" / "cep"
            (source / "CSXS").mkdir(parents=True)
            (source / "CSXS" / "manifest.xml").write_text('<ExtensionManifest ExtensionBundleId="com.adobemcp.aftereffects"/>')
            (source / "panel.js").write_text("new")
            target = base / "appdata" / "Adobe" / "CEP" / "extensions" / "com.adobemcp.aftereffects"
            target.mkdir(parents=True)
            (target / "panel.js").write_text("old")
            with patch.object(ops, "ROOT", base / "repo"), patch.dict(os.environ, {"APPDATA": str(base / "appdata")}), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    ops.install_ae()
                ops.install_ae(force=True)
            self.assertEqual((target / "panel.js").read_text(), "new")
            backups = list(target.parent.glob("*.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "panel.js").read_text(), "old")

    def test_installer_rejects_manifest_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "aftereffects" / "cep" / "CSXS"
            source.mkdir(parents=True)
            (source / "manifest.xml").write_text('<ExtensionManifest ExtensionBundleId="../outside"/>')
            with patch.object(ops, "ROOT", Path(temporary)):
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    ops.install_ae()

    def test_health_output_whitelists_secrets(self):
        fake = {"success": True, "plugin_connected": False, "token": "DO_NOT_PRINT", "error": {"code": "DO_NOT_PRINT"}}
        with patch("core.client.BridgeClient.health", return_value=fake), patch.object(ops, "adobe_installs", return_value={}), patch.object(ops, "capability", return_value={"available": True}):
            report = ops.doctor_report()
        self.assertNotIn("DO_NOT_PRINT", json.dumps(report))
        self.assertFalse(report["bridges"]["premiere"]["plugin_connected"])
        fake["success"] = False
        with patch("core.client.BridgeClient.health", return_value=fake), patch.object(ops, "adobe_installs", return_value={}), patch.object(ops, "capability", return_value={}):
            report = ops.doctor_report()
        self.assertNotIn("DO_NOT_PRINT", json.dumps(report))
        self.assertEqual(report["bridges"]["premiere"]["error_code"], "unavailable")

    def test_doctor_real_authenticated_bridge(self):
        import threading
        from core.bridge import BridgeServer
        from core.client import BridgeClient
        server = BridgeServer("aftereffects", port=0, token="x" * 48)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        real_client = BridgeClient
        def local_client(app):
            return real_client(app, port=server.server_port)
        try:
            with patch("core.client.BridgeClient", side_effect=local_client), patch("core.client.load_token", return_value="x" * 48), patch.object(ops, "adobe_installs", return_value={}), patch.object(ops, "capability", return_value={}):
                report = ops.doctor_report()
            self.assertTrue(report["bridges"]["aftereffects"]["reachable"])
            self.assertFalse(report["bridges"]["aftereffects"]["plugin_connected"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_debug_not_written_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "repo" / "aftereffects" / "cep" / "CSXS"
            source.mkdir(parents=True)
            (source / "manifest.xml").write_text('<ExtensionManifest ExtensionBundleId="com.adobemcp.aftereffects"/>')
            with patch.object(ops, "ROOT", Path(temporary) / "repo"), patch.dict(os.environ, {"APPDATA": str(Path(temporary) / "appdata")}), patch.dict(sys.modules, {"winreg": None}), contextlib.redirect_stdout(io.StringIO()):
                ops.install_ae()


if __name__ == "__main__":
    unittest.main()
