# Agent operating protocol

Ghost is a second Android display on the same phone. See and control that display
with `ghostctl` while the human uses the physical display. It is not a separate
Android user: accounts, files, app processes and some single-instance tasks are shared.

## Establish a session

1. Select an explicit device/SSH endpoint. On PC, use the PowerShell wrapper or the
   [read-only Python probe](../integrations/artemis/probe.py). Never rely on the first
   ADB device in a list.
2. Run `status --json` before changing anything. If Ghost is stopped, use `start`
   only within the user's authorized session. Do not stop/recreate an active display
   merely to initialize a tool.
3. Confirm a positive `displayId`, `backendUid:2000`, positive dimensions,
   `state:ON`, `captureHealth:ready` and `inputHealth:ok`.
4. Capture a screenshot. Read only this frame for the next input. The display ID
   and dimensions are live values, not persistent constants.

## See, act, verify

1. Inspect the Ghost frame; identify the target and intended result.
2. Send one display-scoped action through `ghostctl`.
3. Capture again and verify the actual app response. `ok:true` proves command
   acceptance, not task completion. Do not infer success from a process exit alone.
4. Keep actions bounded. Stop on unexpected app transitions, loss of connection,
   stale geometry, denied permissions or an ambiguous command outcome.

CLI coordinates are full Ghost pixels. For a reduced image, scale x by
`displayWidth/imageWidth` and y by `displayHeight/imageHeight`. The Artemis adapter
instead accepts integer 0..1000 coordinates and handles the pixel conversion.

Never use unscoped `adb shell input`, ordinary ADB screenshots, Accessibility nodes
from display 0, global clipboard replacement or physical display fallback. Do not
open `viewer`, send power/volume keys, force-stop a shared app, modify phone settings,
or unlock the physical phone while the human is using it unless specifically asked.

Before launching a real app, consider whether it can reuse/move the human's task.
Start testing with `open-component com.vertex.ghost/.GhostTestActivity`. Captures of
real apps may contain personal data; keep them in ignored private directories and
review them before publication. Do not send messages, purchase items or take other
external actions without the user's authorization for those actions.

## Recovery and remote access

After recovery or rotation, discard coordinates and capture a new frame. A changed
backend PID or display ID means a new session identity even at the same dimensions.
Do not replay an action whose transport timed out; it might already have happened.
If Shizuku is unavailable, report that condition and use the authorized recovery
path. Avoid ADB 5555 or opening a public Ghost TCP listener.

Tailscale provides the private network route. Remote operation additionally needs
an authenticated Termux SSH shell and `rish` access to Shizuku. Use pinned host keys
and key authentication for agents. The local Ghost socket remains restricted to
shell/root/Ghost UID. Being reachable over Tailscale does not prove Ghost is ready.

Leave an existing Ghost session running when another operator/human still needs it.
Stop it when the user is finished or has requested cleanup.

## Five-minute neutral acceptance check

Use the dedicated Ghost fixture, without opening the native viewer or the old smoke
suite. Capture the fixture, tap its counter, long-press it, insert a neutral ASCII
phrase into its edit field, and scroll its list. Verify every result from fresh frames.
Record display ID/geometry/backend PID and command outcomes, without full phone dumps.

Let the human lock the physical phone themselves for the screen-off phase. Repeat
those Ghost actions, check the fixture clock advances, and independently inspect
display power state. A static screenshot alone does not prove continued execution.
Concurrent human use and screen-off tests are separate conditions; record each.

For Artemis work, read [the adapter status and bypass-channel requirements](../integrations/artemis/README.md)
before launching its runner. Current local tests are not a full phone/MCP/model-task
acceptance result.
