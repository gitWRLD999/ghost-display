"""Ghost-only device checks: no physical launch, unlock, power, or global input.

Evidence stays private. Fixture actions require --fixture-actions; screen-off checks
require the human to lock the physical phone first. Existing Ghost must be running.
"""
import argparse
import asyncio
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations/artemis'))
from ghost_bridge import CommandTransport, GhostError, GhostSession


def power_summary(policy, display, inputs, windows):
    panels = [dict(state=s, committedState=c) for s, c in re.findall(
        r'DisplayDeviceInfo\{"Built-in Screen"[^\r\n]*?state (\w+), committedState (\w+)', display)]
    focus = re.search(r'FocusedDisplayId:\s*(\d+)', inputs)
    top_focus = re.search(r'mTopFocusedDisplayId=(\d+)', windows)
    return dict(locked=bool(re.search(r'^\s+showing=true\s*$', policy, re.M)),
                physicalScreenOff='screenState=SCREEN_STATE_OFF' in policy,
                panels=panels, inputFocusedDisplay=int(focus[1]) if focus else None,
                windowFocusedDisplay=int(top_focus[1]) if top_focus else None)


def require_off(summary):
    if not summary['locked'] or not summary['physicalScreenOff']:
        raise GhostError('Secure physical lock/off is not confirmed; this script never locks or wakes the phone')
    if not summary['panels'] or any(p['state'] != 'OFF' or p['committedState'] != 'OFF' for p in summary['panels']):
        raise GhostError('Physical panel OFF/OFF is not confirmed by OEM diagnostics')


