# ghostctl reference

Every command returns one JSON object and a nonzero exit code on failure. A successful `screenshot` without `--out` emits only image bytes. `--json` is accepted; JSON is already the default.

| Command | Arguments / behavior |
| --- | --- |
| `start` | Start or reuse the canonical display and enable recovery. |
| `stop` | Clear desired state, stop the host, release the display and backend. |
| `status --json` | Running state, display ID, dimensions, density, orientation/rotation, power state, UID/PID, flags, capture/input health, foreground window. |
| `open-app` | Launcher package, e.g. `com.android.chrome`. |
| `open-component` | Explicit component, e.g. `com.vertex.ghost/.GhostTestActivity`. |
| `open-url` | URL handled by the phone's default browser. |
| `tap` | `x y` in Ghost pixels. |
| `long-press` | `x y [durationMs]`, default 700. |
| `swipe` / `scroll` | `x1 y1 x2 y2 [durationMs]`, default 350. |
| `text` | One quoted string; inserted into the focused Ghost field. |
| `key` | Android key number or name, such as `ENTER`, `DEL`, `KEYCODE_TAB`. |
| `back` | Back targeted at Ghost. |
| `home` | Open Ghost's blank workspace. |
| `rotate` | Swap display width/height without replacing the display ID. |
| `dump` | WindowManager information for Ghost's display only. |
| `viewer` | Explicitly open the native viewer on physical display 0. |
| `screenshot` | `--out PATH`, `--format png\|jpeg`, `--quality 1..100`, `--max-width N`. |

Coordinates outside the current bounds are rejected. Screenshot scaling does **not** change input coordinates: multiply coordinates measured in a reduced image by the ratio between the display's width and the image's width. The native viewer performs this transform automatically using full-resolution frames.

`rotation` is the Android display rotation value; `rotate` changes the surface orientation by resizing, so `orientation` and `width`/`height` describe the result even when `rotation` remains 0.

## Screenshot destinations

```sh
# Android / rish: a path on the phone
ghostctl screenshot --out /sdcard/Download/ghost.png

# Binary PNG on stdout
adb exec-out sh /data/local/tmp/ghostctl screenshot > frame.png

# Smaller JPEG for a fast vision loop
ghostctl screenshot --format jpeg --quality 75 --max-width 800 --out /sdcard/Download/ghost.jpg
```

Use `cli/ghostctl.ps1` on PowerShell to preserve binary streams across versions. Its `--out` is a PC path; the Android/rish `--out` is a phone path. PowerShell 7 is required for the wrapper's argument handling.

## State and errors

```json
{"ok":true,"running":true,"displayId":7,"width":1200,"height":1920,"density":320,"rotation":0,"orientation":"portrait","state":"ON","captureHealth":"ready","inputHealth":"ok"}
```

Additional fields include `frameSequence`, `frameAgeMs`, `displayGroupId`, `virtualDeviceId`, `associationId`, `currentPackage`, `currentActivity`, `backendPid`, `backendUid`, and resolved flag names/values. A static app may have an old `frameAgeMs` while its cached frame remains valid. Foreground fields are nullable.

If the backend is absent, `status` returns `running:false` without creating a display. Start Shizuku and issue `start` to recover. Reject unsupported text as an error; do not silently reroute input through the physical display or clipboard.

## Local protocol

The abstract Unix socket is `com.vertex.ghost.control.v1`. Accepted peer UIDs are shell, root, and Ghost's own app UID. There is no TCP/LAN listener.

Send one UTF-8 JSON object followed by a newline (maximum 256 KiB):

```json
{"command":"tap","x":600,"y":400}
```

The server returns a JSON line. A screenshot returns a header with `ok`, `mime`, and `byteLength`, followed by exactly that many binary bytes. Use the CLI for lifecycle operations so the foreground host's desired state stays in sync. `scripts/device-probe.ps1` is a development aid that creates a temporary localhost ADB forward and removes it afterward.

## Broadcast compatibility

The exported receiver is guarded by Android's `INTERACT_ACROSS_USERS_FULL` permission. Existing shell integrations can continue using `com.vertex.ghost.HEADLESS_START`, `HEADLESS_STOP`, `HEADLESS_STATUS`, `HEADLESS_SCREENSHOT`, `OPEN_APP`, `OPEN_COMPONENT`, `OPEN_URL`, `CLICK`, `SWIPE`, `SET_TEXT`, `FOCUS`, and `DUMP`.

The new responses are JSON. `FOCUS` acknowledges display-scoped focus; target a field with `CLICK`. Physical panel/brightness controls and Accessibility fallbacks are intentionally absent.
