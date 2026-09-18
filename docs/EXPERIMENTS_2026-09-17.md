# Screen-off experiments — September 17, 2026

This log follows the research-only pass. The user subsequently authorized further experiments. Tests use disposable `app_process` helpers; the installed Ghost APK has not been replaced during this pass.

## Outcome

**The VirtualDevice probe passed the evening secure-lock / physical-screen-off acceptance test.** Twelve samples spanning 331.83 seconds all reported secure keyguard showing and screen OFF; new targeted touch and text then appeared in the captured image while those conditions remained true. Both physical panels were also checked directly and reported state OFF / committedState OFF. This is a measured proof of concept, not an installed Ghost fix or an indefinite-persistence guarantee.

## Findings

1. **Panel power-off is different from secure lock.** The phone exposes `cmd display power-off` and `power-reset`. A canonical private display (flags 97608) continued to render the synthetic fixture and accept text and taps while SurfaceFlinger reported both physical panels OFF and keyguard was absent. The physical-display override was guarded by a timed reset. This is useful diagnostic evidence, but an unlocked panel-off session does not meet the secure-lock requirement.
2. **The shell holds CREATE_VIRTUAL_DEVICE on this firmware.** Runtime inspection confirmed the grant rather than assuming it from AOSP.
3. **Local-only VirtualDevice is system-server-only.** `setLocalDeviceOnly(true)` is present but the service explicitly rejects it for shell UID. No permission or security setting was changed to bypass that restriction.
4. **A normal VirtualDevice can be created by shell.** A dedicated, self-managed test association using the app-streaming profile enabled the supported privileged API. It does not pair Bluetooth hardware or connect to a remote host. The experiment uses the shell's real UID and package attribution.
5. **The resulting display actually has an independent group.** The observed logical display was 8, virtual device 2, display group 5. These IDs are session-specific. The ordinary comparison display stayed in group 0.

## Details needed to reproduce the successful creation

The shell package context alone was insufficient: `getApplicationContext()` returned null in `app_process`, and its attribution did not initially identify the intended shell package. A context wrapper returned itself for application context and supplied shell UID 2000 with package `com.android.shell` as the attribution source and operation package. This describes the process's actual identity; it does not impersonate a system UID.

The probe constructed `VirtualDeviceManager` with the Binder service and that context, built `VirtualDeviceParams` with a name, `LOCK_STATE_ALWAYS_UNLOCKED`, and `localDeviceOnly=false`, then created a device with the dedicated companion association ID. It created the display through that **VirtualDevice**, using `VirtualDisplayConfig` with an ImageReader surface.

Requested flags: OWN_CONTENT_ONLY, SUPPORTS_TOUCH, DESTROY_CONTENT_ON_REMOVAL, TRUSTED, ALWAYS_UNLOCKED, TOUCH_FEEDBACK_DISABLED, OWN_FOCUS, STEAL_TOP_FOCUS_DISABLED, DEVICE_DISPLAY_GROUP. Combined value on this firmware: **128328 (`0x1f548`)**. OWN_DISPLAY_GROUP and Samsung HIDDEN_SPACE are absent.

The probe owns an RGBA ImageReader, continually closes acquired images, saves a synthetic capture every ten seconds, and holds bounded CPU/display wake locks. It automatically releases its VirtualDisplay, closes the VirtualDevice, releases the reader and locks, and exits after the selected duration (10–600 seconds). The temporary companion association is removed separately after all probes using it complete.

## Secure-lock acceptance

Secure keyguard was engaged at approximately 15:24:31 America/Chicago, followed by an explicit physical-display sleep key. Window policy reported keyguard showing and screen OFF. Power diagnostics showed physical group 0 dozing and virtual group 5 awake; global wakefulness remained Awake because a non-default group was awake. Global wakefulness alone must therefore not be used to decide whether the physical phone is off.

Initial locked checks passed: the fixture recorded two taps, appended text, a display-targeted Delete, and scroll offset 967. Captures showed the actual changing fixture. Chrome was subsequently launched on the virtual display while the phone remained securely locked; its example.com page rendered, and InputDispatcher retained focused display 0. The five-minute and teardown results are recorded below.

The ordinary display was kept running as a simultaneous comparison. Following secure lock, it transitioned to OFF and its sequence stopped at 452 while frame age continued increasing. The VirtualDevice display stayed ON and resumed frame delivery after browser navigation and relaunching the fixture. Thus both implementations were tested under the same keyguard/power conditions, not just in separate runs.

The first probe produced useful frames through its six-minute lifetime (last sample: elapsed 354303 ms, sequence 1034, frame age 388 ms). However, physical-screen state was ON at the final manual check, so this does **not** establish uninterrupted physical-off operation for five minutes. System power logs showed a call-related full wake lock at 15:29:45, close to that check. The helper reported successful normal cleanup.

A second VirtualDevice was then created while keyguard was already showing and the physical screen was OFF. It successfully created a new display (9) in another independent group (6), and the fixture rendered without unlocking the phone. A strict 330-second acceptance script passed its 0- and 30-second lock/off samples but rejected the 60-second sample because the physical screen had turned ON while keyguard remained showing. A further call-related system wake lock occurred at 15:31:48. These interruptions are recorded as invalid duration tests, not successful five-minute results or virtual-display failures.

