"""Authenticated loopback job broker for Adobe CEP panels (stdlib only)."""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORTS = {"aftereffects": 8767, "premiere": 8768}
ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 1024 * 1024
MAX_TIMEOUT = 300
MAX_RESPONSE = MAX_BODY + 4096
MAX_STATE = 12 * MAX_BODY
MAX_RECEIPTS = 64
MAX_RECEIPT_BYTES = 4 * MAX_BODY


def error(code, message, **details):
    return {"success": False, "error": {"code": code, "message": message}, **details}


class ValidationError(ValueError):
    pass


def strict_loads(raw, *, max_depth=32, max_values=20000):
    def reject(value):
        raise ValidationError("Non-finite JSON numbers are forbidden.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError("Duplicate JSON fields are forbidden.")
            result[key] = value
        return result
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValidationError("Non-finite JSON numbers are forbidden.")
        return parsed
    value = json.loads(raw, parse_constant=reject, parse_float=finite_float, object_pairs_hook=unique)
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > max_depth or count > max_values:
            raise ValidationError(f"JSON exceeds the maximum depth ({max_depth}) or value count ({max_values}).")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def number(value, name, low=None, high=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{name} must be a finite number.")
    if integer and not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer.")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValidationError(f"{name} must be between {low} and {high}.")
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 32768 or "\x00" in value:
        raise ValidationError(f"{name} must be a nonempty string without NUL characters.")
    return value


def path_value(value, name, source=False, overwrite=False):
    path = Path(text(value, name))
    if not path.is_absolute():
        raise ValidationError(f"{name} must be an absolute path.")
    if source:
        if not path.is_file():
            raise ValidationError(f"{name} must identify an existing file.")
    else:
        if not path.parent.is_dir():
            raise ValidationError(f"Parent directory for {name} must exist.")
        if path.exists() and (not overwrite or not path.is_file()):
            raise ValidationError(f"{name} already exists; choose a new file or explicitly allow overwrite when supported.")
    return str(path)


def validate_operation(app, operation, args):
    if app not in DEFAULT_PORTS:
        raise ValidationError("app must be aftereffects or premiere.")
    if not isinstance(operation, str) or not isinstance(args, dict):
        raise ValidationError("operation must be a string and args must be an object.")
    common = {"session_info": ((), ()), "project_info": ((), ()), "save_project": (("path",), ("overwrite",))}
    ae = {
        "create_comp": (("name", "width", "height", "pixel_aspect", "duration", "frame_rate"), ()),
        "import_media": (("path",), ()), "add_layer": (("comp_id", "item_id"), ()),
        "set_layer_transform": (("comp_id", "layer_index"), ("position", "scale", "rotation", "opacity")),
        "render_comp": (("comp_id", "output_path"), ("output_module_template",)),
    }
    premiere = {
        "import_media": (("paths",), ("bin_name",)),
        "create_sequence": (("name", "item_node_ids"), ()),
        "insert_clip": (("sequence_id", "project_item_id", "track_type", "track_index", "time_seconds"), ("companion_track_index",)),
        "export_sequence": (("sequence_id", "output_path", "preset_path"), ()),
    }
    schema = {**common, **(ae if app == "aftereffects" else premiere)}
    if operation not in schema:
        raise ValidationError(f"Unsupported {app} operation: {operation}.")
    required, optional = schema[operation]
    missing = set(required) - args.keys()
    unknown = args.keys() - set(required + optional)
    if missing or unknown:
        raise ValidationError(f"Invalid arguments; missing={sorted(missing)}, unsupported={sorted(unknown)}.")
    result = dict(args)
    if "overwrite" in args and type(args["overwrite"]) is not bool:
        raise ValidationError("overwrite must be a boolean.")
    for key, value in args.items():
        if key in ("path", "output_path", "preset_path"):
            result[key] = path_value(value, key, source=operation == "import_media" or key == "preset_path", overwrite=args.get("overwrite", False))
        elif key == "paths":
            if not isinstance(value, list) or not 1 <= len(value) <= 1000:
                raise ValidationError("paths must contain 1 to 1000 existing absolute file paths.")
            result[key] = [path_value(p, "paths entry", source=True) for p in value]
        elif key == "item_node_ids":
            if not isinstance(value, list) or not 1 <= len(value) <= 1000:
                raise ValidationError("item_node_ids must contain 1 to 1000 IDs.")
            for item in value:
                text(item, "item_node_ids entry")
        elif key in ("comp_id", "item_id", "layer_index"):
            number(value, key, 1, 2147483647, integer=True)
        elif key in ("sequence_id", "project_item_id", "name", "bin_name", "output_module_template"):
            text(value, key)
        elif key in ("width", "height"):
            number(value, key, 4, 30000, integer=True)
        elif key == "pixel_aspect":
            number(value, key, 0.01, 100)
        elif key == "duration":
            number(value, key, 0.001, 10800)
        elif key == "frame_rate":
            number(value, key, 1, 99)
        elif key in ("position", "scale"):
            if not isinstance(value, list) or len(value) not in (2, 3):
                raise ValidationError(f"{key} must have 2 or 3 finite numeric components.")
            for component in value:
                number(component, key, -1000000, 1000000)
        elif key == "rotation":
            number(value, key, -1000000, 1000000)
        elif key == "opacity":
            number(value, key, 0, 100)
        elif key == "track_type":
            if value not in ("video", "audio"):
                raise ValidationError("track_type must be video or audio.")
        elif key in ("track_index", "companion_track_index"):
            number(value, key, 0, 10000, integer=True)
        elif key == "time_seconds":
            number(value, key, 0, 10800000)
    if operation == "set_layer_transform" and not set(args).intersection(("position", "scale", "rotation", "opacity")):
        raise ValidationError("Specify at least one transform property.")
    return result


def token_path(app):
    if app not in DEFAULT_PORTS:
        raise ValidationError("app must be aftereffects or premiere.")
    return ROOT / ".runtime" / f"{app}-token.txt"


def load_token(app, create=False):
    path = token_path(app)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(48))
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or any(c.isspace() for c in token):
        raise ValidationError(f"Invalid token file: regenerate {path.name} with at least 32 random characters.")
    return token


def decode_state(raw, app):
    # The HTTP budget applies to each request, while a journal aggregates up to
    # 64 receipts plus one pending request and adds two container levels.
    if len(raw.encode("utf-8")) > MAX_STATE:
        raise ValidationError("Broker journal exceeds its byte limit; inspect Adobe before recovery.")
    state = strict_loads(raw, max_depth=36, max_values=20000 * (MAX_RECEIPTS + 1) + 100)
    if not isinstance(state, dict) or set(state) != {"app", "pending", "receipts"} or state["app"] != app:
        raise ValidationError("Invalid broker journal schema; inspect Adobe before recovery.")
    receipts = state["receipts"]
    if not isinstance(receipts, dict) or len(receipts) > MAX_RECEIPTS:
        raise ValidationError("Invalid broker receipt cache.")
    total = 0
    def job_id(value):
        if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
            raise ValidationError("Invalid journal job ID.")
    for identifier, result in receipts.items():
        job_id(identifier)
        if not isinstance(result, dict):
            raise ValidationError("Journal receipts must be result objects.")
        # Match the original /result envelope's depth/value/byte budget.
        encoded = json.dumps({"id": identifier, "result": result}, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_BODY:
            raise ValidationError("Journal receipt exceeds the HTTP request budget.")
        strict_loads(encoded)
        total += len(json.dumps(result))
    if total > MAX_RECEIPT_BYTES:
        raise ValidationError("Journal receipt cache exceeds its aggregate byte budget.")
    pending = state["pending"]
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) != {"id", "operation", "args", "expires_at"}:
            raise ValidationError("Invalid pending journal job schema.")
        job_id(pending["id"])
        if pending["id"] in receipts or not isinstance(pending["args"], dict):
            raise ValidationError("Invalid pending journal job arguments or duplicate ID.")
        text(pending["operation"], "journal operation")
        number(pending["expires_at"], "journal expires_at", 0)
        encoded = json.dumps(pending, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_BODY + 4096:
            raise ValidationError("Pending journal job exceeds the request budget.")
        strict_loads(encoded)
    return state


class Broker:
    def __init__(self, app, state_path=None):
        if app not in DEFAULT_PORTS:
            raise ValidationError("app must be aftereffects or premiere.")
        self.app = app
        self.condition = threading.Condition()
        self.active = None
        self.last_poll = None
        self.receipts = {}  # Bounded acknowledgments allow safe /result delivery retries.
        self.state_path = Path(state_path) if state_path else None
        if self.state_path and self.state_path.exists():
            with self.state_path.open("rb") as stream:
                raw = stream.read(MAX_STATE + 1)
            if len(raw) > MAX_STATE:
                raise ValidationError("Broker journal exceeds its byte limit; inspect Adobe before recovery.")
            state = decode_state(raw.decode("utf-8"), app)
            self.receipts = state["receipts"]
            pending = state["pending"]
            if pending is not None:
                self.active = {**pending, "claimed": True, "unknown": True, "result": None, "deadline": 0}

    def persist(self, pending):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump({"app": self.app, "pending": pending, "receipts": self.receipts}, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)

    def health(self):
        with self.condition:
            return {"success": True, "app": self.app, "protocol": 1,
                    "plugin_connected": self.last_poll is not None and time.monotonic() - self.last_poll < 10,
                    "busy": self.active is not None,
                    "outcome_unknown": bool(self.active and self.active["unknown"]),
                    "last_result": ({"job_id": next(reversed(self.receipts)), "result": self.receipts[next(reversed(self.receipts))]} if self.receipts else None)}

    def call(self, operation, args, timeout=30):
        try:
            args = validate_operation(self.app, operation, args)
            number(timeout, "timeout", 0.01, MAX_TIMEOUT)
        except (ValidationError, OverflowError) as exc:
            return error("validation_error", str(exc))
        with self.condition:
            if self.active is not None:
                return error("busy", "Adobe is busy. Wait for the current job or its late result; do not retry a timed-out mutation.", outcome_unknown=self.active["unknown"])
            if self.last_poll is None or time.monotonic() - self.last_poll >= 10:
                return error("disconnected", "Open the Adobe app and its MCP panel, then wait for the panel to connect.")
            job = {"id": secrets.token_hex(16), "operation": operation, "args": args,
                   "expires_at": time.time() + timeout, "deadline": time.monotonic() + timeout,
                   "claimed": False, "unknown": False, "result": None}
            self.active = job
            while job["result"] is None:
                remaining = job["deadline"] - time.monotonic()
                if remaining <= 0:
                    if job["claimed"]:
                        job["unknown"] = True
                        return error("timeout", "Adobe accepted the job but has not returned its result. Outcome is unknown; do not retry. Wait for the late result.", outcome_unknown=True, job_id=job["id"])
                    self.active = None
                    return error("timeout", "The panel did not claim the job before its deadline. No operation was dispatched.", outcome_unknown=False, job_id=job["id"])
                self.condition.wait(remaining)
            return job["result"]

    def next(self):
        with self.condition:
            self.last_poll = time.monotonic()
            job = self.active
            if not job or job["claimed"]:
                return {"job": None}
            if time.monotonic() >= job["deadline"]:
                return {"job": None}
            public_job = {key: job[key] for key in ("id", "operation", "args", "expires_at")}
            # Persist before handing execution rights to the panel. Failure to write
            # means no dispatch; restart conservatively retains uncertain work.
            try:
                self.persist(public_job)
            except OSError:
                return error("state_write_failed", "Cannot journal dispatch safely. Fix runtime directory permissions; no job was delivered.", job=None)
            job["claimed"] = True
            return {"job": public_job}

    def result(self, job_id, result):
        with self.condition:
            if job_id in self.receipts:
                if self.receipts[job_id] == result:
                    return {"success": True}
                return error("conflicting_result", "This job already has a different result. Keep the original receipt; never replay the operation.")
            job = self.active
            if not job or not job["claimed"] or job["id"] != job_id:
                return error("unknown_job", "No claimed job matches this result ID; never replay the Adobe operation.")
            previous_receipts = dict(self.receipts)
            self.receipts[job_id] = result
            # Bound both entry count and bytes: result bodies may approach MAX_BODY.
            while len(self.receipts) > MAX_RECEIPTS or sum(len(json.dumps(item)) for item in self.receipts.values()) > MAX_RECEIPT_BYTES:
                del self.receipts[next(iter(self.receipts))]
            try:
                self.persist(None)
            except OSError:
                self.receipts = previous_receipts
                return error("state_write_failed", "Cannot persist the result receipt. Keep and retry this receipt; do not execute the operation again.")
            job["result"] = result
            self.active = None
            self.condition.notify_all()
            return {"success": True}


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, app, port=None, token=None):
        self.broker = Broker(app, ROOT / ".runtime" / f"{app}-state.json" if token is None else None)
        self.token = token if token is not None else load_token(app, create=True)
        super().__init__(("127.0.0.1", DEFAULT_PORTS[app] if port is None else port), BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass  # Never log bearer tokens or payloads.

    def reply(self, status, payload):
        raw = json.dumps(payload, allow_nan=False, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if getattr(self, "cep_origin", None):
            self.send_header("Access-Control-Allow-Origin", self.cep_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(raw)

    def guard(self, preflight=False):
        self.cep_origin = None
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_port
        if len(hosts) != 1 or hosts[0].lower() not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.reply(403, error("forbidden_host", "Use the loopback bridge host and exact port."))
            return False
        origins = self.headers.get_all("Origin", [])
        if origins:
            # CEP file panels serialize their opaque origin as null. Some CEP
            # versions send file://; only these exact values are permitted.
            if len(origins) != 1 or origins[0] not in ("null", "file://"):
                self.reply(403, error("forbidden_origin", "Only local CEP file panel origins are allowed."))
                return False
            self.cep_origin = origins[0]
        if not preflight:
            auth = self.headers.get_all("Authorization", [])
            if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("utf-8"), ("Bearer " + self.server.token).encode("utf-8")):
                self.reply(401, error("unauthorized", "Supply the app-specific bridge token as Authorization: Bearer <token>."))
                return False
        return True

    def do_OPTIONS(self):
        if not self.guard(preflight=True):
            return
        if self.path not in ("/health", "/next", "/call", "/result"):
            self.reply(404, error("not_found", "Unknown bridge endpoint."))
            return
        requested = self.headers.get("Access-Control-Request-Headers", "")
        if any(h.strip().lower() not in ("authorization", "content-type") for h in requested.split(",") if h.strip()):
            self.reply(403, error("forbidden_headers", "Only Authorization and Content-Type are permitted."))
            return
        self.send_response(204)
        if self.cep_origin:
            self.send_header("Access-Control-Allow-Origin", self.cep_origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.guard():
            return
        if self.path == "/health":
            self.reply(200, self.server.broker.health())
        elif self.path == "/next":
            self.reply(200, self.server.broker.next())
        else:
            self.reply(404, error("not_found", "Use /health or /next."))

    def do_POST(self):
        if not self.guard():
            return
        if self.path not in ("/call", "/result"):
            self.reply(404, error("not_found", "Use /call or /result."))
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValidationError("Transfer-Encoding is unsupported; send Content-Length.")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_BODY:
                raise ValidationError(f"Content-Length must be between 1 and {MAX_BODY} bytes.")
            if self.headers.get_content_type() != "application/json":
                raise ValidationError("Content-Type must be application/json.")
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]):
                raise ValidationError("Incomplete request body.")
            body = strict_loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValidationError("Request body must be a JSON object.")
            if self.path == "/call":
                if not {"operation", "args"} <= body.keys() or body.keys() - {"operation", "args", "timeout"}:
                    raise ValidationError("/call requires operation and args, with optional timeout.")
                result = self.server.broker.call(body["operation"], body["args"], body.get("timeout", 30))
            else:
                if set(body) != {"id", "result"} or not isinstance(body["result"], dict):
                    raise ValidationError("/result requires id and a result object.")
                text(body["id"], "id")
                # json.loads accepts numeric overflow such as 1e999; enforce finite recursively.
                json.dumps(body["result"], allow_nan=False)
                result = self.server.broker.result(body["id"], body["result"])
            self.reply(200, result)
        except (ValueError, UnicodeError, OverflowError, RecursionError) as exc:
            self.reply(400, error("validation_error", str(exc)))
        except (TimeoutError, OSError):
            self.close_connection = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=tuple(DEFAULT_PORTS))
    parser.add_argument("--port", type=int)
    options = parser.parse_args(argv)
    server = BridgeServer(options.app, options.port)
    print(f"{options.app} bridge listening on 127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