async def run(args):
    from PIL import Image
    destination = args.evidence.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    session = GhostSession(CommandTransport.adb(args.adb, args.serial),
                           allowed_packages={'com.vertex.ghost'}, max_actions=12)
    report = dict(startedAt=time.strftime('%Y-%m-%dT%H:%M:%S%z'), checks=[], samples=[],
                  fixtureActionsRequested=args.fixture_actions, screenOffRequired=args.require_screen_off)
    started = time.monotonic()

    def save():
        (destination / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    def check(name, passed, detail=None):
        report['checks'].append(dict(test=name, passed=bool(passed), detail=detail))
        save()
        print(json.dumps(dict(test=name, passed=bool(passed))), flush=True)
        if not passed:
            raise GhostError(name)

    async def fixed_read(command):
        process = await asyncio.create_subprocess_exec(
            args.adb, '-s', args.serial, 'exec-out', command,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, error = await asyncio.wait_for(process.communicate(), 15)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise GhostError('Read-only diagnostic interrupted')
        if process.returncode:
            raise GhostError(error.decode('utf-8', errors='replace')[:500])
        return out.decode('utf-8', errors='replace')

    async def diagnostics():
        # Parse only selected power/focus fields; never persist raw phone dumps.
        policy = await fixed_read('dumpsys window policy')
        display = await fixed_read('dumpsys display')
        inputs = await fixed_read('dumpsys input')
        windows = await fixed_read('dumpsys window')
        summary = power_summary(policy, display, inputs, windows)
        if summary['inputFocusedDisplay'] != 0 or summary['windowFocusedDisplay'] != 0:
            raise GhostError('Physical focus is not confirmed on display 0; inspect before proceeding')
        if args.require_screen_off:
            require_off(summary)
        return summary

    async def capture(name, allow_uniform=False):
        frame = await session.observe()
        with Image.open(BytesIO(frame.image)) as image:
            image.load()
            extrema = image.convert('L').getextrema()
        if extrema[0] == extrema[1] and not allow_uniform:
            raise GhostError('Uniform frame; rendering is not established')
        (destination / name).write_bytes(frame.image)
        return frame

    async def fixture(display_id):
        # Only this app's synthetic test record, never another application's data.
        raw = await fixed_read(f'run-as com.vertex.ghost cat files/test-display-{display_id}.json')
        state = json.loads(raw)
        if state.get('displayId') != display_id:
            raise GhostError('Fixture belongs to a different display')
        return state

    try:
        before = await diagnostics()
        frame = await capture('initial.png', allow_uniform=args.fixture_actions)
        report['display'] = dict(displayId=frame.display_id, width=frame.width, height=frame.height)
        report['physicalBefore'] = before
        check('real-frame-and-focus', True)
        if args.fixture_actions:
            # Coordinates below are previously verified for the canonical fixture;
            # fail rather than guess if geometry/density changes.
            status = await session.status()
            if (frame.width, frame.height, status.get('density')) != (1200, 1920, 320):
                raise GhostError('Fixture actions require visually verified 1200x1920 @320 geometry')
            if status.get('currentActivity') != 'com.vertex.ghost/com.vertex.ghost.GhostTestActivity':
                await session.launch('com.vertex.ghost')
                await asyncio.sleep(1)
            await capture('fixture-before.png')
            baseline = await fixture(frame.display_id)
            await session.text('GhostCheck123')
            await capture('fixture-text.png')
            typed = await fixture(frame.display_id)
            check('targeted-ascii-text', typed['text'].endswith('GhostCheck123'))
            await session.key('DEL')
            await capture('fixture-delete.png')
            deleted = await fixture(frame.display_id)
            check('targeted-delete', deleted['text'] == typed['text'][:-1])
            await session.click(500, 195)
            await capture('fixture-tap.png')
            tapped = await fixture(frame.display_id)
            check('targeted-tap', tapped['clicks'] == baseline['clicks'] + 1)
            await session.click(500, 195, duration_ms=750)
            await capture('fixture-hold.png')
            held = await fixture(frame.display_id)
            check('targeted-long-press', held['longPresses'] == baseline['longPresses'] + 1)
            await session.swipe((500, 800), (500, 400), duration_ms=450)
            await asyncio.sleep(0.5)
            await capture('fixture-after.png')
            scrolled = await fixture(frame.display_id)
            check('targeted-scroll', scrolled['scrollY'] > baseline['scrollY'])
            check('physical-focus-retained-after-actions', await diagnostics() is not None)

        latencies = []
        for _ in range(12):
            start = time.monotonic()
            image_bytes = await session.transport.run('screenshot', '--format', 'jpeg', '--quality', '75', '--max-width', '800')
            with Image.open(BytesIO(image_bytes)) as image:
                image.load()
                if image.format != 'JPEG' or image.width != 800:
                    raise GhostError('Scaled JPEG capture is invalid')
            latencies.append(round((time.monotonic() - start) * 1000, 2))
        check('repeated-scaled-jpeg', True, dict(captures=12, meanMs=round(statistics.mean(latencies), 2), maxMs=max(latencies)))

        previous_clock = None
        deadline = time.monotonic() + args.duration
        while True:
            physical = await diagnostics()
            frame = await capture('latest.png')
            status = await session.status()
            sample = dict(elapsedSeconds=round(time.monotonic() - started, 2),
                          displayId=frame.display_id, state=status.get('state'),
                          frameSequence=status.get('frameSequence'), physical=physical,
                          frameSha256=hashlib.sha256(frame.image).hexdigest())
            if args.fixture_actions:
                current = await fixture(frame.display_id)
                if previous_clock is not None and current['seconds'] <= previous_clock:
                    raise GhostError('Fixture clock stopped advancing')
                previous_clock = current['seconds']
                sample['fixtureClock'] = previous_clock
            report['samples'].append(sample)
            save()
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(15, max(0, deadline - time.monotonic())))
        check('sampled-rendering-and-power', True, dict(samples=len(report['samples']), durationSeconds=args.duration))
        report['ok'] = True
        report['visualInspectionRequired'] = True
    except Exception as error:
        # Do not include phone output or old fixture text in published errors.
        report['ok'] = False
        report['errorType'] = type(error).__name__
        save()
        raise
    finally:
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--evidence', type=Path, default=Path('private/ghost-check'))
    parser.add_argument('--fixture-actions', action='store_true')
    parser.add_argument('--require-screen-off', action='store_true')
    parser.add_argument('--duration', type=int, default=0, help='Sample for 0..1800 seconds, every 15 seconds')
    args = parser.parse_args()
    if not 0 <= args.duration <= 1800:
        parser.error('--duration must be 0..1800')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
