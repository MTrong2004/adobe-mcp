"""Local authenticated broker for the optional Photoshop UXP plugin (stdlib only)."""
from __future__ import annotations
import json
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_FILE = Path(__file__).with_name("bridge-token.txt")
PORT = 8766
OPERATIONS = {"session_info", "document_info", "update_layer"}


def get_token(create=False):
    token = os.environ.get("PS_UXP_TOKEN", "").strip()
    if not token:
        if create and not TOKEN_FILE.exists():
            try:
                with TOKEN_FILE.open("x", encoding="utf-8") as f:
                    f.write(secrets.token_urlsafe(32))
            except FileExistsError:
                pass
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("UXP token must contain at least 32 characters")
    return token


def validate(operation, args):
    if operation not in OPERATIONS or not isinstance(args, dict):
        raise ValueError("Unsupported operation or invalid args")
    allowed = {"session_info": set(), "document_info": {"document_id", "include_layers", "max_depth"},
               "update_layer": {"document_id", "layer_id", "name", "visible", "opacity"}}[operation]
    if set(args) - allowed:
        raise ValueError("Unknown argument")
    for key in ("document_id", "layer_id"):
        if key in args and (type(args[key]) is not int or args[key] <= 0):
            raise ValueError(key + " must be a positive integer")
    if "max_depth" in args and (type(args["max_depth"]) is not int or not -1 <= args["max_depth"] <= 100):
        raise ValueError("max_depth must be -1..100")
    for key in ("include_layers", "visible"):
        if key in args and type(args[key]) is not bool:
            raise ValueError(key + " must be boolean")
    if "name" in args and (not isinstance(args["name"], str) or not 1 <= len(args["name"]) <= 255):
        raise ValueError("name must contain 1..255 characters")
    if "opacity" in args and (type(args["opacity"]) not in (int, float) or not 0 <= args["opacity"] <= 100):
        raise ValueError("opacity must be 0..100")
    if operation == "update_layer":
        if not {"document_id", "layer_id"} <= args.keys():
            raise ValueError("Explicit document_id and layer_id required")
        if not {"name", "visible", "opacity"} & args.keys():
            raise ValueError("Specify a layer change")


class Broker:
    def __init__(self):
        self.condition = threading.Condition()
        self.job = None
        self.claimed = False
        self.result = None
        self.last_poll = 0.0
        self.completed_id = None
        self.timed_out = False

    def status(self):
        with self.condition:
            return {"success": True, "protocol": 1, "plugin_connected": time.monotonic() - self.last_poll < 5,
                    "busy": self.job is not None}

    def call(self, operation, args, timeout=30):
        validate(operation, args)
        with self.condition:
            if self.job is not None:
                return {"success": False, "error": "UXP busy or previous result unknown; inspect Photoshop before reconnecting."}
            if time.monotonic() - self.last_poll >= 5:
                return {"success": False, "error": "Open UXP panel and connect first."}
            job_id = uuid.uuid4().hex
            self.job = {"id": job_id, "operation": operation, "args": args,
                        "expires_at": int((time.time() + timeout) * 1000)}
            self.claimed, self.result, self.timed_out = False, None, False
            ready = self.condition.wait_for(lambda: self.result is not None, timeout)
            if ready:
                result = self.result
                self.job, self.result = None, None
                return result
            if not self.claimed:
                self.job = None
                return {"success": False, "error": "UXP timed out before delivery; request discarded."}
            # Never release/replay a delivered operation whose outcome is unknown.
            self.timed_out = True
            return {"success": False, "outcome_unknown": True,
                    "error": "UXP result timed out. Do not retry mutation; inspect Photoshop. Bridge blocked until result arrives or restart."}

    def next(self):
        with self.condition:
            self.last_poll = time.monotonic()
            if self.job and not self.claimed:
                self.claimed = True
                return {"job": self.job}
            return {"job": None}

    def finish(self, payload):
        with self.condition:
            job_id = payload.get("id")
            if job_id == self.completed_id and job_id is not None:
                return
            if not self.job or self.job["id"] != job_id or not self.claimed:
                raise ValueError("Unknown job")
            result = payload.get("result")
            if "error" in payload:
                result = {"success": False, "error": str(payload["error"])}
            if not isinstance(result, dict):
                raise ValueError("Result must be an object")
            self.completed_id = job_id
            if self.timed_out:
                self.job, self.result = None, None
            else:
                self.result = result
            self.condition.notify_all()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, token):
        self.token = token
        self.broker = Broker()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log authorization or document contents.

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token):
            self.send_json(401, {"success": False, "error": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/health":
            self.send_json(200, self.server.broker.status())
        elif self.path == "/next":
            self.send_json(200, self.server.broker.next())
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8 * 1024 * 1024:
                raise ValueError("Invalid body length")
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Body must be an object")
            if self.path == "/call":
                result = self.server.broker.call(payload.get("operation"), payload.get("args", {}))
                self.send_json(200, result)
            elif self.path == "/result":
                self.server.broker.finish(payload)
                self.send_json(200, {"success": True})
            else:
                self.send_json(404, {"error": "Not found"})
        except (ValueError, TypeError, TimeoutError) as exc:
            self.send_json(400, {"success": False, "error": str(exc)})


if __name__ == "__main__":
    token = get_token(create=True)
    server = Server(("127.0.0.1", PORT), token)
    print(f"Photoshop UXP bridge: http://127.0.0.1:{PORT}", flush=True)
    print("Token: PS_UXP_TOKEN environment variable or bridge-token.txt beside this script.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
