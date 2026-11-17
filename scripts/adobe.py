#!/usr/bin/env python3
"""Local Adobe MCP operations. Uses only Python's standard library."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APPS = ("aftereffects", "premiere", "photoshop")
PORTS = {"aftereffects": 8767, "premiere": 8768}


def capability(name):
    executable = shutil.which(name)
    if not executable:
        return {"available": False}
    try:
        result = subprocess.run([executable, "-version" if name in ("ffmpeg", "ffprobe") else "--version"], capture_output=True, text=True, timeout=10)
        line = (result.stdout or result.stderr).splitlines()[0]
        # Emit a version only, never arbitrary tool output or environment values.
        match = re.search(r"\d+(?:\.\d+){1,3}", line)
        return {"available": result.returncode == 0, "path": executable, "version": match.group() if match else "unknown"}
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return {"available": False, "path": executable}


def adobe_installs():
    """Only Adobe uninstall records and the two explicitly approved roots."""
    found = []
    if sys.platform == "win32":
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for branch in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    with winreg.OpenKey(hive, branch) as parent:
                        for index in range(winreg.QueryInfoKey(parent)[0]):
                            try:
                                with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as item:
                                    name = winreg.QueryValueEx(item, "DisplayName")[0]
                                    if "adobe" not in name.lower() and "uxp developer" not in name.lower():
                                        continue
                                    record = {"name": name}
                                    for key, label in (("DisplayVersion", "version"), ("InstallLocation", "location")):
                                        try:
                                            record[label] = winreg.QueryValueEx(item, key)[0]
                                        except OSError:
                                            pass
                                    found.append(record)
                            except OSError:
                                continue
                except OSError:
                    pass
    paths = []
    for base in (Path("C:/Program Files/Adobe"), Path("D:/Default_app")):
        if not base.is_dir():
            continue
        # Two levels only: no recursive disk/home search.
        for directory in base.iterdir():
            if directory.is_dir() and "adobe" in directory.name.lower():
                paths.append(str(directory))
                for child in directory.iterdir():
                    if child.is_dir() and "adobe" in child.name.lower():
                        paths.append(str(child))
    premiere = Path("D:/Default_app/Adobe Premiere Pro 2026/Adobe Premiere Pro.exe")
    udt_candidates = [Path("C:/Program Files/Adobe/Adobe UXP Developer Tool/Adobe UXP Developer Tool.exe"), Path("C:/Program Files/Adobe/UXP Developer Tool/UXP Developer Tool.exe"), Path("D:/Default_app/Adobe UXP Developer Tool/Adobe UXP Developer Tool.exe")]
    udt_detected = any("uxp developer" in item["name"].lower() for item in found) or any(path.is_file() for path in udt_candidates)
    return {"uninstall_records": found, "directories": paths, "premiere_executable": {"path": str(premiere), "exists": premiere.is_file()}, "uxp_developer_tool": {"detected": udt_detected, "checked_executables": [str(path) for path in udt_candidates], "next_step": "In Premiere enable developer mode and restart; UDT Add manifest, Load & Watch, then open Window > UXP Plugins."}}


def doctor_report():
    sys.path.insert(0, str(ROOT))
    bridges = {}
    for app in PORTS:
        try:
            from core.client import BridgeClient
            result = BridgeClient(app).health()
            # Whitelist fields: bridge payloads or bearer tokens never enter output.
            bridges[app] = {"port": PORTS[app], "token_present": (ROOT / ".runtime" / f"{app}-token.txt").is_file(), "reachable": result.get("success") is True, "plugin_connected": result.get("plugin_connected") is True}
            if not result.get("success"):
                err = result.get("error", {})
                code = err.get("code") if isinstance(err, dict) else None
                bridges[app]["error_code"] = code if code in {"disconnected", "unauthorized", "http_error", "timeout", "invalid_response", "validation_error"} else "unavailable"
        except (ImportError, OSError, ValueError):
            bridges[app] = {"reachable": False, "plugin_connected": False, "error_code": "bridge_not_ready"}
    manifests = {}
    for app, relative in (("aftereffects", "aftereffects/cep/CSXS/manifest.xml"), ("premiere", "premiere/uxp-plugin/manifest.json"), ("photoshop", "photoshop/uxp-plugin/manifest.json")):
        path = ROOT / relative
        valid = False
        if path.is_file():
            try:
                ET.parse(path) if path.suffix == ".xml" else json.loads(path.read_text(encoding="utf-8"))
                valid = True
            except (ValueError, ET.ParseError):
                pass
        manifests[app] = {"path": str(path), "valid": valid}
    return {"root": str(ROOT), "capabilities": {name: capability(name) for name in ("uv", "python", "node", "ffmpeg", "ffprobe")}, "adobe": adobe_installs(), "bridges": bridges, "manifests": manifests, "uxp_installation": "Manual UXP Developer Tool Add/Load required; manifest presence does not prove installed or connected."}


def mcp_config(apps):
    uv = shutil.which("uv") or "uv"
    return {"mcpServers": {f"adobe-{app}": {"command": uv, "args": ["run", "--script", str(ROOT / app / "server.py")]} for app in apps}}


def install_ae(force=False, enable_debug=False):
    source = ROOT / "aftereffects" / "cep"
    manifest = source / "CSXS" / "manifest.xml"
    if not manifest.is_file():
        raise ValueError("AE CEP panel source is unavailable; finish the panel build first.")
    xml = ET.parse(manifest).getroot()
    extension_id = xml.attrib.get("ExtensionBundleId", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", extension_id) or extension_id in (".", ".."):
        raise ValueError("Panel manifest has an unsafe ExtensionBundleId.")
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise ValueError("APPDATA is unavailable; run this installer on Windows.")
    parent = Path(appdata).resolve() / "Adobe" / "CEP" / "extensions"
    target = parent / extension_id
    # Existing symlinks/junctions could redirect writes outside the known extension target.
    if parent.resolve() != parent.absolute():
        raise ValueError("Refusing a redirected CEP extensions parent.")
    if target.is_symlink() or (target.exists() and target.resolve() != target.absolute()):
        raise ValueError("Refusing a redirected extension target.")
    if target.exists():
        if not force:
            raise ValueError(f"Extension already exists at {target}; use --force to preserve it as a backup and replace it.")
        backup = target.with_name(target.name + ".backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        target.rename(backup)
        print(f"Backup: {backup}")
    parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    print(f"Copied AE panel: {target}")
    if enable_debug:
        if sys.platform != "win32":
            raise ValueError("PlayerDebugMode requires Windows.")
        import winreg
        # Set only the manifest's declared CSXS runtime; explicit opt-in only.
        runtime = xml.find(".//RequiredRuntime[@Name='CSXS']")
        version = runtime.attrib.get("Version", "11.0") if runtime is not None else "11.0"
        major = version.split(".")[0]
        if not major.isdigit():
            raise ValueError("Invalid CSXS runtime version.")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Adobe\CSXS.{major}") as key:
            winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
        print(f"Enabled PlayerDebugMode for CSXS.{major} by explicit request.")
    print("Restart After Effects, open Window > Extensions > Adobe MCP. Copy the local token into the panel privately; do not paste it into logs or chat.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doc = sub.add_parser("doctor", help="Read-only capability, install and authenticated bridge checks")
    doc.add_argument("--json", action="store_true")
    bridge = sub.add_parser("bridge", help="Run the app's local bridge")
    bridge.add_argument("--app", required=True, choices=tuple(PORTS))
    config = sub.add_parser("config", help="Print cwd-independent MCP client JSON")
    config.add_argument("--app", choices=APPS, action="append")
    install = sub.add_parser("install-ae-panel")
    install.add_argument("--force", action="store_true")
    install.add_argument("--enable-debug", action="store_true")
    tests = sub.add_parser("test", help="Run Python, Node and real MCP SDK protocol tests")
    tests.add_argument("--skip-protocol", action="store_true", help="Offline unit tests only; does not prove MCP readiness")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = doctor_report()
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.command == "config":
            print(json.dumps(mcp_config(args.app or APPS), indent=2))
            return 0
        if args.command == "bridge":
            return subprocess.call([sys.executable, "-m", "core.bridge", "--app", args.app], cwd=ROOT)
        if args.command == "install-ae-panel":
            install_ae(args.force, args.enable_debug)
            return 0
        if args.command == "test":
            return subprocess.call([sys.executable, str(ROOT / "scripts" / "run_tests.py"), *(["--skip-protocol"] if args.skip_protocol else [])], cwd=ROOT)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
