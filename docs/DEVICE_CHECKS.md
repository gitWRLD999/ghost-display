# Run focused device checks

[`scripts/ghost-check.py`](../scripts/ghost-check.py) tests the existing Ghost display
without opening a physical-screen test activity, waking/unlocking the phone, stopping
Ghost or force-stopping a shared app. It uses an explicit USB ADB serial. Python 3.12+
and Pillow are required.

Inspect a live Ghost frame first. Ghost and Shizuku must already be available. On a
fresh display, use `ghostctl home` or explicitly launch the neutral fixture if there
is no rendered frame yet. The script does not bootstrap a stopped backend.

```powershell
# Decode real frames, check focus, benchmark 12 scaled JPEGs, sample for a minute.
python scripts/ghost-check.py --serial DEVICE_SERIAL --duration 60 --evidence private/device-check

# Add neutral test-fixture text, Delete, tap, long press and scroll assertions.
python scripts/ghost-check.py --serial DEVICE_SERIAL --fixture-actions --duration 90 --evidence private/fixture-check

# Have the human lock the phone first. This script never does so on their behalf.
python scripts/ghost-check.py --serial DEVICE_SERIAL --fixture-actions --require-screen-off --duration 330 --evidence private/locked-check
```

Use `--adb /path/to/adb` for an explicit executable. Fixture action coordinates are
previously verified for 1200×1920 at density 320; a different configuration fails
rather than guessing. A real frame is required before each action. The fixture is
reused when already foreground on Ghost. Captured screenshots require visual review
even when machine assertions pass.

Power/focus diagnostics are parsed in memory; raw phone dumps are never saved.
Screenshots and result files belong under ignored `private/` paths. Initial captures
can contain the previous Ghost app's content. Review and curate anything published.
An unfamiliar OEM diagnostic format fails the screen-off check; missing fields are
not treated as proof of OFF.

The older `scripts/smoke.ps1` intentionally starts a fresh session and puts a fixture
on the physical phone. Use it only during an unlocked development session when the
human has agreed to that interaction. It is not the concurrent-use test runner.

See [the operating protocol](AGENT_PROTOCOL.md), [historical Fold 7 results](TEST_RESULTS.md)
and [current validation](VALIDATION_2026-10-12.md). Emulator results cannot establish
Samsung-specific power behavior, unfolding support or overnight endurance.
