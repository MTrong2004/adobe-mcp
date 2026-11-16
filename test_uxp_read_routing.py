"""Item 1a contract/routing tests; no Photoshop, credentials, or private PSD needed."""
import ast
import asyncio
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from uxp_bridge import validate
import uxp_tools

SOURCE = Path(__file__).with_name('server.py')
NAMES = ('photoshop_get_session_info', 'photoshop_get_active_document_info', 'photoshop_get_selection_info')


def read_functions():
    # Load the real functions without importing COM or creating an MCP runtime.
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in NAMES]
    for node in selected:
        node.decorator_list = []
    namespace = {'os': os, 'jsx': AsyncMock(return_value={'success': True, 'source': 'com'})}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class ReadRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_com_remains_default(self):
        for flag in (None, '', '0', 'true'):
            with patch.dict(os.environ, {}, clear=True):
                if flag is not None:
                    os.environ['PS_UXP_ENABLED'] = flag
                ns = read_functions()
                with patch.object(uxp_tools, 'call', new_callable=AsyncMock) as call:
                    for name in NAMES:
                        self.assertEqual((await ns[name]())['source'], 'com')
                    call.assert_not_called()
                    self.assertEqual(ns['jsx'].await_count, 3)

    async def test_opt_in_forwards_unchanged_contract_and_arguments(self):
        ns = read_functions()
        response = {'success': True, 'has_selection': False}
        with patch.dict(os.environ, {'PS_UXP_ENABLED': '1'}), patch.object(uxp_tools, 'call', new_callable=AsyncMock, return_value=response) as call:
            for name in NAMES:
                result = await ns[name]()
                self.assertIs(result, response)
            self.assertEqual(call.await_args_list[0].args, ('get_session_info', {}))
            self.assertEqual(call.await_args_list[1].args, ('get_active_document_info', {'include_layers': True, 'max_depth': -1}))
            self.assertEqual(call.await_args_list[2].args, ('get_selection_info', {}))
            await ns[NAMES[1]](False, -5)
            call.assert_awaited_with('get_active_document_info', {'include_layers': False, 'max_depth': -5})
            ns['jsx'].assert_not_called()

    async def test_uxp_failure_never_falls_back_to_com(self):
        ns = read_functions()
        failure = {'success': False, 'error': 'Photoshop đang bận'}
        with patch.dict(os.environ, {'PS_UXP_ENABLED': '1'}), patch.object(uxp_tools, 'call', new_callable=AsyncMock, return_value=failure):
            for name in NAMES:
                self.assertIs(await ns[name](), failure)
            ns['jsx'].assert_not_called()

    def test_read_allowlist_and_legacy_depth(self):
        validate('get_session_info', {})
        validate('get_selection_info', {})
        for depth in (-50, -1, 0, 1000):
            validate('get_active_document_info', {'include_layers': True, 'max_depth': depth})
        for operation, args in [('get_selection_info', {'document_id': 1}),
                                ('get_active_document_info', {'max_depth': True}),
                                ('get_active_document_info', {'include_layers': 'yes'})]:
            with self.assertRaises(ValueError):
                validate(operation, args)


if __name__ == '__main__':
    unittest.main()
