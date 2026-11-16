import concurrent.futures
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from uxp_bridge import Broker, Server, validate


class BrokerTests(unittest.TestCase):
    def test_validation(self):
        for op, args in [("execute", {}), ("update_layer", {"document_id": 1}),
                         ("update_layer", {"document_id": 1, "layer_id": 2, "opacity": float('nan')}),
                         ("document_info", {"document_id": True}), ("session_info", {"x": 1})]:
            with self.assertRaises(ValueError):
                validate(op, args)
        validate("update_layer", {"document_id": 1, "layer_id": 2, "visible": False, "opacity": 0})

    def test_disconnected(self):
        self.assertFalse(Broker().call("session_info", {})["success"])

    def test_roundtrip_and_no_redelivery(self):
        b = Broker()
        b.next()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(b.call, "session_info", {}, 2)
            deadline = time.monotonic() + 1
            job = None
            while job is None and time.monotonic() < deadline:
                job = b.next()["job"]
                if job is None:
                    threading.Event().wait(.001)
            self.assertIsNotNone(job)
            self.assertIsNone(b.next()["job"])
            self.assertFalse(b.call("session_info", {})["success"])
            b.finish({"id": job["id"], "result": {"success": True, "version": "28"}})
            self.assertEqual(future.result()["version"], "28")
            b.finish({"id": job["id"], "result": {"success": True}})
        self.assertFalse(b.status()["busy"])

    def test_undelivered_timeout_drops_job(self):
        b = Broker()
        b.next()
        self.assertFalse(b.call("session_info", {}, .01)["success"])
        self.assertIsNone(b.next()["job"])

    def test_delivered_timeout_blocks_until_late_result(self):
        b = Broker()
        b.next()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            f = pool.submit(b.call, "session_info", {}, .05)
            job = None
            while job is None:
                job = b.next()["job"]
                if not job:
                    threading.Event().wait(.001)
            self.assertTrue(f.result()["outcome_unknown"])
        self.assertTrue(b.status()["busy"])
        self.assertIsNone(b.next()["job"])
        b.finish({"id": job["id"], "error": "Expired"})
        self.assertFalse(b.status()["busy"])

    def test_http_auth_and_bad_body(self):
        server = Server(("127.0.0.1", 0), "x" * 32)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open(base + '/health')
            self.assertEqual(e.exception.code, 401)
            req = urllib.request.Request(base + '/health', headers={'Authorization': 'Bearer ' + 'x'*32})
            with opener.open(req) as r:
                self.assertEqual(json.load(r)['protocol'], 1)
            req = urllib.request.Request(base + '/call', data=b'[]', headers={'Authorization': 'Bearer ' + 'x'*32})
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open(req)
            self.assertEqual(e.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
