"""Diagnostic parsing tests, independent of a connected phone."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ghost_device_check', Path(__file__).resolve().parents[1] / 'ghost-check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class DiagnosticTests(unittest.TestCase):
    def summary(self, panel='OFF', committed='OFF', locked=True):
        return check.power_summary(
            ('  showing=true\n' if locked else '  showing=false\n') + 'screenState=SCREEN_STATE_OFF',
            f'  DisplayDeviceInfo{{"Built-in Screen", state {panel}, committedState {committed}\n'
            '  DisplayDeviceInfo{"Built-in Screen", state OFF, committedState OFF\n',
            'FocusedDisplayId: 0', 'mTopFocusedDisplayId=0')

    def test_fold_both_panels_locked_off(self):
        result = self.summary()
        check.require_off(result)
        self.assertEqual(len(result['panels']), 2)
        self.assertEqual(result['inputFocusedDisplay'], 0)
        self.assertEqual(result['windowFocusedDisplay'], 0)

    def test_on_or_uncommitted_panel_is_rejected(self):
        for panel, committed in [('ON', 'ON'), ('OFF', 'ON')]:
            with self.assertRaises(check.GhostError):
                check.require_off(self.summary(panel, committed))

    def test_unlocked_phone_is_rejected(self):
        with self.assertRaises(check.GhostError):
            check.require_off(self.summary(locked=False))

    def test_unknown_oem_diagnostics_do_not_claim_off(self):
        result = check.power_summary('', '', '', '')
        self.assertIsNone(result['inputFocusedDisplay'])
        self.assertIsNone(result['windowFocusedDisplay'])
        with self.assertRaises(check.GhostError):
            check.require_off(result)

    def test_only_builtin_panel_not_virtual_display_is_counted(self):
        result = check.power_summary('showing=true\nscreenState=SCREEN_STATE_OFF',
                                    'DisplayDeviceInfo{"Ghost", state OFF, committedState OFF',
                                    'FocusedDisplayId: 0', 'mTopFocusedDisplayId=0')
        self.assertEqual(result['panels'], [])
        with self.assertRaises(check.GhostError):
            check.require_off(result)

    def test_unrelated_phone_content_not_retained(self):
        result = check.power_summary('private fixture secret', 'private application title',
                                    'FocusedDisplayId: 0\nprivate text', 'mTopFocusedDisplayId=0\nprivate text')
        self.assertNotIn('private', str(result))


if __name__ == '__main__':
    unittest.main()
