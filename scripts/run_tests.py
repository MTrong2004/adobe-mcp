"""Aggregate checks; every invoked suite must pass. Missing product suites fail."""
from pathlib import Path
import argparse
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-protocol", action="store_true")
    args = parser.parse_args()
    commands = [[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]]
    uv = shutil.which("uv")
    missing = []
    for folder in ("core", "aftereffects/tests", "photoshop"):
        if list((ROOT / folder).glob("test_*.py")):
            commands.append([sys.executable, "-m", "unittest", "discover", "-s", folder, "-p", "test_*.py"])
        else:
            missing.append(f"{folder}: required Python unit suite missing")
    uv = shutil.which("uv")
    premiere_protocol = ROOT / "premiere" / "test_server.py"
    if not premiere_protocol.is_file():
        missing.append("premiere/test_server.py: required schema protocol suite missing")
    elif not args.skip_protocol:
        if uv:
            commands.append([uv, "run", "--script", str(premiere_protocol)])
        else:
            missing.append("uv missing: Premiere SDK schema suite unavailable")
    node = shutil.which("node")
    for folder in ("aftereffects", "premiere", "photoshop"):
        suites = sorted([*(ROOT / folder).rglob("*.test.js"), *(ROOT / folder).rglob("*.test.cjs")])
        if not suites:
            missing.append(f"{folder}: JavaScript suite missing")
        elif not node:
            missing.append(f"{folder}: node unavailable")
        else:
            commands.append([node, "--test", *map(str, suites)])
    if not args.skip_protocol:
        uv = shutil.which("uv")
        if uv:
            commands.append([uv, "run", "--script", str(ROOT / "scripts" / "mcp_smoke.py")])
        else:
            missing.append("uv missing: real MCP protocol suite unavailable")
    failed = bool(missing)
    for message in missing:
        print(f"FAIL {message}", file=sys.stderr)
    for command in commands:
        print("RUN " + subprocess.list2cmdline(command), flush=True)
        result = subprocess.run(command, cwd=ROOT)
        failed = failed or result.returncode != 0
    print("FAIL aggregate" if failed else "PASS aggregate" + (" (offline only; MCP protocol skipped)" if args.skip_protocol else ""))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
