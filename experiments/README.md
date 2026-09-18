# Disposable display experiments

`GhostDisplayExperiment.java` is a shell-only, time-bounded proof of concept. It does not replace the installed Ghost backend. It creates its own comparison display and writes one PNG every ten seconds under `/data/local/tmp/ghost-experiment-<mode>.png`.

The `regular` mode requests the original flags (97608). The `vdm` mode creates a real VirtualDevice and requests DEVICE_DISPLAY_GROUP (128328). It needs a dedicated companion association owned by `com.android.shell`, using the app-streaming profile. The source does not create or remove that association itself.

## Build

Compile against Android SDK 36 with JDK 17 or later, then use build-tools 36.0.0 `d8` to package all generated class files, including inner classes. Do not execute code downloaded from a different source as part of these probes.

```powershell
./build-probe.ps1 -JavaHome /path/to/jdk -AndroidSdk /path/to/sdk
adb push ./build/GhostDisplayExperiment/classes.dex /data/local/tmp/GhostDisplayExperiment.dex
```

## Controlled experiment

Inspect existing associations first with `cmd companiondevice list 0`. Create a **new, dedicated synthetic association**, using an unused locally administered address, and record its ID. Never reuse the user's watch, Phone Link, or other existing association. The following address is a test example; check for collisions first.

```sh
adb shell cmd companiondevice associate 0 com.android.shell 02:00:00:47:48:01 android.app.role.COMPANION_DEVICE_APP_STREAMING true
adb shell cmd companiondevice list 0
```

Run the probe in a terminal. Replace `ASSOCIATION_ID` with the returned ID:

```sh
adb shell 'CLASSPATH=/data/local/tmp/GhostDisplayExperiment.dex app_process /system/bin GhostDisplayExperiment vdm 600 ASSOCIATION_ID'
```

The probe prints its process, device and display IDs. In another terminal, launch the installed Ghost test activity on the printed display ID. Wait until it is visible and has focus before typing. Keep only one fixture instance on that display: multiple fixtures share a per-display diagnostic file and can race while writing it.

```sh
adb shell am start --user 0 --display DISPLAY_ID -f 0x18000000 -n com.vertex.ghost/.GhostTestActivity
adb shell input -d DISPLAY_ID tap 600 374
adb pull /data/local/tmp/ghost-experiment-vdm.png ./frame.png
```

For lock testing, lock the phone normally, leave its screen off, and record at least five minutes of window-policy state, group-specific power state, changing fixture time, and actual captures. Inject a targeted tap and text after that interval and visually verify the next PNG. Secure keyguard must remain showing, physical screen must remain off, and the virtual group's state must remain ON.

Wait for the physical screen to finish turning off before starting the timer; an immediate check after a sleep key can observe the transition. `verify-lock.ps1` automates sampled lock/panel checks, fixture-clock progress, and final targeted input for the 1200 × 1920 fixture:

```powershell
./verify-lock.ps1 -Serial YOUR_USB_SERIAL -DisplayId DISPLAY_ID
```

It leaves power and lock state alone, fails when an observed condition changes, and saves only summarized state plus a synthetic PNG under the ignored `build/` directory. Inspect the PNG and power-group wake logs as well: thirty-second samples cannot rule out a brief wake between samples. The verifier's syntax and panel-state parser have been checked; the September 17 live duration run used its earlier local harness.

Incoming calls can wake the physical display while the VirtualDevice keeps rendering. This invalidates a strict uninterrupted screen-off measurement; it does not by itself show a virtual-display failure. Do not suppress the user's calls to obtain a passing result. A global `display_group_added` wake reason also does not establish that physical group 0 woke; inspect group-specific state.

The helper accepts a duration from 10 to 600 seconds and closes its resources automatically. Binder ownership also removes its VirtualDevice when the process dies. After the helper is gone, remove **only its dedicated association** using the same owner and address:

```sh
adb shell cmd companiondevice disassociate 0 com.android.shell 02:00:00:47:48:01
```

Verify that the experiment display, VirtualDevice and wake locks have disappeared and that the user's pre-existing associations remain. If testing `cmd display power-off 0` separately, arrange a bounded reset and restore using `cmd display power-reset 0`.

See [the experiment log](../docs/EXPERIMENTS_2026-09-17.md) for the exact results. These commands are development tools, not a production setup flow.

## Clean browser showcase helper

`GhostBrowserDemo.java` launches a public HTTPS page in Chrome's Custom Tab on an existing Ghost display. It does not create a display or control the browser afterward; use normal `ghostctl` commands for that. Custom Tabs share browser cookies and are not a private profile. Inspect captures before publishing them.

```powershell
./build-probe.ps1 -SourceName GhostBrowserDemo -JavaHome /path/to/jdk -AndroidSdk /path/to/sdk
adb push ./build/GhostBrowserDemo/classes.dex /data/local/tmp/GhostBrowserDemo.dex
adb shell 'CLASSPATH=/data/local/tmp/GhostBrowserDemo.dex app_process /system/bin GhostBrowserDemo DISPLAY_ID https://en.wikipedia.org/wiki/Android_%28operating_system%29'
```

Replace `DISPLAY_ID` with the current positive ID from `ghostctl status`. See [the actual demo](../docs/SHOWCASE.md).