PowerGroup logs subsequently identified both physical wake events explicitly as `reason=application`, with `TURN_ON:handleTurnScreenOn::com.samsung.android.incallui`. Separately, `display_group_added` appeared in a global PowerManager wake message. That global event must not be described as proof of a physical-panel wake.

The second probe was deliberately killed at 15:35:48 to test Binder-death cleanup. `dumpsys virtualdevice` reported zero active devices; display 9 and its active experiment wake locks disappeared. The pre-existing Ghost display 6 remained. This verifies process-death cleanup for the probe, not Ghost foreground-service recovery.

A third probe (display 10, group 7) continued rendering for its full ten-minute lifetime, reaching sequence 1768 with a frame age of 489 ms at elapsed 599214 ms, then reported normal cleanup. Its strict duration check passed through 150.9 seconds but observed the physical screen ON at 181.06 seconds; it is therefore another invalid five-minute off test. A check performed immediately after a sleep key also caught the ON-to-OFF transition, establishing the need to allow the screen to settle before timing.

After the phone restarted, the disposable association was still present while no VirtualDevice remained. A fresh evening test started with a new device/display, demonstrating that association persistence and live display persistence are different.

### Evening acceptance: passed

The fresh probe started at approximately 21:31:20 America/Chicago with VirtualDevice 1, logical display 7 and group 5. Secure keyguard was requested, the physical display was put to sleep, and the test waited three seconds for the screen transition before starting its timer.

| Check | Observed result |
| --- | --- |
| Timed lock/off checks | All 12 samples passed, from 0.15 to 331.83 seconds, approximately 30 seconds apart. |
| Fixture progress | Live-seconds values advanced from 5817 to 6149 during the timed interval. |
| Physical panels | Both reported OFF and committedState OFF at direct checks during the interval and after final input. |
| Fresh post-interval input | Tap count changed from 0 to 1; text became `PASS-AFTER-330-SECONDS`. |
| Visual capture | Final PNG visibly showed the new text, tap count 1, and live-seconds value 6159. This was not a black frame. |
| Extended input under lock | Long-press count 1, scroll offset 1356, and Delete changed the text to `PASS-AFTER-330-SECOND`; another PNG confirmed these changes. |
| Physical focus | InputDispatcher focused display remained 0 after extended input. |
| Probe frame health | Last pre-cleanup sample: elapsed 425793 ms, sequence 1379, frame age 512 ms, display state ON. |
| Process-death cleanup | Deliberate termination at 21:38:27 removed the VirtualDevice, display, and active probe wake locks. |
| Association cleanup | Only the dedicated shell association was removed; the three pre-existing companion associations remained. |

The duration check sampled every 30 seconds; it does not prove millisecond-by-millisecond panel state. No matching physical wake event was found in the filtered power wake log for this evening test window. This is strong evidence for the short acceptance interval, not an overnight endurance result.

The phone was left securely locked with its screen OFF. No display-power override remained from the earlier panel-only experiment. The installed Ghost APK was not replaced. The successful association, probe display and process were temporary and have been removed.

Synthetic evidence is preserved in [the evidence directory](assets/screen-off-2026-09-17/README.md). Raw dumps and browser captures stay outside the project.

## Practical limits

This establishes an architectural lead, not yet an installed Ghost fix. Integration must handle association ownership and orphan recovery, correct shell attribution, VirtualDevice teardown, foreground-service recovery, viewer rotation, third-party app policy, and real-device regression. A successful app-streaming VirtualDevice does not guarantee every app is eligible to run on it.

### Integration gates

1. Move the proven creation path into the existing Shizuku UserService without changing socket/Binder caller checks or routing failed input to the physical display. ADB shell success is not yet proof that the Shizuku lifecycle is correct.
2. Explicitly own the app-streaming association lifecycle. Persist the chosen identity outside transient display state, verify its owner/profile before reuse, and remove only an association Ghost created. An association survives a reboot even though the VirtualDevice does not.
3. Expose actual device ID, display group, display state and frame age in health diagnostics. Fail visibly when the separate device group was not obtained; do not substitute a black capture and report success.
4. Preserve capture ownership and cleanup order. Recreate tasks and refresh clients' display IDs after Binder death rather than promising the old activity state survived.
5. Recheck secure-lock/off behavior, focus isolation, all input types, viewer hide/reopen, rotation, restart/stop, and association cleanup using the installed backend. Record a longer unattended trial separately from the short acceptance test.
6. Test fold/unfold and representative third-party applications separately. Chrome success does not establish compatibility with secure video, banking applications, or every activity policy.

No APK build or installation was performed for these probes. The portable experiment build completed successfully with SDK 36 and the local JDK; the verifier passed PowerShell parsing and its panel-state regex matched both physical panels on this device.

Raw diagnostics and browser screenshots remain local because they can contain unrelated device or browser information. Only synthetic screenshots and summarized results are suitable for the private project repository.
