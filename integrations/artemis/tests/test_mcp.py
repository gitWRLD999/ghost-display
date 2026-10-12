"""Real MCP 1.29 memory-transport tests; no device, LLM, or full Artemis runtime.

Only unrelated Artemis controller/config/OCR/LangChain imports are stubbed. The
pinned action server, session, observation, manifest, bindings, result models,
FastMCP registration, ClientSession, schemas and memory streams execute unchanged.
Install requirements-test.txt and provide the audited sibling artemis-upstream.
"""
import asyncio
import base64
import importlib.metadata
import importlib.util
from io import BytesIO
import logging
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghost_actuator import GhostActuator
from ghost_bridge import GhostSession
from test_bridge import ScriptedTransport, load_source_module


PINNED_ARTEMIS = '351ca8422f7b5b54e80a9c1ce03a222e02415b6b'


def load_action_runtime(root):
    """Load actual source against the real MCP SDK, bypassing Artemis __init__."""
    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        return module

    def unexpected(*args, **kwargs):
        raise AssertionError('Ghost must not reach OCR, raw controllers, or fallback disk storage')

    stubs = {
        'artemis': stub('artemis', __path__=[]),
        'artemis.mcp': stub('artemis.mcp', __path__=[]),
        'artemis.mcp.actuators': stub('artemis.mcp.actuators', __path__=[]),
        'artemis.config': stub('artemis.config', get_temp_dir=unexpected),
        'artemis.context': stub('artemis.context', ArtemisContext=object),
        'artemis.controllers.unified_controller': stub(
            'artemis.controllers.unified_controller', UnifiedMobileController=object),
        'artemis.utils.ocr_xml_fusion': stub('artemis.utils.ocr_xml_fusion', fuse_ocr_with_xml=unexpected),
        'artemis.utils.visualization': stub(
            'artemis.utils.visualization', format_minimal_list_with_elements=unexpected),
        'third_party.mobile_use.utils.logger': stub(
            'third_party.mobile_use.utils.logger', get_logger=lambda name: logging.getLogger(name)),
        'langchain_core.tools': stub('langchain_core.tools', StructuredTool=object),
        'artemis.core.tool_declaration': stub('artemis.core.tool_declaration', ToolDeclaration=object),
    }
    # Do not stub any mcp or anyio module. Fresh bindings must retain the real
    # Annotated[CallToolResult, ActionResult] return type for FastMCP schemas.
    with patch.dict(sys.modules, stubs):
        modules = {}
        for name, relative in (
            ('types', 'action_types.py'), ('manifest', 'action_manifest.py'),
            ('specs', 'action_specs.py'), ('base', 'actuators/base.py'),
            ('observation', 'observation.py'), ('server', 'action_server.py'),
            ('session', 'action_session.py'),
        ):
            qualified = 'artemis.mcp.' + (relative[:-3].replace('/', '.'))
            modules[name] = load_source_module(qualified, root / 'artemis/mcp' / relative)
    return SimpleNamespace(**modules)


