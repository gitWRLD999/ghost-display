# Validation — October 12, 2026

The broader agent checks pass, and a fresh Android 16 emulator exercised the real
Ghost backend and fixture. **These are separate from the September Fold 7 tests.**
The physical phone had no USB ADB connection; Tailscale responded, but authenticated
Termux SSH was not enrolled on the PC. No new Samsung device acceptance is claimed.

## Local and protocol tests

| Suite | Result | What actually ran |
| --- | --- | --- |
| Bridge, transport and Artemis contract | 63 passed, zero skips | Bounds, stale observations, budgets, failures, cancellation, concurrency, full PNG decode, actual pinned manifest/models/observation/wire code. |
| MCP action layer | 10 passed, zero skips | MCP 1.29 client/server memory streams, pinned action server/session, real schemas and decoded JPEG blocks; simulated device and unrelated runtime imports. |
| Device diagnostic parsing | 6 passed | Folded-panel OFF conditions, missing/unknown diagnostics, focus parsing and exclusion of unrelated phone text. |
| Android build | Passed | Updated fixture compiled with Gradle 8.13, JDK 21 and SDK 36; APK v2 signature verified against the existing preview certificate. |

Total automated checks: **79 passed**. `pip check` found no broken dependencies.
MCP emits a nonfatal unresolved `lifespan` annotation warning; making all warnings
fatal prevents its setup. Complete Artemis startup, provider/model tasks, web
mirroring and raw-ADB bypass closure are still outside this verification.

The tests fixed stale observations after failed/cancelled readiness, unsafe action
budget types, sequences changed by their caller during execution, subprocess-start
errors, incomplete PNG acceptance and cancellation during encoding. A newly rendered
display with `inputHealth=untested` now permits its first targeted input; malformed
health values and absent frames remain blocked.

## Real Android emulator checks

Fresh API 36 Google Play x86_64 image; headless, no account sign-in, no snapshots,
2 GB guest RAM and two CPU cores. The installed APK's `GhostBackendMain` ran through
the explicit development-shell entry point as UID 2000. **This did not exercise
Shizuku authorization, the foreground host's automatic recovery, or the native viewer.**

| Check | Result |
| --- | --- |
| Display ownership/configuration | Shell UID, 1200×1920 at density 320, flags 128328, actual VirtualDevice, non-default display group. |
| Neutral fixture input | ASCII insertion, Delete, tap, long press and scroll passed, with real PNG captures and app-private fixture records. |
| Primary focus | InputDispatcher and WindowManager kept focus on display 0 through the action checks. |
| Scaled JPEG capture | 12 decoded captures at width 800; mean 346.33 ms, maximum 375 ms in the normal-screen run. |
| Short normal-screen sampling | Completed 90-second sampling window; seven successful samples, advancing fixture clock and real changing frames. |
| Fixture lifecycle regression | Twenty samples retained the current fixture's text after a second fixture was opened. Back resumed the previous fixture and its clock/state. |
| Primary screen locked/off | Fixture actions and 12 JPEG captures passed. Five samples between elapsed 22.84 and 96.22 seconds showed keyguard, primary panel OFF/OFF and Ghost ON; fixture clock advanced 74 seconds. |
| Requested 330-second lock/off run | **Interrupted, not passed.** Host available RAM fell to 1.87 GB; the emulator was stopped at the configured 2 GB safety floor. |
| Explicit Stop/cleanup | No running Ghost display, no display wake lock, zero companion associations and no ownership marker; the test emulator was shut down. |

Machine capture checks were accompanied by visual inspection of the neutral fixture.
Samples do not provide continuous proof of panel state between observations. The
emulator cannot establish Samsung power management, fold/unfold behavior or overnight
persistence. The existing [Fold 7 results](TEST_RESULTS.md) retain their original dates.

The first emulator Start returned `ghost_association_not_created`; the dedicated
association appeared afterward, and a subsequent Start reused it successfully. This
startup visibility/timing issue is recorded rather than hidden by a weaker display
fallback. No core display flags, power behavior or association creation code changed.

The fixture failure found during testing came from an older hidden activity continuing
to write the same display's result file. Its timer now pauses/resumes with activity
lifecycle. The modified fixture was rebuilt, installed with matching signature, and
the repeated-activity regression was checked on the emulator. It has not been installed
or regression-tested on the Fold 7. The published September preview APK remains unchanged.

Curated measurements: [emulator-summary.json](assets/validation-2026-10-12/emulator-summary.json).
Raw phone dumps, local paths, host keys and captures of unrelated apps are excluded.
Reproduce focused device checks using [DEVICE_CHECKS.md](DEVICE_CHECKS.md).

## Public repository review

Both original Git commits and all 70 unique text blobs were scanned for credentials,
private keys, personal paths and network identifiers. All eight existing PNGs were
visually reviewed; they contain neutral fixture, calculator or public Wikipedia
content and no text/EXIF metadata. The existing release APK matches its published
checksum, contains no private assets/signing keys, and uses the documented generic
Android Debug certificate. New code and summarized evidence are reviewed separately
before publication. Signing material and raw evidence remain ignored.
