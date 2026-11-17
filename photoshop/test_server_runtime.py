"""Runtime contract tests; no Photoshop, COM installation, or MCP dependency required.

Run: python -B -m unittest discover -s photoshop -p test_server_runtime.py -v
"""

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch


def load_server():
    com = types.ModuleType("comtypes")
    client = types.ModuleType("comtypes.client")

    class COMError(Exception):
        def __init__(self, hresult):
            self.hresult = hresult
            super().__init__(str(hresult))

    com.COMError = COMError
    com.CoInitialize = Mock()
    com.client = client
    client.GetActiveObject = Mock()
    client.CreateObject = Mock()
    fastmcp = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self):
            return lambda function: function

    fastmcp.FastMCP = FastMCP
    fastmcp.Image = Mock()
    modules = {"comtypes": com, "comtypes.client": client,
               "mcp": types.ModuleType("mcp"), "mcp.server": types.ModuleType("mcp.server"),
               "mcp.server.fastmcp": fastmcp}
    spec = importlib.util.spec_from_file_location("photoshop_runtime_under_test", Path(__file__).with_name("server.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.dict(os.environ, {"PS_UXP_ENABLED": "0"}):
        spec.loader.exec_module(module)
    return module


server = load_server()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ps = server.PS()
        self.app = Mock()
        self.app.Name = "Photoshop"
        self.app.DoJavaScript.side_effect = lambda code: code
        self.connect = patch.object(self.ps, "_connect", return_value=self.app)
        self.connect.start()
        self.addCleanup(self.connect.stop)
        self.addCleanup(self.ps._pool.shutdown, wait=True, cancel_futures=True)

    async def wait_started(self, event):
        self.assertTrue(await asyncio.to_thread(event.wait, 1), "worker did not start")

    async def settle(self):
        # Join the actual worker before asserting late-result recovery.
        if self.ps._pending is not None:
            try:
                await asyncio.wrap_future(self.ps._pending)
            except Exception:
                pass

    def blocking_script(self, fail=False):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def run(code):
            started.set()
            if not release.wait(2):
                raise AssertionError("test did not release worker")
            if fail:
                raise ValueError("late failure")
            return code

        self.app.DoJavaScript.side_effect = run
        return started, release

    async def test_concurrent_calls_serialize_and_preserve_com_thread(self):
        started, release = self.blocking_script()
        threads = []
        original = self.app.DoJavaScript.side_effect

        def run(code):
            threads.append(threading.get_ident())
            return original(code)

        self.app.DoJavaScript.side_effect = run
        self.ps._connect.side_effect = lambda: (threads.append(threading.get_ident()), self.app)[1]
        first = asyncio.create_task(self.ps.run("first", 1))
        await self.wait_started(started)
        second = asyncio.create_task(self.ps.run("second", 1))
        await asyncio.sleep(0)
        self.assertEqual(self.app.DoJavaScript.call_count, 1)
        release.set()
        self.assertEqual(await asyncio.gather(first, second), ["first", "second"])
        self.assertEqual(len(set(threads)), 1)
        self.assertNotEqual(threads[0], threading.get_ident())

    async def test_timeout_blocks_new_and_already_queued_calls_until_late_success(self):
        started, release = self.blocking_script()
        pool = self.ps._pool
        first = asyncio.create_task(self.ps.run("mutation", .05))
        await self.wait_started(started)
        queued = asyncio.create_task(self.ps.run("queued mutation", 1))
        with self.assertRaises(server.OutcomeUnknownError):
            await first
        with self.assertRaises(server.OutcomeUnknownError):
            await queued
        with self.assertRaises(server.OutcomeUnknownError):
            await self.ps.run("new mutation")
        self.assertEqual(self.app.DoJavaScript.call_count, 1)
        self.assertIs(self.ps._pool, pool)
        release.set()
        await self.settle()
        self.assertEqual(await self.ps.run("inspect"), "inspect")
        self.assertEqual([c.args[0] for c in self.app.DoJavaScript.call_args_list], ["mutation", "inspect"])
        self.assertEqual(self.ps._connect.call_count, 1)

    async def test_late_failure_is_consumed_and_allows_recovery(self):
        started, release = self.blocking_script(fail=True)
        errors = []
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        try:
            with self.assertRaises(server.OutcomeUnknownError):
                await self.ps.run("mutation", .02)
            release.set()
            await self.settle()
            self.app.DoJavaScript.side_effect = lambda code: code
            self.assertEqual(await self.ps.run("inspect"), "inspect")
            await asyncio.sleep(0)
            self.assertEqual(errors, [])
        finally:
            loop.set_exception_handler(old_handler)

    async def test_cancellation_does_not_release_running_com_call(self):
        started, release = self.blocking_script()
        task = asyncio.create_task(self.ps.run("mutation", 1))
        await self.wait_started(started)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(server.OutcomeUnknownError):
            await self.ps.run("duplicate")
        release.set()
        await self.settle()
        self.assertEqual(await self.ps.run("inspect"), "inspect")
        self.assertEqual(self.app.DoJavaScript.call_count, 2)

    async def test_queue_bound_and_queue_timeout_never_dispatch(self):
        self.ps.MAX_WAITERS = 1
        started, release = self.blocking_script()
        first = asyncio.create_task(self.ps.run("active", 1))
        await self.wait_started(started)
        queued = asyncio.create_task(self.ps.run("expired", .02))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(RuntimeError, "đã đầy"):
            await self.ps.run("overflow")
        with self.assertRaisesRegex(RuntimeError, "chưa được gửi"):
            await queued
        self.assertEqual(self.app.DoJavaScript.call_count, 1)
        release.set()
        self.assertEqual(await first, "active")
        self.assertEqual(await self.ps.run("after"), "after")
        self.assertEqual(self.ps._waiters, 0)

    async def test_cancelled_waiter_never_dispatches(self):
        started, release = self.blocking_script()
        first = asyncio.create_task(self.ps.run("active", 1))
        await self.wait_started(started)
        queued = asyncio.create_task(self.ps.run("cancelled", 1))
        await asyncio.sleep(0)
        queued.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queued
        release.set()
        await first
        self.assertEqual(self.app.DoJavaScript.call_count, 1)
        self.assertEqual(self.ps._waiters, 0)

    async def test_cancellation_at_gate_handoff_never_dispatches(self):
        await self.ps._gate.acquire()
        task = asyncio.create_task(self.ps.run("mutation", 1))
        # Queue acquire even when admission uses a separate task (Python 3.11 wait_for).
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(self.ps._waiters, 1)
        self.ps._gate.release()
        asyncio.get_running_loop().call_soon(task.cancel)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(task.cancelled())
        self.app.DoJavaScript.assert_not_called()
        self.assertIsNone(self.ps._pending)
        self.assertFalse(self.ps._gate.locked())
        self.assertEqual(self.ps._waiters, 0)
        self.assertEqual(await self.ps.run("inspect", 1), "inspect")
        self.app.DoJavaScript.assert_called_once_with("inspect")

    async def test_disconnect_after_mutation_never_replays_and_next_call_reconnects(self):
        replacement = Mock(Name="Photoshop")
        replacement.DoJavaScript.return_value = "inspected"
        self.ps._connect.side_effect = [self.app, replacement]
        self.app.DoJavaScript.side_effect = server.COMError(next(iter(server.DISCONNECTED)))
        with self.assertRaises(server.OutcomeUnknownError):
            await self.ps.run("mutation")
        self.app.DoJavaScript.assert_called_once_with("mutation")
        self.assertEqual(self.ps._connect.call_count, 1)
        self.assertEqual(await self.ps.run("inspect"), "inspected")
        replacement.DoJavaScript.assert_called_once_with("inspect")

    async def test_stale_connection_probe_reconnects_before_dispatch(self):
        class StaleApp:
            @property
            def Name(self):
                raise server.COMError(next(iter(server.DISCONNECTED)))

        self.ps._app = StaleApp()
        self.assertEqual(await self.ps.run("mutation"), "mutation")
        self.app.DoJavaScript.assert_called_once_with("mutation")

    async def test_busy_rejection_can_retry_but_other_script_error_cannot(self):
        self.app.DoJavaScript.side_effect = [server.COMError(next(iter(server.BUSY))), "ok"]
        with patch.object(server.time, "sleep"):
            self.assertEqual(await self.ps.run("mutation"), "ok")
        self.assertEqual(self.app.DoJavaScript.call_count, 2)
        self.app.DoJavaScript.reset_mock()
        self.app.DoJavaScript.side_effect = ValueError("script failed after partial mutation")
        with self.assertRaises(ValueError):
            await self.ps.run("partial")
        self.app.DoJavaScript.assert_called_once_with("partial")

    async def test_jsx_preserves_success_contract_and_marks_unknown_outcome(self):
        with patch.object(server, "ps", self.ps):
            self.app.DoJavaScript.side_effect = None
            self.app.DoJavaScript.return_value = '{"success":true,"result":{"version":"28"}}'
            self.assertEqual(await server.jsx("info", "return {};"), {"success": True, "version": "28"})
            self.app.DoJavaScript.side_effect = server.COMError(next(iter(server.DISCONNECTED)))
            result = await server.jsx("mutation", "return {};")
            self.assertFalse(result["success"])
            self.assertTrue(result["outcome_unknown"])

    async def test_invalid_timeout_never_dispatches(self):
        for timeout in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                await self.ps.run("mutation", timeout)
        self.app.DoJavaScript.assert_not_called()


if __name__ == "__main__":
    unittest.main()