class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('mcp') is None:
            raise unittest.SkipTest('MCP SDK absent; install integrations/artemis/requirements-test.txt')
        if importlib.metadata.version('mcp') != '1.29.0':
            raise RuntimeError('MCP tests require SDK 1.29.0, matching the audited Artemis lockfile')
        root = Path(__file__).resolve().parents[4] / 'artemis-upstream'
        if not root.exists():
            raise unittest.SkipTest('Audited sibling artemis-upstream checkout absent')
        revision = subprocess.run(
            ['git', '-c', 'safe.directory=' + root.as_posix(), '-C', str(root), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
        if revision != PINNED_ARTEMIS:
            raise RuntimeError('Artemis checkout is not the audited revision: ' + revision)
        from mcp.shared.memory import create_connected_server_and_client_session
        cls.connect = staticmethod(create_connected_server_and_client_session)
        cls.runtime = load_action_runtime(root)

    async def asyncSetUp(self):
        self.transport = ScriptedTransport()
        self.ghost = GhostSession(self.transport, ['com.vertex.ghost'], max_actions=20)
        self.persisted = []

        def persist(image, **attributes):
            self.persisted.append((image, attributes))
            return 'neutral-frame'

        storage = SimpleNamespace(get_or_create_image=persist,
                                  get_image_path=lambda name: Path('private') / (name + '.jpg'))
        self.ctx = SimpleNamespace(device=SimpleNamespace(device_width=1, device_height=1), data_engine=storage)
        self.actuator = GhostActuator(self.ghost, ctx=self.ctx, result_type=self.runtime.types.ActionResult)
        self.server = self.runtime.server.build_action_server(self.actuator, name='ghost_mcp_test')

    def assert_jpeg(self, encoded):
        from PIL import Image
        image_bytes = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (1200, 1920))
            image.load()
        return image_bytes

    def assert_device_result(self, result, action, ok):
        self.assertFalse(result.isError)
        decoded = self.runtime.types.ActionResult.model_validate(result.structuredContent)
        self.assertEqual(decoded.action, action)
        self.assertEqual(decoded.ok, ok)
        self.assertEqual(result.content[0].type, 'text')
        self.assertEqual(result.content[0].text, decoded.message)
        return decoded

    async def test_real_registration_and_input_output_schemas(self):
        async with self.connect(self.server) as client:
            listed = await client.list_tools()
        tools = {tool.name: tool for tool in listed.tools}
        self.assertEqual(set(tools), set(self.actuator.capabilities()))
        for name in ('focus_and_clear_text', 'wait_for_text', 'open_link', 'run_adb_command'):
            self.assertNotIn(name, tools)
        click = tools['click'].inputSchema
        self.assertEqual(click['required'], ['target'])
        self.assertEqual(click['properties']['target']['items']['type'], 'integer')
        self.assertEqual(click['properties']['times']['default'], 1)
        self.assertEqual(click['properties']['delay_ms']['default'], 100)
        text = tools['input_text'].inputSchema
        self.assertEqual(text['required'], ['text'])
        self.assertTrue(text['properties']['clear_exist']['default'])
        self.assertIsNone(text['properties']['target']['default'])
        for name, model in (('click', self.runtime.types.ActionResult),
                            ('observe_screen', self.runtime.types.ObserveResult)):
            self.assertEqual(tools[name].outputSchema, model.model_json_schema())
        self.assertEqual(self.transport.calls, [])

    async def test_screenshot_then_default_click_and_stale_refusal(self):
        async with self.connect(self.server) as client:
            screenshot = await client.call_tool('take_screenshot', {})
            self.assertFalse(screenshot.isError)
            self.assertTrue(screenshot.structuredContent['ok'])
            self.assert_jpeg(screenshot.structuredContent['image_b64'])
            result = await client.call_tool('click', {'target': [1000, 1000]})
            self.assert_device_result(result, 'click', True)
            stale = await client.call_tool('click', {'target': [500, 500]})
            self.assert_device_result(stale, 'click', False)
        self.assertEqual(self.transport.inputs, [('tap', '1199', '1919')])
        self.assertEqual(self.ghost.actions, 1)

    async def test_wire_sequence_focus_insert_and_swipe(self):
        cases = [
            ('click_sequence', {'sequence': [[250, 500], [750, 500]], 'delay_ms': 0},
             [('tap', '300', '960'), ('tap', '900', '960')]),
            ('input_text', {'text': 'neutral', 'target': [500, 500], 'clear_exist': False},
             [('tap', '600', '960'), ('text', 'neutral')]),
            ('swipe', {'start': [0, 1000], 'end': [1000, 0], 'duration_ms': 5000},
             [('swipe', '0', '1919', '1199', '0', '5000')]),
        ]
        async with self.connect(self.server) as client:
            for name, arguments, expected in cases:
                with self.subTest(action=name):
                    await client.call_tool('take_screenshot', {})
                    count = len(self.transport.inputs)
                    result = await client.call_tool(name, arguments)
                    self.assert_device_result(result, name, True)
                    self.assertEqual(self.transport.inputs[count:], expected)

    async def test_device_refusals_are_structured_without_protocol_errors(self):
        async with self.connect(self.server) as client:
            await client.call_tool('take_screenshot', {})
            for name, arguments in (
                ('input_text', {'text': 'neutral'}),  # Default clear_exist=True is excluded.
                ('press_key', {'key': 'POWER'}),
                ('manage_app', {'action': 'stop', 'app_name': 'com.vertex.ghost'}),
                ('manage_app', {'action': 'launch', 'app_name': 'example.denied'}),
                ('click', {'target': [1001, 500]}),
            ):
                with self.subTest(action=name, arguments=arguments):
                    result = await client.call_tool(name, arguments)
                    self.assert_device_result(result, name, False)
        self.assertEqual(self.transport.inputs, [])
        self.assertEqual(self.ghost.actions, 0)

    async def test_observation_image_and_missing_hierarchy_round_trip(self):
        async with self.connect(self.server) as client:
            with self.assertLogs('artemis.mcp.observation', level='ERROR'):
                result = await client.call_tool('observe_screen', {'settle_ms': 0, 'include_image': True})
        self.assertFalse(result.isError)
        observed = self.runtime.types.ObserveResult.model_validate(result.structuredContent)
        self.assertTrue(observed.ok)
        self.assertFalse(observed.hierarchy_ok)
        self.assertEqual(observed.elements, [])
        self.assertEqual((self.ctx.device.device_width, self.ctx.device.device_height), (1200, 1920))
        images = [content for content in result.content if content.type == 'image']
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].mimeType, 'image/jpeg')
        image_bytes = self.assert_jpeg(images[0].data)
        self.assertEqual(self.persisted, [(image_bytes, {'ui_tree': None, 'ocr_result': []})])
        self.assertEqual(Path(observed.screenshot_path), Path('private/neutral-frame.jpg'))
        self.assertEqual(self.transport.inputs, [])

    async def test_unavailable_hierarchy_does_not_break_the_session(self):
        async with self.connect(self.server) as client:
            hierarchy = await client.call_tool('get_ui_hierarchy', {})
            self.assertFalse(hierarchy.isError)
            self.assertFalse(hierarchy.structuredContent['ok'])
            self.assertIn('hierarchy is unavailable', hierarchy.structuredContent['error'])
            self.assertEqual(self.transport.calls, [])
            screenshot = await client.call_tool('take_screenshot', {})
            self.assertTrue(screenshot.structuredContent['ok'])
            self.assert_jpeg(screenshot.structuredContent['image_b64'])

    async def test_protocol_errors_leave_later_requests_usable(self):
        async with self.connect(self.server) as client:
            for name, arguments in (('click', {}), ('click', {'target': ['invalid', 500]}),
                                     ('open_link', {'url': 'https://example.invalid/'})):
                with self.subTest(name=name, arguments=arguments):
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.isError)
                    self.assertEqual(self.transport.calls, [])
            screenshot = await client.call_tool('take_screenshot', {})
            self.assertTrue(screenshot.structuredContent['ok'])
            result = await client.call_tool('click', {'target': [500, 500]})
            self.assert_device_result(result, 'click', True)
        self.assertEqual(self.transport.inputs, [('tap', '600', '960')])

    async def test_screenshot_timeout_invalidates_capture_and_session_recovers(self):
        started = asyncio.Event()

        async def blocked_capture(arguments):
            if arguments[0] == 'screenshot':
                started.set()
                await asyncio.Event().wait()

        async with self.connect(self.server) as client:
            self.transport.before_command = blocked_capture
            result = await client.call_tool('take_screenshot', {'timeout_ms': 50})
            self.assertTrue(started.is_set())
            self.assertFalse(result.isError)
            self.assertFalse(result.structuredContent['ok'])
            self.assertIn('timed out after 50ms', result.structuredContent['error'])
            self.assertIsNone(self.ghost.observed)
            self.assertEqual(self.ghost.actions, 0)
            self.transport.before_command = None
            listed = await client.list_tools()
            self.assertEqual(len(listed.tools), len(self.actuator.capabilities()))
            screenshot = await client.call_tool('take_screenshot', {})
            self.assert_jpeg(screenshot.structuredContent['image_b64'])
            result = await client.call_tool('click', {'target': [500, 500]})
            self.assert_device_result(result, 'click', True)
        self.assertEqual(self.transport.inputs, [('tap', '600', '960')])

    async def test_bad_capture_is_a_device_failure_with_no_image_or_input(self):
        self.transport.bad_image = True
        async with self.connect(self.server) as client:
            screenshot = await client.call_tool('take_screenshot', {})
            self.assertFalse(screenshot.isError)
            self.assertFalse(screenshot.structuredContent['ok'])
            self.assertNotIn('image_b64', screenshot.structuredContent)
            with self.assertLogs('artemis.mcp.observation', level='ERROR'):
                observed = await client.call_tool('observe_screen', {'settle_ms': 0, 'include_image': True})
            self.assertFalse(observed.isError)
            self.assertFalse(observed.structuredContent['ok'])
            self.assertFalse(any(content.type == 'image' for content in observed.content))
            click = await client.call_tool('click', {'target': [500, 500]})
            self.assert_device_result(click, 'click', False)
        self.assertEqual(self.transport.inputs, [])
        self.assertIsNone(self.ghost.observed)

    async def test_actual_action_session_uses_typed_mcp_results_and_closes(self):
        session = await self.runtime.session.ActionSession(self.server).start()
        try:
            self.assertTrue(session.started)
            self.assert_jpeg(await session.screenshot_b64())
            result = await session.call('click', {'target': [500, 500]})
            self.assertIsInstance(result, self.runtime.types.ActionResult)
            self.assertTrue(result.ok)
            with self.assertRaisesRegex(RuntimeError, 'not_a_tool'):
                await session.call_raw('not_a_tool', {})
            # Continue through the owner-task transport after the protocol failure.
            with self.assertLogs('artemis.mcp.observation', level='ERROR'):
                observed = await session.observe(settle_ms=0, include_image=True)
            self.assertTrue(observed.ok)
            self.assertFalse(observed.hierarchy_ok)
        finally:
            await session.aclose()
        self.assertFalse(session.started)


if __name__ == '__main__':
    unittest.main()
