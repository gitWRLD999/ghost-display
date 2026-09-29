import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import shlex
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghost_bridge import CommandTransport, GhostError, GhostSession
from ghost_actuator import GhostActuator


def png(width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = (b'\0' + b'\xff\xff\xff' * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


class FakeTransport:
    def __init__(self):
        self.state = dict(ok=True, running=True, displayId=7, backendPid=123,
                          backendUid=2000, width=1200, height=1920, virtualDeviceId=4,
                          state='ON', captureHealth='ready', inputHealth='ok')
        self.calls = []
        self.bad_image = False
        self.fail_action = False
        self.recreate_during_capture = False

    async def run(self, *args):
        self.calls.append(args)
        if args[0] == 'status':
            return json.dumps(self.state).encode()
        if args[0] == 'screenshot':
            if self.recreate_during_capture:
                self.state['backendPid'] += 1
            return b'{"ok":false}' if self.bad_image else png(self.state['width'], self.state['height'])
        if self.fail_action:
            raise GhostError('outcome unknown')
        return b'{"ok":true}'

    @property
    def inputs(self):
        return [c for c in self.calls if c[0] not in {'status', 'screenshot'}]


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.session = GhostSession(self.transport, ['com.vertex.ghost'], max_actions=3)

    async def test_observe_then_normalized_edges(self):
        frame = await self.session.observe()
        self.assertEqual((frame.width, frame.height, frame.display_id), (1200, 1920, 7))
        await self.session.click(1000, 1000)
        self.assertEqual(self.transport.inputs, [('tap', '1199', '1919')])

    async def test_input_before_capture_is_rejected(self):
        with self.assertRaises(GhostError):
            await self.session.click(500, 500)
        self.assertEqual(self.transport.inputs, [])

    async def test_changed_identity_and_geometry_require_reobserve(self):
        for field in ('backendPid', 'displayId', 'width', 'height', 'virtualDeviceId'):
            await self.session.observe()
            self.transport.state[field] += 1
            with self.assertRaises(GhostError):
                await self.session.click(500, 500)
        self.assertEqual(self.transport.inputs, [])

    async def test_physical_display_never_accepted(self):
        self.transport.state['displayId'] = 0
        with self.assertRaises(GhostError):
            await self.session.observe()
        self.assertEqual(self.transport.calls, [('status', '--json')])

    async def test_backend_capture_and_power_guards(self):
        for field, value in [('backendUid', 1000), ('captureHealth', 'error'), ('inputHealth', 'error'),
                             ('running', False), ('state', 'OFF')]:
            original = self.transport.state[field]
            self.transport.state[field] = value
            with self.assertRaises(GhostError):
                await self.session.observe()
            self.transport.state[field] = original
        self.assertEqual(self.transport.inputs, [])

    async def test_failed_capture_and_recreation_do_not_fabricate_frame(self):
        self.transport.bad_image = True
        with self.assertRaises(GhostError):
            await self.session.observe()
        self.transport.bad_image = False
        self.transport.recreate_during_capture = True
        with self.assertRaises(GhostError):
            await self.session.observe()
        self.assertIsNone(self.session.observed)

    async def test_invalid_coordinates_and_duration(self):
        await self.session.observe()
        for x in (-1, 1001, 0.5, True, '500'):
            with self.assertRaises(GhostError):
                await self.session.click(x, 500)
        with self.assertRaises(GhostError):
            await self.session.swipe((0, 0), (1000, 1000), 0)
        self.assertEqual(self.transport.inputs, [])

    async def test_keys_forbid_power_and_use_ghost_home(self):
        await self.session.observe()
        for key in ('power', 'KEYCODE_VOLUME_UP', '26', 'app_switch'):
            with self.assertRaises(GhostError):
                await self.session.key(key)
        await self.session.key('home')
        await self.session.observe()
        await self.session.key('KEYCODE_DEL')
        self.assertEqual(self.transport.inputs, [('home',), ('key', 'DEL')])

    async def test_budget_and_unknown_outcome_no_retry(self):
        await self.session.observe()
        self.transport.fail_action = True
        with self.assertRaises(GhostError):
            await self.session.click(500, 500)
        self.assertEqual(len(self.transport.inputs), 1)
        self.assertIsNone(self.session.observed)
        self.transport.fail_action = False
        await self.session.observe()
        await self.session.click(500, 500)
        await self.session.observe()
        await self.session.click(500, 500)
        await self.session.observe()
        with self.assertRaises(GhostError):
            await self.session.click(500, 500)
        self.assertEqual(len(self.transport.inputs), 3)

    async def test_fixture_launch_and_unapproved_app(self):
        await self.session.observe()
        with self.assertRaises(GhostError):
            await self.session.launch('com.android.chrome')
        await self.session.launch('com.vertex.ghost')
        self.assertEqual(self.transport.inputs, [('open-component', 'com.vertex.ghost/.GhostTestActivity')])

    async def test_successful_action_requires_new_observation(self):
        await self.session.observe()
        await self.session.click(500, 500)
        with self.assertRaises(GhostError):
            await self.session.click(500, 500)
        self.assertEqual(len(self.transport.inputs), 1)

    async def test_focus_and_insert_is_bounded_and_invalidates_observation(self):
        await self.session.observe()
        await self.session.text('neutral test', target=(500, 500))
        self.assertEqual(self.transport.inputs, [('tap', '600', '960'), ('text', 'neutral test')])
        self.assertIsNone(self.session.observed)

    async def test_sequence_budget_rejected_before_first_action(self):
        await self.session.observe()
        with self.assertRaises(GhostError):
            await self.session.click_sequence([(500, 500)] * 4, delay_ms=0)
        self.assertEqual(self.transport.inputs, [])

    def test_explicit_endpoint_and_android_argument_quoting(self):
        with self.assertRaises(ValueError):
            CommandTransport.adb('adb', '')
        with self.assertRaises(ValueError):
            CommandTransport.ssh('ssh', '-evil')
        value = "quotes' ; $(id) `id` new\nline"
        self.assertEqual(shlex.split('text ' + shlex.quote(value)), ['text', value])
        self.assertIn('StrictHostKeyChecking=yes', CommandTransport.ssh('ssh', 'phone').prefix)

    async def test_real_local_process_receives_one_quoted_remote_command(self):
        transport = CommandTransport(
            [sys.executable, '-c', 'import json,sys; print(json.dumps(sys.argv[1:]))', '-s', 'serial', 'exec-out'],
            'sh /data/local/tmp/ghostctl')
        text = "quotes' ; $(id) `id` new\nline"
        argv = json.loads(await transport.run('text', text))
        self.assertEqual(argv[:-1], ['-s', 'serial', 'exec-out'])
        self.assertEqual(shlex.split(argv[-1]), ['sh', '/data/local/tmp/ghostctl', 'text', text])


def load_source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ArtemisContractTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[4] / 'artemis-upstream'
        if not root.exists():
            raise unittest.SkipTest('Pinned upstream checkout absent; set up the sibling artemis-upstream checkout')
        # Load the actual manifest/models independently of expensive package initialization.
        cls.manifest = load_source_module('ghost_test_artemis_manifest', root / 'artemis/mcp/action_manifest.py')
        cls.types = load_source_module('ghost_test_artemis_types', root / 'artemis/mcp/action_types.py')

    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.session = GhostSession(self.transport, ['com.vertex.ghost'])
        self.actuator = GhostActuator(self.session, result_type=self.types.ActionResult)

    def test_actual_upstream_manifest(self):
        self.manifest.validate_actuator(self.actuator)
        self.assertNotIn('focus_and_clear_text', self.actuator.capabilities())
        self.assertNotIn('wait_for_text', self.actuator.capabilities())

    async def test_observation_schema_and_actual_result_model(self):
        data = await self.actuator.get_screen_data()
        self.assertFalse(data.hierarchy_available)
        with self.assertRaises(GhostError):
            _ = data.elements
        self.assertEqual((data.width, data.height), (1200, 1920))
        self.assertEqual(base64.b64decode(data.base64)[:3], b'\xff\xd8\xff')
        result = await self.actuator.click(500, 500)
        self.assertTrue(result.ok)
        self.assertIsInstance(result, self.types.ActionResult)

    async def test_unsupported_clear_and_stop_are_errors(self):
        await self.actuator.get_screen_data()
        self.assertFalse((await self.actuator.input_text('hello')).ok)
        self.assertFalse((await self.actuator.manage_app('stop', 'com.vertex.ghost')).ok)
        self.assertEqual(self.transport.inputs, [])

    async def test_invalid_sequence_is_rejected_before_first_tap(self):
        await self.actuator.get_screen_data()
        result = await self.actuator.click_sequence([(500, 500), (1001, 500)])
        self.assertFalse(result.ok)
        self.assertEqual(self.transport.inputs, [])

    async def test_sequence_text_and_long_press_contract(self):
        await self.actuator.get_screen_data()
        self.assertTrue((await self.actuator.click_sequence([(250, 500), (750, 500)], delay_ms=0)).ok)
        await self.actuator.get_screen_data()
        self.assertTrue((await self.actuator.input_text('neutral test', clear_exist=False)).ok)
        await self.actuator.get_screen_data()
        self.assertTrue((await self.actuator.long_press(500, 500, 750)).ok)
        self.assertEqual(self.transport.inputs[-1], ('long-press', '600', '960', '750'))


if __name__ == '__main__':
    unittest.main()
