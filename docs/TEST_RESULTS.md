# Device verification

**Status: Ghost 1.1.0-preview.1 is installed and passes the short secure-lock / screen-off test.** The VirtualDevice approach is integrated into the Shizuku UserService. This is not a claim of indefinite persistence or compatibility with every app.

Additional agent/MCP and emulator checks are recorded in the [October 12 validation](VALIDATION_2026-10-12.md).
They do not replace or extend the physical Fold 7 measurements below.

The September 17 disposable probe established feasibility; its [historical results](EXPERIMENTS_2026-09-17.md) remain separate from the installed-backend results below.

Test platform: Samsung Galaxy Z Fold7 SM-F966U, Android 16 / API 36, One UI 8.5, firmware build F966USQSCBZH3. Tests performed September 15–18, 2026. The phone was folded, using its cover display. No root, bootloader change, lock-security change, or Accessibility service was used.

## Installed Ghost 1.1 verification — September 18

| Check | Result |
| --- | --- |
| Clean build and signature | Pass; versionCode 8, existing personal signing certificate verified, update installed without deleting app data. |
| Canonical display | Flags 128328; actual VirtualDevice with non-default group. Start refuses group 0. |
| Real-device smoke suite | All nine assertions passed: idempotent start, physical focus, unchanged physical text, targeted input, changed capture, Delete, dual-display isolation, repeated capture, health. |
| Secure lock / both panels OFF | Twelve samples passed over **339.68 seconds**, with virtual display ON throughout the samples. Physical panels each reported OFF / committedState OFF. |
| Real app action after interval | Samsung Calculator accepted Equals after the interval and the captured image visibly changed to **2,304,000**. Keyguard stayed showing and screen OFF at the final check. |
| Real browser under lock | Chrome Custom Tab rendered Wikipedia; targeted search text and Enter navigated to Virtual desktop. |
| Rotation under lock | Same display resized to 1920 × 1200, Chrome redrew correctly, and portrait resize retained the ID. |
| Focus after real-app work | InputDispatcher retained display 0 as focused display. |
| Automatic backend recovery | After deliberate process termination, unavailable at 3.36 s and running on a new display by 6.75 s. The same association was reused; exactly one VirtualDevice existed. This is one measured recovery, not a maximum-time guarantee. |
| Explicit Stop | Zero active VirtualDevices, no Ghost wake locks, owned association and marker removed; three pre-existing associations remained. |
| Restart after Stop | New display and dedicated association created successfully. |

The lock test sampled approximately every 30 seconds; it is not a continuous physical-panel recording. A static application's old frame timestamp alone is not a failure. Calculator's blinking cursor produced advancing frames during this run, and the final fresh action plus visual capture established useful output after the interval.

See [real app captures](SHOWCASE.md), [lock/off samples](assets/showcase/locked-off-samples.json), and [recovery samples](assets/showcase/recovery-samples.json). Native viewer touch/hide/reopen and Termux/rish were verified on the preceding build; those full interactions have not yet been repeated on 1.1. Fold/unfold and overnight endurance remain untested.

Personal preview APK SHA-256: `3877885bc290615d97496d8817b1954730d6ac9c4d2760fd4fc74e92d59be34a`.

## Earlier preview checks — September 15–17

| Check | Result | Evidence summary |
| --- | --- | --- |
| Private headless display | Pass | Shell UID 2000, owner `com.android.shell`, 1200 × 1920; no simulated-display overlay. |
| Idempotent start | Pass | Repeated start retained the same display ID. |
| Chrome on Ghost | Pass | Opened example.com, targeted address-bar input and Enter. |
| Physical focus isolation | Pass | WindowManager and InputDispatcher both retained top focus on display 0. |
| Independent text fields | Pass | Physical fixture retained `PHYSICAL`; Ghost received `Ghost input works`. |
| Touch and keyboard input | Pass | Fixture recorded one tap, one long press, scroll offset 964; DEL affected Ghost only. |
| PNG capture | Pass | Valid, visually checked before/after frames matched fixture changes. |
| Repeated JPEG capture | Pass | 12 captures at width 800: mean 370 ms, maximum 403 ms, including CLI/ADB overhead. |
| Native viewer | Pass | Portrait tap/text, landscape mapped tap/swipe, aspect-preserving display. |
| Hide / reopen viewer | Pass | Same display and retained text, counter and scroll state. |
| Termux / rish | Pass | Commands worked locally; apostrophe-containing text was preserved. |
| Backend recovery and stop | Not completed on this earlier build | Completed on the installed September 18 build in the table above. |

The first nine checks are exercised by `scripts/smoke.ps1`. Viewer and rish checks used the same device and synthetic fixture. Raw system dumps and personal browser content are deliberately not published.

## Historical ordinary-display failure — fixed by replacing the creation path

With the canonical flags **97608**, secure keyguard was showing and the phone was off/dozing. After approximately 182 seconds, the Ghost backend and display still existed, but the display reported OFF and capture had stopped advancing. Frame age reached approximately 157 seconds. Retaining a process and display ID did not satisfy ongoing rendering and input requirements.

The observed display group was 0 despite OWN_DISPLAY_GROUP and ALWAYS_UNLOCKED. Inspection of this device's display allocator and power behavior pointed to Samsung's group assignment overriding the requested independent power group.

Two targeted alternatives were tested and rejected:

- Samsung's Hidden Space flag reported ON and allowed some application activity, but captured frames were black. Changing the display name to the firmware's HiddenSpaceApp form also produced black frames.
- Removing the group/unlocked flags to use the private never-blank path left the activity without a usable visible frame while securely locked.

Neither workaround ships. Ghost 1.1 uses the association-backed VirtualDevice path instead. It does not disable keyguard, wake the physical display through a hidden fallback, or reduce device security. Frame counters and `state:ON` alone remain insufficient proof of successful capture.

## Not claimed

- Restarting Shizuku after a reboot without the user's existing starter setup.
- Surviving every Android force-stop, memory pressure, or manufacturer power policy.
- Dynamic unfolding/refolding or every third-party app's task model.
- Protected video, unrestricted Unicode, or an Accessibility-style UI tree.
- Release builds on other Android versions or OEM firmware; runtime uses hidden framework APIs.

Re-run the real-device checks after firmware updates, display-flag changes, or input/capture changes. CI builds and verifies an APK signature; it cannot verify these hardware behaviors.
