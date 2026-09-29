# Working with Ghost

## Operate

Read [docs/AGENT_PROTOCOL.md](docs/AGENT_PROTOCOL.md) for concurrent human use,
remote access, recovery, screenshot privacy and neutral acceptance testing.
For Artemis integration, also read [integrations/artemis/README.md](integrations/artemis/README.md).

1. **Start:** `ghostctl start`. Shizuku must already be available.
2. **Inspect:** `ghostctl status --json`. Read the live `displayId`, dimensions, power state, and health fields. Never assume an ID persists across recovery.
3. **See:** `ghostctl screenshot --out /sdcard/Download/ghost.png`, or use the PC wrapper with a local output path.
4. **Act:** Launch, tap, swipe, type, or send keys through `ghostctl`. Coordinates refer to full Ghost pixels. Rescale coordinates from reduced images.
5. **Verify:** Capture another frame and inspect the expected change. A command returning `ok` means the operation was accepted; verify the app's response visually.
6. **Recover:** If unavailable, start Shizuku, then `ghostctl start`. Inspect the new display ID. Backend recreation does not preserve all transient app state.
7. **Stop:** `ghostctl stop` when the user is finished. Hiding the viewer does not stop Ghost.

Use `ghostctl viewer` only when the user wants to see Ghost on the physical phone. No Accessibility dependency, physical-display fallback, global clipboard substitution, or localhost ADB 5555 workaround is needed.

## Develop

- Keep package `com.vertex.ghost` and the shell-owned Shizuku UserService architecture.
- Preserve display-targeted input. Do not route failed input to display 0.
- Resolve hidden framework constants on the device; verify their effects with captures and focus/power dumps.
- Keep one canonical display configuration. Changes to flags, power, input, capture, or lifecycle require real-device regression checks.
- Read `docs/ARCHITECTURE.md`, `docs/TEST_RESULTS.md`, and `docs/DEVELOPMENT.md` before changing core behavior.
- Use the existing signing key for updates. Never commit signing material, app backups, or full phone dumps.
- The smoke test starts a fresh session and opens a test activity on the physical display; run it only on an unlocked development device.
- Use `./gradlew clean assembleDebug` and verify the produced APK. CI compilation does not prove device behavior.
