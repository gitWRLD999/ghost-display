import asyncio
import base64
import importlib.util
from functools import lru_cache
import json
import logging
from io import BytesIO
from pathlib import Path
import shlex
import struct
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghost_bridge import CommandTransport, GhostError, GhostSession
from ghost_actuator import GhostActuator


@lru_cache(maxsize=8)
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


class ScriptedTransport(FakeTransport):
    """Inject a failure or state transition at a specific command boundary."""

    def __init__(self):
        super().__init__()
        self.responses = {}
        self.before_command = None

    async def run(self, *args):
        if self.before_command is not None:
            await self.before_command(args)
        responses = self.responses.get(args[0], [])
        if responses:
            self.calls.append(args)
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        return await super().run(*args)


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


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def test_endpoint_selection_is_explicit(self):
        self.assertEqual(CommandTransport.adb('adb.exe', 'phone-123').prefix,
                         ['adb.exe', '-s', 'phone-123', 'exec-out'])
        ssh = CommandTransport.ssh('ssh.exe', 'user@phone', port=2222)
        self.assertEqual(ssh.prefix[-3:], ['-p', '2222', 'user@phone'])
        for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'ConnectTimeout=5'):
            self.assertIn(option, ssh.prefix)

    def test_ssh_port_must_be_an_integer_in_range(self):
        for port in (0, 65536, -1, True, 8022.5, '8022', None):
            with self.subTest(port=port), self.assertRaises(ValueError):
                CommandTransport.ssh('ssh', 'phone', port)

    async def test_nonzero_process_exit_is_bounded_and_not_retried(self):
        transport = CommandTransport(
            [sys.executable, '-c', "import sys; sys.stderr.buffer.write(b'bad\\xff' + b'x' * 1500); sys.exit(3)"],
            'ghostctl')
        with self.assertRaises(GhostError) as error:
            await transport.run('tap', '1', '2')
        self.assertEqual(len(str(error.exception)), 1000)
        self.assertTrue(str(error.exception).startswith('bad\ufffd'))

    async def test_nonzero_exit_without_stderr_has_an_error(self):
        transport = CommandTransport([sys.executable, '-c', 'raise SystemExit(2)'], 'ghostctl')
        with self.assertRaisesRegex(GhostError, 'ghostctl failed'):
            await transport.run('status', '--json')

    async def test_process_creation_failure_is_a_ghost_error(self):
        transport = CommandTransport.adb('missing-adb.exe', 'phone')
        with patch('ghost_bridge.asyncio.create_subprocess_exec',
                   new=AsyncMock(side_effect=FileNotFoundError('missing executable'))) as spawn:
            with self.assertRaisesRegex(GhostError, 'Transport could not start'):
                await transport.run('tap', '1', '2')
        self.assertEqual(spawn.await_count, 1)

    async def test_pipe_failure_kills_and_reaps_child_without_replay(self):
        process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=OSError('pipe closed')),
                                  kill=Mock(), wait=AsyncMock(return_value=1))
        transport = CommandTransport.adb('adb', 'phone')
        with patch('ghost_bridge.asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)) as spawn:
            with self.assertRaisesRegex(GhostError, 'outcome unknown'):
                await transport.run('tap', '1', '2')
        process.kill.assert_called_once_with()
        process.wait.assert_awaited_once_with()
        self.assertEqual(spawn.await_count, 1)

    async def test_timeout_kills_and_reaps_child_without_replay(self):
        process = None
        create = asyncio.create_subprocess_exec
        wait_for = asyncio.wait_for

        async def spawn(*args, **kwargs):
            nonlocal process
            process = await create(*args, **kwargs)
            return process

        async def short_timeout(awaitable, timeout):
            return await wait_for(awaitable, .02)

        transport = CommandTransport([sys.executable, '-c', 'import time; time.sleep(30)'], 'ghostctl')
        with patch('ghost_bridge.asyncio.create_subprocess_exec', side_effect=spawn) as mocked_spawn, \
                patch('ghost_bridge.asyncio.wait_for', side_effect=short_timeout):
            with self.assertRaisesRegex(GhostError, 'outcome unknown'):
                await transport.run('tap', '1', '2')
        self.assertIsNotNone(process.returncode)
        self.assertEqual(mocked_spawn.call_count, 1)

    async def test_cancellation_kills_and_reaps_child_and_propagates(self):
        process = None
        started = asyncio.Event()
        create = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            nonlocal process
            process = await create(*args, **kwargs)
            started.set()
            return process

        transport = CommandTransport([sys.executable, '-c', 'import time; time.sleep(30)'], 'ghostctl')
        with patch('ghost_bridge.asyncio.create_subprocess_exec', side_effect=spawn) as mocked_spawn:
            task = asyncio.create_task(transport.run('tap', '1', '2'))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(process.returncode)
        self.assertEqual(mocked_spawn.call_count, 1)
        self.assertTrue(task.cancelled())


class BridgeSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = ScriptedTransport()
        self.session = GhostSession(self.transport, ['com.vertex.ghost', 'example.approved'], max_actions=40)

    def test_action_budget_requires_a_positive_integer(self):
        for budget in (0, -1, True, False, 1.5, float('inf'), float('nan'), '40', None):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                GhostSession(self.transport, max_actions=budget)

    async def test_status_failure_discards_coordinates_without_spending_an_action(self):
        failures = [GhostError('transport lost'), OSError('pipe lost'), b'not json', b'{"ok":false}',
                    json.dumps(dict(self.transport.state, inputHealth='error')).encode(),
                    json.dumps(dict(self.transport.state, inputHealth=[])).encode(),
                    json.dumps(dict(self.transport.state, inputHealth={'ok': True})).encode()]
        for failure in failures:
            with self.subTest(failure=failure):
                await self.session.observe()
                self.transport.responses['status'] = [failure]
                with self.assertRaises(GhostError):
                    await self.session.click(500, 500)
                self.assertIsNone(self.session.observed)
                with self.assertRaisesRegex(GhostError, 'Observe Ghost first'):
                    await self.session.click(500, 500)
                self.assertEqual(self.session.actions, 0)
        self.assertEqual(self.transport.inputs, [])

    async def test_cancelled_readiness_check_requires_new_capture(self):
        await self.session.observe()
        self.transport.responses['status'] = [asyncio.CancelledError()]
        with self.assertRaises(asyncio.CancelledError):
            await self.session.click(500, 500)
        self.assertIsNone(self.session.observed)
        with self.assertRaises(GhostError):
            await self.session.click(500, 500)
        self.assertEqual(self.transport.inputs, [])

    async def test_malformed_action_responses_consume_budget_and_block_replay(self):
        for response in (b'garbage', b'[]', b'{"ok":1}', b'{"ok":false,"error":"denied"}'):
            with self.subTest(response=response):
                await self.session.observe()
                count = self.session.actions
                self.transport.responses['tap'] = [response]
                with self.assertRaises(GhostError):
                    await self.session.click(500, 500)
                self.assertEqual(self.session.actions, count + 1)
                self.assertIsNone(self.session.observed)
                with self.assertRaises(GhostError):
                    await self.session.click(500, 500)
        self.assertEqual(len(self.transport.inputs), 4)

    async def test_failed_recapture_invalidates_previous_observation(self):
        for command in ('status', 'screenshot'):
            with self.subTest(command=command):
                await self.session.observe()
                self.transport.responses[command] = [GhostError('connection lost')]
                with self.assertRaises(GhostError):
                    await self.session.observe()
                self.assertIsNone(self.session.observed)
                with self.assertRaises(GhostError):
                    await self.session.key('ENTER')
        self.assertEqual(self.transport.inputs, [])

    async def test_failed_post_capture_status_does_not_authorize_input(self):
        self.transport.responses['status'] = [json.dumps(self.transport.state).encode(), b'not json']
        with self.assertRaises(GhostError):
            await self.session.observe()
        self.assertIsNone(self.session.observed)
        self.assertEqual(self.transport.calls, [('status', '--json'), ('screenshot', '--format', 'png'),
                                                ('status', '--json')])

    async def test_screenshot_header_and_geometry_are_required(self):
        for image in (b'', b'\x89PNG\r\n\x1a\n', png(1200, 1919), png(1199, 1920)):
            with self.subTest(size=len(image)):
                self.transport.responses['screenshot'] = [image]
                with self.assertRaises(GhostError):
                    await self.session.observe()
                self.assertIsNone(self.session.observed)

    async def test_truncated_or_corrupt_matching_png_cannot_authorize_input(self):
        valid = png(1200, 1920)
        corrupted = bytearray(valid)
        corrupted[41] ^= 1  # Damage IDAT data while preserving its dimensions.
        for image in (valid[:24], valid[:-12], bytes(corrupted)):
            with self.subTest(size=len(image)):
                self.transport.responses['screenshot'] = [image]
                with self.assertRaisesRegex(GhostError, 'could not be decoded'):
                    await self.session.observe()
                self.assertIsNone(self.session.observed)
                with self.assertRaises(GhostError):
                    await self.session.click(500, 500)
        self.assertEqual(self.transport.inputs, [])

    async def test_device_transport_oserror_is_reported_as_a_failed_action(self):
        await self.session.observe()
        self.transport.responses['tap'] = [OSError('pipe disconnected')]
        with self.assertRaises(GhostError):
            await self.session.click(500, 500)
        self.assertEqual(self.session.actions, 1)
        self.assertIsNone(self.session.observed)
        self.assertEqual(self.transport.inputs, [('tap', '600', '960')])

    async def test_invalid_identity_numbers_do_not_authorize_capture(self):
        for field in ('displayId', 'backendPid', 'width', 'height'):
            for value in (None, 0, -1, True, 1.5, '7'):
                with self.subTest(field=field, value=value):
                    state = dict(self.transport.state, **{field: value})
                    self.transport.responses['status'] = [json.dumps(state).encode()]
                    with self.assertRaises(GhostError):
                        await self.session.observe()
        self.assertFalse(any(c[0] == 'screenshot' for c in self.transport.calls))

    async def test_fresh_untested_input_can_bootstrap_only_from_a_real_frame(self):
        self.transport.state['inputHealth'] = 'untested'
        await self.session.observe()
        await self.session.click(500, 500)
        self.assertEqual(self.transport.inputs, [('tap', '600', '960')])
        for health in ('error', 'denied', 'unavailable', '', None):
            with self.subTest(input_health=health):
                self.transport.state['inputHealth'] = health
                with self.assertRaises(GhostError):
                    await self.session.observe()
        self.transport.state['inputHealth'] = 'untested'
        self.transport.state['captureHealth'] = 'no_frame'
        count = len(self.transport.calls)
        with self.assertRaises(GhostError):
            await self.session.observe()
        self.assertEqual(self.transport.calls[count:], [('status', '--json')])
        self.assertEqual(self.transport.inputs, [('tap', '600', '960')])
        self.assertIsNone(self.session.observed)

    async def test_sequence_stops_at_recovery_and_never_retries_the_first_tap(self):
        await self.session.observe()

        async def recreate(args):
            if args[0] == 'status' and self.transport.inputs:
                self.transport.state['backendPid'] += 1

        self.transport.before_command = recreate
        with self.assertRaises(GhostError):
            await self.session.click_sequence([(250, 500), (750, 500)], delay_ms=0)
        self.assertEqual(self.transport.inputs, [('tap', '300', '960')])
        self.assertEqual(self.session.actions, 1)
        self.assertIsNone(self.session.observed)

    async def test_focus_insert_stops_when_display_changes_after_focus(self):
        await self.session.observe()

        async def resize(args):
            if args[0] == 'status' and self.transport.inputs:
                self.transport.state['width'] += 1

        self.transport.before_command = resize
        with self.assertRaises(GhostError):
            await self.session.text('neutral', target=(500, 500))
        self.assertEqual(self.transport.inputs, [('tap', '600', '960')])
        self.assertEqual(self.session.actions, 1)

    async def test_sequence_uses_a_snapshot_of_validated_points(self):
        await self.session.observe()
        points = [[250, 500], [750, 500]]

        async def mutate_after_validation(args):
            if args[0] == 'status':
                points[0][0] = 1000
                points.append([500, 500])
                self.transport.before_command = None

        self.transport.before_command = mutate_after_validation
        await self.session.click_sequence(points, delay_ms=0)
        self.assertEqual(self.transport.inputs, [('tap', '300', '960'), ('tap', '900', '960')])
        self.assertEqual(self.session.actions, 2)

    async def test_sequence_rejects_invalid_sizes_delay_and_shapes_before_input(self):
        await self.session.observe()
        cases = [([], 0), ([(0, 0)] * 21, 0), ([(0, 0)], -1), ([(0, 0)], 2001),
                 ([(0, 0)], True), ([(0, 0)], 1.5), ([(0, 0), (0,)], 0),
                 ([(0, 0), (0, 0, 0)], 0), ([(0, 0), (0, True)], 0)]
        for points, delay in cases:
            with self.subTest(points=points, delay=delay), self.assertRaises((GhostError, ValueError)):
                await self.session.click_sequence(points, delay)
        self.assertEqual(self.transport.inputs, [])
        self.assertEqual(self.session.actions, 0)

    async def test_sequence_accepts_twenty_points_at_exact_budget(self):
        self.session.max_actions = 20
        await self.session.observe()
        await self.session.click_sequence([(0, 0)] * 20, delay_ms=0)
        self.assertEqual(len(self.transport.inputs), 20)
        await self.session.observe()
        with self.assertRaisesRegex(GhostError, 'Action budget reached'):
            await self.session.key('ENTER')

    async def test_focus_insert_reserves_both_actions_before_tapping(self):
        self.session.max_actions = 1
        await self.session.observe()
        with self.assertRaisesRegex(GhostError, 'remaining action budget'):
            await self.session.text('neutral', target=(500, 500))
        self.assertEqual(self.transport.inputs, [])
        self.assertEqual(self.session.actions, 0)
        await self.session.text('neutral')
        self.assertEqual(self.session.actions, 1)

    async def test_swipe_edges_and_duration_bounds(self):
        for duration in (1, 5000):
            await self.session.observe()
            await self.session.swipe((0, 1000), (1000, 0), duration)
            self.assertEqual(self.transport.inputs[-1], ('swipe', '0', '1919', '1199', '0', str(duration)))
        await self.session.observe()
        count = self.session.actions
        for duration in (0, 5001, True, 1.5, '800'):
            with self.subTest(duration=duration), self.assertRaises(GhostError):
                await self.session.swipe((0, 0), (1000, 1000), duration)
        self.assertEqual(self.session.actions, count)

    async def test_text_budget_counts_utf8_bytes_and_rejects_invalid_payloads(self):
        await self.session.observe()
        for value in (None, 42, b'text', 'a' * 32001, '\u00e9' * 16001):
            with self.subTest(value_type=type(value)), self.assertRaises(GhostError):
                await self.session.text(value)
        self.assertEqual(self.transport.inputs, [])
        await self.session.text('\u00e9' * 16000)
        self.assertEqual(len(self.transport.inputs[-1][1].encode('utf-8')), 32000)

    async def test_all_safe_keys_and_aliases_stay_on_ghost(self):
        for key in sorted(GhostSession.SAFE_KEYS) + ['KEYCODE_DELETE', 'BACK', 'HOME']:
            await self.session.observe()
            await self.session.key(key)
        self.assertEqual(self.transport.inputs[-3:], [('key', 'DEL'), ('back',), ('home',)])
        self.assertTrue(all(c[0] in {'key', 'back', 'home'} for c in self.transport.inputs))

    async def test_package_allowlist_is_exact_and_default_denies_launch(self):
        await self.session.observe()
        for package in ('Approved App', 'example.approved/.Activity', 'example.approved; echo bad', 'example.approved '):
            with self.subTest(package=package), self.assertRaises(GhostError):
                await self.session.launch(package)
        await self.session.launch('example.approved')
        self.assertEqual(self.transport.inputs, [('open-app', 'example.approved')])
        other = GhostSession(self.transport)
        await other.observe()
        with self.assertRaises(GhostError):
            await other.launch('com.vertex.ghost')

    async def test_concurrent_single_actions_share_only_one_observation(self):
        await self.session.observe()
        results = await asyncio.gather(self.session.click(250, 500), self.session.click(750, 500),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(result, GhostError) for result in results), 1)
        self.assertEqual(self.transport.inputs, [('tap', '300', '960')])
        self.assertEqual(self.session.actions, 1)

    async def test_capture_waits_until_a_sequence_finishes(self):
        await self.session.observe()
        first_tap = asyncio.Event()
        release = asyncio.Event()

        async def hold_first_tap(args):
            if args[0] == 'tap' and not first_tap.is_set():
                first_tap.set()
                await release.wait()

        self.transport.before_command = hold_first_tap
        sequence = asyncio.create_task(self.session.click_sequence([(250, 500), (750, 500)], 0))
        await asyncio.wait_for(first_tap.wait(), 2)
        capture = asyncio.create_task(self.session.observe())
        await asyncio.sleep(0)
        self.assertFalse(capture.done())
        release.set()
        await asyncio.gather(sequence, capture)
        commands = [c[0] for c in self.transport.calls]
        self.assertEqual(commands[3:], ['status', 'status', 'tap', 'status', 'tap',
                                        'status', 'screenshot', 'status'])
        self.assertIsNotNone(self.session.observed)


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
        revision = subprocess.run(
            ['git', '-c', 'safe.directory=' + root.as_posix(), '-C', str(root), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
        if revision != '351ca8422f7b5b54e80a9c1ce03a222e02415b6b':
            raise RuntimeError('Artemis contract checkout is not the audited pinned revision: ' + revision)
        # Load the actual manifest/models independently of expensive package initialization.
        cls.manifest = load_source_module('ghost_test_artemis_manifest', root / 'artemis/mcp/action_manifest.py')
        cls.types = load_source_module('ghost_test_artemis_types', root / 'artemis/mcp/action_types.py')
        # Only imported runtime dependencies are stubbed. The upstream observation
        # and wire-handler implementations execute unchanged, without starting
        # Artemis, MCP, a controller, OCR, or its expensive package initialization.
        def stub(name, **attributes):
            module = ModuleType(name)
            module.__dict__.update(attributes)
            return module

        def unexpected(*args, **kwargs):
            raise AssertionError('Unavailable Ghost hierarchy must not reach OCR or temp storage')

        stubs = {
            'artemis.config': stub('artemis.config', get_temp_dir=unexpected),
            'artemis.context': stub('artemis.context', ArtemisContext=object),
            'artemis.controllers.unified_controller': stub(
                'artemis.controllers.unified_controller', UnifiedMobileController=object),
            'artemis.mcp.action_types': cls.types,
            'artemis.utils.ocr_xml_fusion': stub('artemis.utils.ocr_xml_fusion', fuse_ocr_with_xml=unexpected),
            'artemis.utils.visualization': stub(
                'artemis.utils.visualization', format_minimal_list_with_elements=unexpected),
            'third_party.mobile_use.utils.logger': stub(
                'third_party.mobile_use.utils.logger', get_logger=lambda name: logging.getLogger(name)),
            'langchain_core.tools': stub('langchain_core.tools', StructuredTool=object),
            'mcp.types': stub('mcp.types', CallToolResult=object),
            'artemis.core.tool_declaration': stub('artemis.core.tool_declaration', ToolDeclaration=object),
        }
        with patch.dict(sys.modules, stubs):
            cls.observation = load_source_module('ghost_test_artemis_observation', root / 'artemis/mcp/observation.py')
            cls.specs = load_source_module('ghost_test_artemis_specs', root / 'artemis/mcp/action_specs.py')

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

    async def test_decoded_jpeg_and_context_dimensions_match_real_capture(self):
        from PIL import Image
        self.actuator.ctx = SimpleNamespace(device=SimpleNamespace(device_width=1, device_height=1))
        data = await self.actuator.get_screen_data()
        with Image.open(BytesIO(base64.b64decode(data.base64, validate=True))) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (1200, 1920))
            self.assertEqual(image.convert('RGB').getpixel((600, 960)), (255, 255, 255))
        self.assertEqual((self.actuator.ctx.device.device_width, self.actuator.ctx.device.device_height),
                         (1200, 1920))

    async def test_corrupt_png_decode_discards_observation(self):
        self.transport = ScriptedTransport()
        self.actuator.session = GhostSession(self.transport)
        # Matching status dimensions alone do not make a decodable frame.
        self.transport.responses['screenshot'] = [png(1200, 1920)[:24]]
        with self.assertRaisesRegex(GhostError, 'could not be decoded'):
            await self.actuator.get_screen_data()
        self.assertIsNone(self.actuator.session.observed)
        self.assertFalse((await self.actuator.click(500, 500)).ok)
        self.assertEqual(self.transport.inputs, [])

    async def test_cancelled_jpeg_encoding_discards_unreturned_observation(self):
        started = asyncio.Event()
        to_thread = asyncio.to_thread

        async def interrupted_encoding(*args, **kwargs):
            if self.session.observed is None:
                return await to_thread(*args, **kwargs)
            started.set()
            await asyncio.Event().wait()

        with patch('ghost_actuator.asyncio.to_thread', side_effect=interrupted_encoding):
            capture = asyncio.create_task(self.actuator.take_screenshot())
            await asyncio.wait_for(started.wait(), 2)
            capture.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await capture
        self.assertIsNone(self.session.observed)
        self.assertFalse((await self.actuator.click(500, 500)).ok)
        self.assertEqual(self.transport.inputs, [])

    async def test_transport_creation_failure_returns_actual_failure_model(self):
        await self.actuator.get_screen_data()
        self.session.transport = CommandTransport.adb('missing-adb.exe', 'phone')
        # Keep the status available so this exercises input transport creation.
        original_status = self.session.status
        self.session.status = AsyncMock(return_value=dict(self.transport.state))
        try:
            with patch('ghost_bridge.asyncio.create_subprocess_exec',
                       new=AsyncMock(side_effect=FileNotFoundError('missing executable'))):
                result = await self.actuator.click(500, 500)
        finally:
            self.session.status = original_status
        self.assertIsInstance(result, self.types.ActionResult)
        self.assertFalse(result.ok)
        self.assertEqual(result.action, 'click')
        self.assertEqual(result.code, self.types.ActionCode.DEVICE_ERROR)
        self.assertEqual(self.session.actions, 1)
        self.assertIsNone(self.session.observed)

    async def test_action_cancellation_spends_budget_and_never_runs_sequence_tail(self):
        await self.actuator.get_screen_data()
        scripted = ScriptedTransport()
        scripted.responses['tap'] = [asyncio.CancelledError()]
        self.session.transport = scripted
        with self.assertRaises(asyncio.CancelledError):
            await self.actuator.click_sequence([(250, 500), (750, 500)], 0)
        self.assertEqual(scripted.inputs, [('tap', '300', '960')])
        self.assertEqual(self.session.actions, 1)
        self.assertIsNone(self.session.observed)

    async def test_cancelled_queued_action_closes_unstarted_coroutine(self):
        coroutine = self.session.key('DEL')
        await self.actuator.operation_lock.acquire()
        try:
            task = asyncio.create_task(self.actuator._action('erase_one_char', coroutine))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            self.actuator.operation_lock.release()
        self.assertIsNone(coroutine.cr_frame)
        self.assertEqual(self.transport.calls, [])

    async def test_invalid_action_arguments_have_failure_results_and_no_input(self):
        await self.actuator.get_screen_data()
        operations = [self.actuator.click(500, 500, times=True), self.actuator.click(500, 500, times=21),
                      self.actuator.long_press(500, 500, 5001), self.actuator.swipe((0,), (1000, 1000)),
                      self.actuator.input_text(b'bytes', clear_exist=False),
                      self.actuator.input_text('text', target=(500,), clear_exist=False),
                      self.actuator.press_key('KEYCODE_POWER')]
        for operation in operations:
            result = await operation
            self.assertIsInstance(result, self.types.ActionResult)
            self.assertFalse(result.ok)
        self.assertEqual(self.transport.inputs, [])
        self.assertEqual(self.session.actions, 0)

    async def test_delay_bounds_do_not_touch_the_device(self):
        with patch('ghost_actuator.asyncio.sleep', new=AsyncMock()) as sleep:
            for delay in (-1, 10001, True, 1.5, '100'):
                self.assertFalse((await self.actuator.wait_for_delay(delay)).ok)
            self.assertEqual(sleep.await_count, 0)
            self.assertTrue((await self.actuator.wait_for_delay(0)).ok)
            self.assertTrue((await self.actuator.wait_for_delay(10000)).ok)
        self.assertEqual([call.args for call in sleep.await_args_list], [(0.0,), (10.0,)])
        self.assertEqual(self.transport.calls, [])

    def test_upstream_declaration_filter_removes_unavailable_device_actions(self):
        names = ['click_sequence', 'click', 'focus_and_clear_text', 'wait_for_text', 'open_link',
                 'observe_screen', 'run_adb_command']
        declarations = [{'name': name} for name in names]
        filtered = self.manifest.filter_declarations(declarations, self.actuator, 'flash')
        self.assertEqual([declaration['name'] for declaration in filtered],
                         ['click_sequence', 'click', 'run_adb_command'])
        # Upstream retains this bypass channel; the runner must disable it separately.
        self.assertIn('run_adb_command', self.manifest.BACKEND_INDEPENDENT_TOOLS)

    async def test_hierarchy_failure_never_uses_the_transport(self):
        with self.assertRaisesRegex(GhostError, 'hierarchy is unavailable'):
            await self.actuator.get_ui_elements()
        self.assertEqual(self.transport.calls, [])

    async def test_actual_upstream_observation_preserves_jpeg_without_hierarchy(self):
        captured = {}

        def persist(image, **kwargs):
            captured.update(image=image, **kwargs)
            return 'neutral-frame'

        storage = SimpleNamespace(get_or_create_image=persist,
                                  get_image_path=lambda name: Path('private') / (name + '.jpg'))
        ctx = SimpleNamespace(device=SimpleNamespace(device_width=1, device_height=1), data_engine=storage)
        self.actuator.ctx = ctx
        with self.assertLogs('ghost_test_artemis_observation', level='ERROR'):
            result, image = await self.observation.observe(ctx, self.actuator, settle_ms=0)
        self.assertTrue(result.ok)
        self.assertIsInstance(result, self.types.ObserveResult)
        self.assertFalse(result.hierarchy_ok)
        self.assertEqual(result.elements, [])
        self.assertIsNone(result.width)
        self.assertIsNone(result.height)
        self.assertEqual((ctx.device.device_width, ctx.device.device_height), (1200, 1920))
        self.assertEqual(captured, dict(image=image, ui_tree=None, ocr_result=[]))
        self.assertEqual(image[:3], b'\xff\xd8\xff')
        self.assertEqual(Path(result.screenshot_path), Path('private/neutral-frame.jpg'))

    async def test_actual_upstream_wire_handlers_bind_supported_actions(self):
        cases = [
            ('click', dict(target=[500, 500], times=2, delay_ms=0),
             [('tap', '600', '960'), ('tap', '600', '960')]),
            ('click_sequence', dict(sequence=[[250, 500], [750, 500]], delay_ms=0),
             [('tap', '300', '960'), ('tap', '900', '960')]),
            ('long_press', dict(target=[500, 500], duration_ms=750), [('long-press', '600', '960', '750')]),
            ('input_text', dict(text='neutral', target=[500, 500], clear_exist=False),
             [('tap', '600', '960'), ('text', 'neutral')]),
            ('swipe', dict(start=[0, 1000], end=[1000, 0], duration_ms=800),
             [('swipe', '0', '1919', '1199', '0', '800')]),
            ('erase_one_char', {}, [('key', 'DEL')]),
            ('manage_app', dict(action='launch', app_name='com.vertex.ghost'),
             [('open-component', 'com.vertex.ghost/.GhostTestActivity')]),
        ]
        for name, arguments, expected in cases:
            with self.subTest(action=name):
                await self.actuator.get_screen_data()
                count = len(self.transport.inputs)
                handler = self.specs.make_wire_handler(
                    self.specs.ACTION_SPECS[name], self.actuator, lambda result: result,
                    lambda action, error: self.fail('Unexpected wire exception: ' + str(error)))
                result = await handler(**arguments)
                self.assertIsInstance(result, self.types.ActionResult)
                self.assertTrue(result.ok)
                self.assertEqual(result.action, name)
                self.assertEqual(self.transport.inputs[count:], expected)


if __name__ == '__main__':
    unittest.main()
