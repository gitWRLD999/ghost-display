# Screen-off rendering research

Research date: 2026-09-17

**Follow-up:** The user authorized experiments after this research pass. A real VirtualDevice has now produced a non-default display group and working capture/input under secure lock in an isolated probe. See [the experiment log](EXPERIMENTS_2026-09-17.md) for measured results and remaining integration work. The hypotheses below are the pre-experiment record.

This document is a research record only. It does not change Ghost, the phone, Shizuku, system settings, or the installed APK. The goal is to explain why the Fold7's secure-lock / physical-screen-off case fails and identify the next experiments worth running.

## Executive conclusion

The strongest lead is not another wake-lock combination. It is creating the display through Android's **VirtualDevice** path and assigning it to a device display group, then creating the capture display with `DEVICE_DISPLAY_GROUP` instead of relying only on `OWN_DISPLAY_GROUP`. AOSP's display service explicitly says that a device display group is created only when a trusted virtual display is associated with a real `VirtualDevice`; the flag by itself is not enough. A virtual-device group is the most plausible route to independent keyguard and power policy on Samsung firmware.

The second strong lead is separating “turn the physical panel off” from “lock the user.” Android 15 added `cmd display power-off <id>` and later `power-reset <id>` commands. scrcpy uses the corresponding privileged SurfaceControl display-power API and describes it as best effort and device-dependent. Ghost's previous experiment used `lockNow`, which intentionally engaged secure keyguard; that is a different path and cannot establish whether Samsung can keep a secondary compositor active while the panel is powered off.

No source found promises that an ordinary app-created virtual display will keep rendering through a **secure** Samsung keyguard. Recent scrcpy reports show the same family of failures on Android 15–17 and multiple OEMs. “Process alive,” “display exists,” or `state:ON` is not enough; advancing frame content and successful targeted input are required.

## What happened on this Fold7

Device: Samsung Galaxy Z Fold7 SM-F966U, Android 16/API 36, One UI 8.5, firmware `F966USQSCBZH3_OYNCBZH3`, tested with the cover display and no root or bootloader changes.

The verified unlocked configuration uses a private shell-owned virtual display with these resolved flags:

```text
OWN_CONTENT_ONLY 8
SUPPORTS_TOUCH 64
DESTROY_CONTENT_ON_REMOVAL 256
TRUSTED 1024
OWN_DISPLAY_GROUP 2048
ALWAYS_UNLOCKED 4096
TOUCH_FEEDBACK_DISABLED 8192
OWN_FOCUS 16384
STEAL_TOP_FOCUS_DISABLED 65536
total 97608 (0x17d48)
```

While unlocked, Ghost passed independent rendering, PNG/JPEG capture, display-targeted tap/long-press/swipe/key/text input, Chrome launch and address-bar input, physical-focus isolation, viewer mapping, hide/reopen, and repeated-capture tests.

For the lock/off test, the phone was securely locked with `lockNow`; it was physically off and dozing. After about 182 seconds the backend process and logical virtual display still existed, but the display reported `OFF`, the frame sequence stopped, frame age reached about 157 seconds, focus was absent, and the captured image was stale/black. This proves a power/keyguard policy failure, not a socket, ImageReader, or process-liveness failure.

Two firmware-specific experiments were rejected:

* Adding Samsung's hidden `VIRTUAL_DISPLAY_FLAG_HIDDEN_SPACE` kept some app activity alive and reported `ON`, but ImageReader frames were black. Naming the display `Ghost HiddenSpaceApp`, as Samsung's decompiled branch checks, did not change that result.
* Removing `OWN_DISPLAY_GROUP` and `ALWAYS_UNLOCKED` took the private never-blank path, but the activity did not produce a usable visible frame while securely locked.

The device placed the ordinary Ghost display in **display group 0** even though it retained `OWN_DISPLAY_GROUP`. A display-specific wake lock and a partial CPU wake lock did not change that assignment or the locked capture result. A direct `requestDisplayPower(..., ON)` call returned success but did not restore useful locked frames.

## Ranked research leads

### 1. Use a real VirtualDevice and its device display group

