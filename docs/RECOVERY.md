# Lifecycle and recovery

## Normal use

Start Shizuku, open Ghost Display, and tap Start. The app remembers that Ghost should run. The foreground host checks the backend every 15 seconds and reconnects when Shizuku becomes available. The host resumes desired operation after boot or an app update; it never opens the viewer automatically.

Closing or hiding the viewer releases its frame polling but leaves the headless display alone. Stop clears the remembered desired state, releases the display and wake locks, and asks Shizuku to remove the privileged service.

Use Stop before uninstalling Ghost so it can also remove its dedicated companion association and ownership record.

## If Ghost is unavailable

| Observation | Action |
| --- | --- |
| `running:false`, backend unavailable | Start Shizuku, then `ghostctl start`. |
| Missing Shizuku permission | Open the viewer and tap Start to grant access. |
| Shizuku was restarted | Allow the host's retry interval, then inspect status. |
| Backend process died | Expect a new display ID and a fresh workspace. Relaunch the desired app. |
| Frame is stale | Check `state`, `frameAgeMs`, current activity, and an actual screenshot. A static page need not produce new frames. |
| Agent coordinates are wrong | Read dimensions again, particularly after Rotate or recovery. |
| Android stopped the app explicitly | Open Ghost and start it again; force-stop suppresses normal background recovery. |

For unattended use, set Ghost to unrestricted battery use / exclude it from Samsung sleeping-app lists. Shizuku's own availability and permissions remain independent prerequisites. This project does not alter Developer Options, ADB trust, screen-lock security, or unrelated apps.

## What persists

The desired running state persists. The display object, its display ID, window focus, and temporary UI state do not survive backend death. App data remains in the same Android user. Recovery recreates one display, not a duplicate of a dead display.

The dedicated companion association and its atomic ownership record survive backend death and reboot. Ghost reuses that association on recovery and removes it on explicit Stop. The record is shell-owned at `/data/local/tmp/ghost-display/association-v1.json`; do not delete it while an association exists, because it identifies the association Ghost is allowed to remove. Never use a command that removes all companion associations. If an ownership/profile mismatch is reported, inspect it rather than borrowing an unrelated association.

There is no promise of unlimited uptime: reboot, Shizuku loss, explicit force-stop, firmware policy, and OS resource reclamation are real lifecycle boundaries. The measured device behavior is recorded in `TEST_RESULTS.md`.
