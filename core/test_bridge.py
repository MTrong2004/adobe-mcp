"""Run with: python -m unittest core.test_bridge -v"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from core.bridge import Broker, BridgeServer, MAX_BODY, ValidationError, strict_loads, validate_operation
from core.client import BridgeClient


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = Broker("aftereffects")
        self.broker.next()

    def start_call(self, timeout=1):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.broker.call("session_info", {}, timeout)))
        worker.start()
        # Synchronize on broker state, with a hard deadline to diagnose failures.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with self.broker.condition:
                if self.broker.active:
                    break
            threading.Event().wait(.001)
        return worker, result

    def test_single_claim_serialization_and_result(self):
        worker, result = self.start_call()
        job = self.broker.next()["job"]
        self.assertIsNotNone(job)
        self.assertIsNone(self.broker.next()["job"])
        self.assertEqual(self.broker.call("session_info", {})["error"]["code"], "busy")
        self.assertFalse(self.broker.result("wrong", {})["success"])
        self.assertTrue(self.broker.result(job["id"], {"success": True, "value": 42})["success"])
        worker.join(1)
        self.assertEqual(result, [{"success": True, "value": 42}])
        self.assertFalse(self.broker.health()["busy"])
        self.assertTrue(self.broker.result(job["id"], {"success": True, "value": 42})["success"])
        self.assertFalse(self.broker.result(job["id"], {})["success"])
        second_worker, second_result = self.start_call()
        second_job = self.broker.next()["job"]
        self.assertTrue(self.broker.result(job["id"], {"success": True, "value": 42})["success"])
        self.assertTrue(self.broker.health()["busy"])
        self.broker.result(second_job["id"], {"success": True})
        second_worker.join(1)
        self.assertEqual(second_result, [{"success": True}])

    def test_restart_preserves_claim_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            self.broker = Broker("aftereffects", state_path)
            self.broker.next()
            worker, response = self.start_call(.03)
            job = self.broker.next()["job"]
            worker.join(1)
            restored = Broker("aftereffects", state_path)
            self.assertTrue(restored.health()["outcome_unknown"])
            self.assertIsNone(restored.next()["job"])
            self.assertEqual(restored.call("session_info", {})["error"]["code"], "busy")
            restored.result(job["id"], {"success": True})
            completed = Broker("aftereffects", state_path)
            self.assertFalse(completed.health()["busy"])
            self.assertEqual(completed.health()["last_result"]["job_id"], job["id"])
            self.assertTrue(completed.result(job["id"], {"success": True})["success"])

    def test_restart_aggregates_large_receipts_and_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            self.broker = Broker("aftereffects", state_path)
            self.broker.next()
            identifiers = []
            payload = {"success": True, "values": list(range(12000))}
            for _ in range(2):
                worker, response = self.start_call()
                job = self.broker.next()["job"]
                identifiers.append(job["id"])
                self.assertTrue(self.broker.result(job["id"], payload)["success"])
                worker.join(1)
                self.assertEqual(response, [payload])
            worker, response = self.start_call(.03)
            pending = self.broker.next()["job"]
            worker.join(1)
            restored = Broker("aftereffects", state_path)
            self.assertTrue(restored.health()["outcome_unknown"])
            self.assertEqual(restored.active["id"], pending["id"])
            for identifier in identifiers:
                self.assertTrue(restored.result(identifier, payload)["success"])
            self.assertTrue(restored.health()["busy"])
            self.assertTrue(restored.result(pending["id"], {"success": True})["success"])
            self.assertFalse(Broker("aftereffects", state_path).health()["busy"])
            malformed = json.loads(state_path.read_text())
            malformed["extra"] = True
            state_path.write_text(json.dumps(malformed))
            with self.assertRaises(ValidationError):
                Broker("aftereffects", state_path)

    def test_claimed_timeout_blocks_until_late_result(self):
        worker, result = self.start_call(.05)
        job = self.broker.next()["job"]
        worker.join(1)
        self.assertTrue(result[0]["outcome_unknown"])
        self.assertTrue(self.broker.health()["outcome_unknown"])
        self.assertIsNone(self.broker.next()["job"])
        self.assertEqual(self.broker.call("session_info", {})["error"]["code"], "busy")
        self.broker.result(job["id"], {"success": True})
        self.assertFalse(self.broker.health()["busy"])

    def test_unclaimed_timeout_is_not_dispatched(self):
        response = self.broker.call("session_info", {}, .02)
        self.assertFalse(response["outcome_unknown"])
        self.assertFalse(self.broker.health()["busy"])
        self.assertIsNone(self.broker.next()["job"])

    def test_disconnected_and_bad_timeout(self):
        self.assertEqual(Broker("premiere").call("session_info", {})["error"]["code"], "disconnected")
        for timeout in (True, float("nan"), float("inf"), 0, 301, "2"):
            self.assertEqual(self.broker.call("session_info", {}, timeout)["error"]["code"], "validation_error")


class ValidationTests(unittest.TestCase):
    def test_strict_json(self):
        for raw in ('{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', '{"a":1,"a":2}'):
            with self.assertRaises(ValueError):
                strict_loads(raw)

    def test_json_depth_and_companion_track(self):
        with self.assertRaises(ValidationError):
            strict_loads("[" * 34 + "0" + "]" * 34)
        args = {"sequence_id": "s", "project_item_id": "p", "track_type": "video", "track_index": 0, "time_seconds": 0, "companion_track_index": 2}
        self.assertEqual(validate_operation("premiere", "insert_clip", args), args)
        args["companion_track_index"] = True
        with self.assertRaises(ValidationError):
            validate_operation("premiere", "insert_clip", args)

    def test_app_schemas_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mov"
            source.write_bytes(b"test")
            self.assertEqual(validate_operation("premiere", "import_media", {"paths": [str(source)]})["paths"], [str(source)])
            validate_operation("aftereffects", "save_project", {"path": str(source), "overwrite": True})
            for operation, args in (("save_project", {"path": str(source)}), ("import_media", {"path": "relative.mov"}), ("import_media", {"path": str(source) + "missing"}), ("save_project", {"path": str(source), "overwrite": 1})):
                with self.assertRaises(ValidationError):
                    validate_operation("aftereffects", operation, args)
        for app, operation, args in (
            ("aftereffects", "add_layer", {"comp_id": True, "item_id": 2}),
            ("aftereffects", "set_layer_transform", {"comp_id": 1, "layer_index": 1}),
            ("aftereffects", "set_layer_transform", {"comp_id": 1, "layer_index": 1, "position": [1, float("inf")]}),
            ("premiere", "create_sequence", {"name": "x", "item_node_ids": [1]}),
            ("premiere", "insert_clip", {"sequence_id": "s", "project_item_id": "p", "track_type": "bad", "track_index": 0, "time_seconds": 0}),
            ("aftereffects", "session_info", {"extra": 1}),
            ("premiere", "execute_js", {}),
        ):
            with self.assertRaises(ValidationError):
                validate_operation(app, operation, args)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = "t" * 48
        cls.server = BridgeServer("aftereffects", 0, cls.token)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, endpoint, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        defaults = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        defaults.update(headers or {})
        connection.request(method, endpoint, body=body, headers=defaults)
        response = connection.getresponse()
        status, response_headers, raw = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, json.loads(raw) if raw else None

    def test_auth_host_origin_and_preflight(self):
        self.assertEqual(self.request("GET", "/health", headers={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.request("GET", "/health", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("GET", "/health", headers={"Origin": "https://attacker.example"})[0], 403)
        for origin in ("null", "file://"):
            status, headers, result = self.request("GET", "/health", headers={"Origin": origin})
            self.assertEqual(status, 200)
            self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
            self.assertEqual(result["protocol"], 1)
        status, headers, _ = self.request("OPTIONS", "/call", headers={"Origin": "null", "Authorization": "", "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(status, 204)
        self.assertNotIn("*", headers.values())

    def test_bounded_strict_body(self):
        for body in ('{"operation":"session_info","args":{},"timeout":NaN}', '{"operation":"session_info","args":{"nested":1e999}}', '[]'):
            self.assertEqual(self.request("POST", "/call", body)[0], 400)
        self.assertEqual(self.request("POST", "/call", "{}", {"Content-Length": str(MAX_BODY + 1)})[0], 400)

    def test_health_preserves_near_limit_receipt(self):
        # Health's wrapper is larger than the original /result wrapper. Keep
        # the complete receipt, including non-ASCII data, across this boundary.
        identifier = "a" * 32
        payload = {"success": True, "value": "x" * (MAX_BODY - 100)}
        envelope = json.dumps({"id": identifier, "result": payload}, separators=(",", ":")).encode()
        self.assertLess(len(envelope), MAX_BODY)
        with self.server.broker.condition:
            old = self.server.broker.receipts
            self.server.broker.receipts = {identifier: payload}
        try:
            with patch("core.client.load_token", return_value=self.token):
                result = BridgeClient("aftereffects", self.port).health()
            self.assertTrue(result["success"])
            self.assertEqual(result["last_result"]["result"], payload)
            self.assertGreater(len(json.dumps(result).encode()), MAX_BODY)
        finally:
            with self.server.broker.condition:
                self.server.broker.receipts = old

    def test_full_http_call_and_client(self):
        self.request("GET", "/next")
        result = []
        with patch("core.client.load_token", return_value=self.token):
            client = BridgeClient("aftereffects", self.port)
            self.assertTrue(client.health()["success"])
            thread = threading.Thread(target=lambda: result.append(client.call("session_info", {}, 1)))
            thread.start()
            deadline = time.monotonic() + 1
            job = None
            while not job and time.monotonic() < deadline:
                job = self.request("GET", "/next")[2]["job"]
            self.assertIsNotNone(job)
            ack = self.request("POST", "/result", json.dumps({"id": job["id"], "result": {"success": True, "app": "aftereffects"}}))[2]
            self.assertTrue(ack["success"])
            thread.join(2)
            self.assertEqual(result, [{"success": True, "app": "aftereffects"}])


class ClientTests(unittest.TestCase):
    def test_missing_token_and_local_validation(self):
        with patch("core.client.load_token", side_effect=FileNotFoundError):
            client = BridgeClient("premiere")
            self.assertEqual(client.health()["error"]["code"], "disconnected")
            self.assertEqual(client.call("session_info", {})["error"]["code"], "disconnected")
        with patch.object(BridgeClient, "_request") as request:
            result = BridgeClient("premiere").call("insert_clip", {})
            self.assertEqual(result["error"]["code"], "validation_error")
            request.assert_not_called()

    def test_socket_timeout_unknown_and_no_proxy(self):
        client = BridgeClient("aftereffects")
        self.assertFalse(any(getattr(handler, "proxies", None) for handler in client.opener.handlers))
        with patch("core.client.load_token", return_value="t" * 48), patch.object(client.opener, "open", side_effect=TimeoutError):
            self.assertTrue(client.call("session_info", {})["outcome_unknown"])
            self.assertFalse(client.health()["outcome_unknown"])


if __name__ == "__main__":
    unittest.main()