AOSP `DisplayManagerService` says that a trusted own-content display without its own group is automatically assigned `DEVICE_DISPLAY_GROUP` only when it is associated with a `VirtualDevice`. `LogicalDisplayMapper` then maps that display to the virtual device's non-default group. This matters because AOSP documents `ALWAYS_UNLOCKED` as valid only for displays that are not in the default group.

The current Ghost backend creates a normal virtual display directly. Passing `DEVICE_DISPLAY_GROUP` without a virtual device is explicitly logged by AOSP as having no device group to join. The meaningful experiment is therefore:

1. establish whether the shell identity on this Samsung build can create a `VirtualDevice`;
2. satisfy its Companion Device Manager association requirement, if Samsung enforces it;
3. create a trusted display through that device and inspect its group ID, `FLAG_ALWAYS_UNLOCKED`, keyguard state, frame sequence and input while the phone is securely locked;
4. close the virtual device and verify all displays, tasks and wake locks are gone.

This is a research lead, not an implementation recommendation yet. Android's public API requires `CREATE_VIRTUAL_DEVICE`, a companion association, and system-level policy. The AOSP shell manifest contains that permission in current Android branches, but Samsung may change grants or association checks. The same virtual-device owner also affects activity policy and input routing, so it could introduce restrictions Ghost does not currently have.

Sources:

