"""Proxy-free local client for core.bridge; never automatically retries jobs."""
from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .bridge import DEFAULT_PORTS, MAX_BODY, MAX_RESPONSE, MAX_TIMEOUT, ValidationError, error, load_token, number, strict_loads, validate_operation


class BridgeClient:
    def __init__(self, app, port=None):
        if app not in DEFAULT_PORTS:
            raise ValidationError("app must be aftereffects or premiere.")
        self.app = app
        self.port = DEFAULT_PORTS[app] if port is None else port
        number(self.port, "port", 1, 65535, integer=True)
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.opener = build_opener(ProxyHandler({}))

    def _request(self, endpoint, payload=None, timeout=5):
        try:
            token = load_token(self.app)
        except (OSError, ValidationError):
            return error("disconnected", "Bridge token is missing or invalid. Start the app bridge and open its MCP panel.", outcome_unknown=False)
        raw = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
        if raw is not None and len(raw) > MAX_BODY:
            return error("validation_error", f"Request exceeds the {MAX_BODY}-byte limit.", outcome_unknown=False)
        request = Request(self.base_url + endpoint, data=raw, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    raise ValueError("Bridge response exceeds the size limit.")
                # Health adds wrapper fields around one valid /result receipt.
                result = strict_loads(body.decode("utf-8"), max_depth=36, max_values=20100)
                if not isinstance(result, dict):
                    raise ValueError("Bridge response must be a JSON object.")
                json.dumps(result, allow_nan=False)
                return result
        except HTTPError as exc:
            try:
                body = exc.read(MAX_BODY + 1)
                if len(body) <= MAX_BODY:
                    result = strict_loads(body.decode("utf-8"))
                    if isinstance(result, dict):
                        json.dumps(result, allow_nan=False)
                        return result
            except (ValueError, UnicodeError, RecursionError):
                pass
            return error("http_error", f"Bridge returned HTTP {exc.code}; inspect the bridge and panel connection.", outcome_unknown=payload is not None)
        except (socket.timeout, TimeoutError):
            return error("timeout", "Bridge response timed out. A submitted operation may have executed; do not retry automatically.", outcome_unknown=payload is not None)
        except (URLError, OSError) as exc:
            return error("disconnected", "Cannot reach the bridge. Start the bridge and open the Adobe MCP panel. A submitted call must not be retried until its outcome is checked.", outcome_unknown=payload is not None)
        except (ValueError, UnicodeError, RecursionError):
            return error("invalid_response", "Bridge returned invalid JSON. Check the app before retrying any submitted operation.", outcome_unknown=payload is not None)

    def health(self):
        return self._request("/health")

    def call(self, operation, args, timeout=30):
        try:
            args = validate_operation(self.app, operation, args)
            number(timeout, "timeout", 0.01, MAX_TIMEOUT)
        except (ValidationError, OverflowError) as exc:
            return error("validation_error", str(exc), outcome_unknown=False)
        return self._request("/call", {"operation": operation, "args": args, "timeout": timeout}, timeout=timeout + 5)
