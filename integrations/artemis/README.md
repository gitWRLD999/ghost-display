# Artemis + Ghost (experimental)

This adapter directs Artemis's device actions to Ghost's independent display using
`ghostctl`. It does not change Ghost's Android application or install an Accessibility
service on the phone. The first implementation uses screenshots without a UI tree.

**Status, 2026-10-12:** 73 local tests pass with no skips: 63 bridge/contract checks
and ten tests using the real MCP client/server memory transport. The pinned upstream
manifest, models, action server, action session, observation and wire handlers are
exercised; unrelated runtime/controller/OCR imports are stubbed and device transport
is simulated in these tests. Full Artemis startup, autonomous model tasks and remote
Termux SSH operation remain untested. See [current validation](../../docs/VALIDATION_2026-10-12.md)
for the separate Android emulator checks. Do not run Artemis's default quickstart
against a personal phone to test this adapter.

Upstream source audited: [google/artemis](https://github.com/google/artemis/tree/351ca8422f7b5b54e80a9c1ce03a222e02415b6b),
commit `351ca8422f7b5b54e80a9c1ce03a222e02415b6b`.

## Why the custom actuator matters

Artemis has an explicit `ctx.actuator` override. Its action session and executor use
this backend, and its manifest hides unavailable device actions. Its default Android
driver captures and injects using the device's ordinary ADB/UIAutomator interfaces;
those are not automatically scoped to Ghost. Default setup also enables the awake
service and automatic Accessibility Helper installation.

The relevant primary sources are the [context hook](https://github.com/google/artemis/blob/351ca8422f7b5b54e80a9c1ce03a222e02415b6b/artemis/context.py),
[actuator contract](https://github.com/google/artemis/blob/351ca8422f7b5b54e80a9c1ce03a222e02415b6b/artemis/mcp/actuators/base.py),
[manifest](https://github.com/google/artemis/blob/351ca8422f7b5b54e80a9c1ce03a222e02415b6b/artemis/mcp/action_manifest.py),
[action session](https://github.com/google/artemis/blob/351ca8422f7b5b54e80a9c1ce03a222e02415b6b/artemis/mcp/action_session.py),
[ADB driver](https://github.com/google/artemis/blob/351ca8422f7b5b54e80a9c1ce03a222e02415b6b/artemis/drivers/android/adb_driver.py),
and [configuration defaults](https://github.com/google/artemis/blob/351ca8422f7b5b54e80a9c1ce03a222e02415b6b/.env.example).

## Local validation

Python 3.12+ and the pinned [test dependencies](requirements-test.txt) run the complete
suite, including MCP. Tests load pinned upstream code directly, avoiding expensive
Artemis package initialization. This validates its action layer, not complete agent
startup or provider/model execution. Pillow is also required by the read-only probe.

Place a checkout of the pinned Artemis commit beside the Ghost repository, named
`artemis-upstream`. From the Ghost repository root:

```powershell
python -m unittest discover -s integrations/artemis/tests -v
```

Install dependencies with `python -m pip install -r integrations/artemis/requirements-test.txt`.
Without that checkout upstream-dependent tests skip. The tests verify its exact
commit; record any skips in a test report. MCP 1.29 currently emits a nonfatal
`lifespan` annotation warning during setup; normal runs pass, while treating that
third-party warning as an error fails MCP setup. The warning is not suppressed.

## Read-only live probe

Ghost must already be running. Install the CLI as described in [CLI.md](../../docs/CLI.md).
No display lifecycle or input command is issued by this probe.

```powershell
python integrations/artemis/probe.py --serial DEVICE_SERIAL --adb C:/path/adb.exe --out private/artemis/frame.png
```

For remote access, the phone needs Termux OpenSSH, a trusted SSH host key, PC key
authentication, working `rish`, and `cli/ghostctl-rish` installed as `~/bin/ghostctl`.
Tailscale connectivity alone does not provide that shell or Shizuku authorization.
The transport uses batch mode and strict host-key checking; it never accepts a new
host key silently or asks for a password inside an autonomous task.

```powershell
python integrations/artemis/probe.py --ssh TERMUX_USER@PHONE_TAILSCALE_NAME --out private/artemis/frame.png
```

## Artemis action-layer wiring

The following is an integration recipe for a **fully installed** pinned Artemis
runtime. Add `integrations/artemis` to its Python path, construct the backend before
the first action session, then validate it:

```python
from ghost_bridge import CommandTransport, GhostSession
from ghost_actuator import GhostActuator
from artemis.mcp.action_manifest import validate_actuator

transport = CommandTransport.adb("C:/path/adb.exe", "DEVICE_SERIAL")
session = GhostSession(transport, allowed_packages={"com.vertex.ghost"}, max_actions=40)
ctx.actuator = GhostActuator(session, ctx=ctx)
validate_actuator(ctx.actuator)
screen = await ctx.actuator.get_screen_data()  # Required before the first input.
```

The upstream `build_action_server(ctx.actuator)` exposes this backend's supported
actions. Its real MCP memory transport is tested with a simulated Ghost device;
a complete live-device Artemis runner remains a separate gate. Do not substitute
the default ADB server when the adapter fails.

Before starting any Artemis process, set `ARTEMIS_KEEP_DEVICE_AWAKE=false` and
`ARTEMIS_HELPER_AUTO_INSTALL=false`. Disable video tooling and every raw ADB/system
channel in the runner being used. **An actuator override alone does not isolate the
whole agent:** upstream `run_adb_command`, diagnostics, setup, video and other direct
controller consumers can bypass it. Flash has a smaller surface but still requires
an audit of task startup and teardown before autonomous use on the personal phone.
The default web mirror is not wired to Ghost by this adapter.

## Supported behavior and limits

- Coordinates are Artemis integers on a 0..1000 scale. Inputs go to full Ghost pixels.
- Captures must be real full-resolution PNGs whose dimensions match live status.
  The actuator decodes these and emits JPEG for upstream's `image/jpeg` MCP blocks;
  the read-only probe saves the original PNG.
- Each input checks the observed display ID, backend PID and geometry. Recovery or
  resizing requires a new capture. A successful action also invalidates its previous
  observation; only an explicit bounded sequence or focus-and-insert transaction can
  dispatch multiple operations from one observation. There remains a status-to-command race because
  Ghost's current command protocol does not atomically accept an expected generation.
- Input uses only Ghost CLI operations, with an explicit ADB serial or SSH endpoint.
  An observed fresh display with `inputHealth=untested` permits its first targeted
  action. Invalid health values and `no_frame` still block operation.
- Sequences and captures serialize within one actuator. Use one operator/session
  per Ghost display; another client can still change its contents.
- App launch requires a session allowlist. `com.vertex.ghost` launches the neutral
  test activity, not the native viewer. Package names must be exact, not app labels.
- Text supports insertion only (`clear_exist=False`). Unsupported characters are
  reported by Ghost. Whole-field clearing, clipboard replacement and UI-tree text
  waits are excluded.
- UI hierarchy access raises an explicit unavailable error. Upstream observation
  records `hierarchy_ok=False` while retaining the image; this path currently omits
  observation dimension fields, so the actuator updates `ctx.device` dimensions
  directly. Tests execute the actual upstream observation function and verify this
  interaction, with unrelated runtime imports stubbed. Upstream observation
  also persists frames through the data engine or its temporary screenshot directory;
  configure private storage and retention before real app tests.
- Power/volume/global keys, force-stop, raw shell, physical viewer and video capture
  are excluded. Shared app data and single-instance tasks remain Android limitations.
- Action budgets are bounded; ambiguous transport failures are never retried automatically.

## Next acceptance gates

1. Read-only live probe: matching dimensions and a real neutral Ghost frame.
2. Ghost test fixture: tap, long press, ASCII insertion and scroll, with visual
   verification and concurrent normal physical-phone use.
3. Screen-off phase: let the user lock the phone, then repeat Ghost fixture actions;
   separately record physical panels OFF and Ghost ON.
4. Full live-device runner test, then a bounded model task with no bypass
   tools. Start with the neutral fixture before allowing a real app.

An emulator is optional for runtime/schema tests. It cannot validate Samsung's
physical-screen-off behavior. Use at most 2 GB guest RAM and 2 CPU cores initially,
and stop the test emulator if host available RAM drops below 2 GB. No emulator was
started in the 2026-09-29 local contract test session; a fresh headless API 36 emulator
was created for the separate 2026-10-12 validation.