* [AOSP Android 16 DisplayManagerService](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/display/DisplayManagerService.java) — trusted displays, own groups, and the `DEVICE_DISPLAY_GROUP` condition.
* [AOSP LogicalDisplayMapper](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/display/LogicalDisplayMapper.java) — default versus own versus device display-group assignment.
* [AOSP VirtualDeviceManager](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/companion/virtual/VirtualDeviceManager.java) — permission and association requirements.
* [AOSP virtual-device Binder interface](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/companion/virtual/IVirtualDeviceManager.aidl) — service-side enforcement and device/display ownership.
* [AOSP Shell manifest](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/packages/Shell/AndroidManifest.xml) — shell's privileged display and virtual-device permissions in the reference build.
* [Android VirtualDeviceManager reference](https://developer.android.com/reference/android/companion/virtual/VirtualDeviceManager).

### 2. Test display-power override without engaging keyguard

The previous lock test used `IWindowManager.lockNow`, which deliberately transitions the user into secure keyguard and doze. That should be compared with the Android 15+ display power override path:

```text
cmd display power-off 0
cmd display power-reset 0
```

The exact command availability and Samsung behavior must be checked on the device. AOSP's later change explains why `power-reset`, rather than `power-on`, is the correct way to remove an override after a power-off. scrcpy's server uses the hidden SurfaceControl display-power API and notes that the result depends on the device. This path may turn off the physical panel while leaving the user unlocked and the virtual compositor active; it may also be rejected or redirected by Samsung.

The future experiment must record keyguard visibility separately from physical panel state, compare frame sequence and a changing synthetic fixture for several minutes, and restore the display with `power-reset` even if the client dies. It must not use a screen-lock shortcut as a proxy for panel power-off.

Sources:

* [AOSP API and `cmd display power-off`](https://android.googlesource.com/platform/frameworks/base/+/fd8b5efc7fcd8cec1ea5dc4ccc6bc87d12db3875).
* [AOSP `power-reset` correction](https://android.googlesource.com/platform/frameworks/base/+/a8458cd441e838c29087077dd6510543f394ee63).
* [scrcpy device power documentation](https://github.com/Genymobile/scrcpy/blob/master/doc/device.md) — `--turn-screen-off`, display power, `--stay-awake`, and `--screen-off-timeout`.
* [scrcpy Controller.java](https://github.com/Genymobile/scrcpy/blob/master/server/src/main/java/com/genymobile/scrcpy/control/Controller.java) — delayed display-power handling and restoration.
* [scrcpy issue #5529](https://github.com/Genymobile/scrcpy/issues/5529) — virtual-display input after the physical phone dims is OEM-dependent.

### 3. Add Android 16's insecure-keyguard compatibility flag only as a stability experiment

An Android 16 scrcpy report on Samsung SM-F731B attributes buffer queue failures to missing `CAN_SHOW_WITH_INSECURE_KEYGUARD` and corrects a common mistake: its value is `1 << 5`, not the focus flag. This flag is about an **insecure** keyguard. It cannot legally bypass a secure PIN/pattern/password keyguard, so it is unlikely to solve this Fold7's secure-lock case. It may still prevent a separate Android 16 buffer error during transitions and should be tested independently from power behavior.

Source: [scrcpy issue #6438](https://github.com/Genymobile/scrcpy/issues/6438). Treat the issue's proposed fix as an implementation report, not an AOSP guarantee.

### 4. Use the “stay awake / keep active” path only when a panel-off requirement is relaxed

scrcpy documents three distinct behaviors:

* `--stay-awake` changes `stay_on_while_plugged_in` and only applies while charging;
* `--screen-off-timeout` delays the normal timeout;
* `--keep-active` periodically signals user activity and does not change global settings.

These can prevent the device from entering doze, but they do not turn off the physical panel while keeping secure keyguard out of the path. They are useful as a control condition and may meet a “do not sleep while plugged in” requirement, but they do not satisfy “screen physically off and securely locked.”

Sources: [scrcpy device documentation](https://github.com/Genymobile/scrcpy/blob/master/doc/device.md), [scrcpy virtual-display documentation](https://github.com/Genymobile/scrcpy/blob/master/doc/virtual-display.md), and Android's [PowerManager wake-lock reference](https://developer.android.com/reference/android/os/PowerManager).

### 5. Reuse a Samsung DeX / desktop-managed display rather than a generic app display

Samsung's own DeX path has system integration that a generic Shizuku-created display lacks. Open-source projects demonstrate two relevant directions:

* [Dextop](https://github.com/NarYuki/Dextop) reports Fold7 compatibility on Android 16 / One UI 8 and supports Shizuku or other privileged runtimes. Its compatibility claims are device/firmware-specific and should be audited against the exact Fold7 build.
* [LocalDex](https://github.com/sam1am/localdex) documents a hidden second display on One UI 8+, uses scrcpy's trusted display, and explains the Android 16 windowing workaround. Its setup intentionally relies on wireless debugging, so it does not meet Ghost's no-Wi-Fi goal by itself.

These projects suggest Samsung's managed desktop stack can obtain behavior that ordinary virtual-display creation cannot. They do not prove that an invisible, capture-to-ImageReader, Shizuku-only display can borrow the same power policy. A future research branch should inspect their display flags, group IDs, power handling and lifecycle rather than copying their UI or wireless-ADB transport.

### 6. Investigate capture-path blacking separately from compositor power

The black image could be caused by the display being stopped, by a Samsung blackout layer, or by a SurfaceFlinger buffer path that stops delivering to ImageReader. AOSP says detaching a virtual display's backing surface has an effect similar to turning its screen off. SurfaceFlinger also has explicit virtual-display power-state handling in Android 16. A future diagnostic should therefore compare:

* ImageReader frame sequence and buffer timestamps;
* a SurfaceControl capture of the same logical display, if the shell can call it safely;
* SurfaceFlinger layer/dump state and buffer-queue errors;
* a synthetic full-screen fixture versus protected/DRM content;
* whether an app window continues to animate while the output surface is black.

`SurfaceControl.captureDisplay` was probed once during this investigation and the probe process was killed before producing an image; that is evidence of an unsafe or incompatible probe, not evidence that capture is impossible. No further probe should be treated as successful without a bounded helper and cleanup path.

Sources: [Android 16 SurfaceFlinger](https://android.googlesource.com/platform/frameworks/native/+/refs/heads/android16-release/services/surfaceflinger/SurfaceFlinger.cpp), [Android ImageReader reference](https://developer.android.com/reference/android/media/ImageReader), and [Stack Overflow's historical ImageReader-black discussion](https://stackoverflow.com/questions/31687259/bitmap-from-imagereader-always-blank-when-trying-to-capture-screen). The Stack Overflow material is useful for failure patterns, but it predates Android 16 and is not authoritative for this device.

## What community implementations actually establish

The current scrcpy code creates a trusted new display with `OWN_DISPLAY_GROUP`, `ALWAYS_UNLOCKED`, `OWN_FOCUS`, and `DEVICE_DISPLAY_GROUP` on Android 14+. It is the best maintained public reference implementation for shell-owned new displays. It does not claim universal screen-off support.

Recent scrcpy reports are consistent with an OEM/framework boundary rather than a single Ghost bug:

* [#6787](https://github.com/Genymobile/scrcpy/issues/6787) reports virtual displays becoming an opaque black surface after the physical screen turns off on Android 15; `--stay-awake` avoids it on that device.
* [#5529](https://github.com/Genymobile/scrcpy/issues/5529) reports virtual-display mouse input failing after the phone dims on Android 14, while keyboard input remains functional.
* [#6974](https://github.com/Genymobile/scrcpy/issues/6974) reports blank virtual output after screen-off on Android 17.
* [#6654](https://github.com/Genymobile/scrcpy/issues/6654) reports lock-screen capture failure after an Android 16 update on OnePlus, while audio and the virtual display still exist.

Those reports do not solve Samsung's Fold7 case, but they rule out the assumption that a second wake lock or a different ImageReader format universally fixes it.

## Explicitly rejected as solutions

* **More CPU or screen wake locks:** they keep execution alive but do not move the display out of Samsung's default group or remove secure keyguard policy.
* **`lockNow` plus `ALWAYS_UNLOCKED`:** locking the physical user is exactly the transition under investigation; AOSP documents `ALWAYS_UNLOCKED` as valid only outside the default group.
* **Hidden Space flag and display-name tricks:** tested on this phone; output was black.
* **Removing group flags:** tested on this phone; no usable locked frames.
* **ADB TCP/localhost 5555:** unrelated to compositor power and violates the project's transport requirement.
* **Accessibility or physical-display fallback:** would change the isolation model and cannot provide a trusted independent headless display.
* **Root, bootloader unlock, or security weakening:** outside the project's constraints and unnecessary for a useful research result.

## Next research sequence (no implementation implied)

1. While the phone is unlocked, inventory `VirtualDeviceManager`, companion associations, shell permissions and Samsung's available virtual-device profiles without creating anything.
2. Check whether the Android 16 `cmd display power-off/reset` commands exist and document their permission and effect without running a persistent session.
3. Compare a short, reversible physical-panel power-off experiment against `lockNow`; capture keyguard state, display group, frame progression, and input separately.
4. Audit Dextop's exact Fold7 backend and flags against this firmware, looking specifically for a VirtualDevice, DeX-managed display, or power override.
5. If a VirtualDevice route is viable, design a disposable proof-of-concept outside Ghost first. Its acceptance criteria are fresh frames, changing fixture state and targeted input for at least five minutes under secure lock, followed by complete teardown.
6. Only after those results should Ghost's architecture be reconsidered.

## Source index

Primary framework sources: [DisplayManager flags](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/core/java/android/hardware/display/DisplayManager.java), [DisplayManagerService](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/display/DisplayManagerService.java), [LogicalDisplayMapper](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/display/LogicalDisplayMapper.java), [DisplayContent](https://android.googlesource.com/platform/frameworks/base/+/master/services/core/java/com/android/server/wm/DisplayContent.java), [KeyguardController](https://android.googlesource.com/platform/frameworks/base/+/master/services/core/java/com/android/server/wm/KeyguardController.java), [VirtualDeviceManager](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/companion/virtual/VirtualDeviceManager.java), [Shell permissions](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/packages/Shell/AndroidManifest.xml), and [SurfaceFlinger](https://android.googlesource.com/platform/frameworks/native/+/refs/heads/android16-release/services/surfaceflinger/SurfaceFlinger.cpp).

Reference implementations and reports: [scrcpy new-display source](https://github.com/Genymobile/scrcpy/blob/master/server/src/main/java/com/genymobile/scrcpy/video/NewDisplayCapture.java), [scrcpy virtual-display guide](https://github.com/Genymobile/scrcpy/blob/master/doc/virtual-display.md), [scrcpy device power guide](https://github.com/Genymobile/scrcpy/blob/master/doc/device.md), [Dextop](https://github.com/NarYuki/Dextop), [LocalDex](https://github.com/sam1am/localdex), [scrcpy #6438](https://github.com/Genymobile/scrcpy/issues/6438), [#6787](https://github.com/Genymobile/scrcpy/issues/6787), [#6974](https://github.com/Genymobile/scrcpy/issues/6974), and [#6654](https://github.com/Genymobile/scrcpy/issues/6654).
