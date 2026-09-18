# Architecture

Ghost has one privileged owner and optional clients. Package identity remains `com.vertex.ghost`; privileged operations run in a Shizuku UserService with shell UID 2000 and a real `com.android.shell` package context.

## Ownership and transport

`GhostHostService` remembers desired running state and checks the backend every 15 seconds. `GhostShizukuClient` maintains the Binder binding. The backend owns the VirtualDisplay, ImageReader, input injection and wake locks. It binds one abstract Unix socket, `com.vertex.ghost.control.v1`, which also prevents duplicate backend owners. Both Binder and socket access check the caller UID: Ghost, shell, or root.

The CLI runs through Android `app_process` using the installed APK. JSON commands use the socket; screenshots use a length-prefixed binary response. The viewer uses Binder and a file-descriptor image pipe. A bounded worker pool serves socket clients. No network listener, Accessibility service, physical-display mirroring, or localhost ADB workaround is involved.

## Canonical display configuration

The backend creates an association-backed Android VirtualDevice, then creates the capture display through that device. It resolves framework constants by name at runtime. On the tested Android 16 device their combined value is **128328 (`0x1f548`)**.

| Flag | Value | Purpose |
| --- | ---: | --- |
| OWN_CONTENT_ONLY | 8 | Do not mirror another display. |
| SUPPORTS_TOUCH | 64 | Accept targeted touch events. |
| DESTROY_CONTENT_ON_REMOVAL | 256 | Dispose of tasks on display removal. |
| TRUSTED | 1024 | Enable trusted secondary-display behavior. |
| DEVICE_DISPLAY_GROUP | 32768 | Place the display in its owning VirtualDevice's group. |
| ALWAYS_UNLOCKED | 4096 | Request unlocked secondary-display behavior. |
| TOUCH_FEEDBACK_DISABLED | 8192 | Suppress system touch feedback. |
| OWN_FOCUS | 16384 | Maintain independent display focus. |
| STEAL_TOP_FOCUS_DISABLED | 65536 | Preserve the physical display's top focus. |

There is no PUBLIC flag. Default dimensions are 1200 × 1920 at density 320. The name is `Ghost Headless`. Unsupported constants fail explicitly rather than silently selecting a weaker configuration.

The original ordinary VirtualDisplay path was placed in group 0 by Samsung despite requesting OWN_DISPLAY_GROUP; secure lock stopped useful capture. The VirtualDevice path obtains an independent group. Start now rejects group 0 instead of reporting a successful workspace. Samsung Hidden Space and private never-blank workarounds are excluded. See [device tests](TEST_RESULTS.md).

`GhostVirtualDevice` creates a dedicated self-managed app-streaming association owned by shell. A random locally administered address is an identifier, not a Bluetooth connection. An atomic ownership record under `/data/local/tmp/ghost-display/` lets a replacement backend reuse its association after a crash. The backend checks owner, profile and self-managed status before reuse or removal. Explicit Stop removes only that association; pre-existing watch and phone-link associations are untouched. No Wi-Fi connection or TCP listener is involved in Ghost's display transport; starting Shizuku remains a separate prerequisite.

## Capture and input

An RGBA ImageReader holds three buffers. A background thread continually acquires the latest frame and closes every acquired image. The backend reuses a padded bitmap, copies a coherent frame for encoding, crops row padding, and supports PNG or JPEG with optional width scaling. The viewer polls only while visible and never replaces the producer surface.

Touch and key events receive the current Ghost display ID before injection. Coordinates use full display pixels. Text is preflighted through Android's virtual key character map; unsupported characters produce an error before injection. There is no fallback to physical display 0 or the clipboard. Launches explicitly specify the display and a new task; single-instance applications can still impose their own task-reuse behavior.

The viewer renders the full frame inside an aspect-preserving rectangle. Touch coordinates are mapped through that rectangle. Rotate swaps display dimensions; clients must refresh dimensions after rotation or recovery.

## Lifecycle

Start reuses a valid display. Hide stops viewer polling only. Stop clears desired state, releases the display, reader, frame thread, bitmap and wake locks, and removes the Shizuku backend. A backend crash releases its process-owned resources; the foreground host creates a new display on its next successful check. Transient app UI state is not restored automatically.

A partial CPU lock and an explicitly display-targeted screen lock belong to the backend. `status` exposes VirtualDevice and association IDs, display state, group ID, frame age and sequence, input health, and backend identity. Power behavior still requires real-device verification after firmware updates. A ready frame means bytes are available, not that protected content is visible.

## References

- [Android 16 display constants](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/core/java/android/hardware/display/DisplayManager.java)
- [ImageReader lifecycle](https://developer.android.com/reference/android/media/ImageReader)
- [Shizuku API](https://github.com/RikkaApps/Shizuku-API)
