# Synthetic screen-off evidence

Captured September 17, 2026, during an isolated VirtualDevice experiment on the Fold7. No personal app content is included.

- `samples.json`: all twelve timed fixture / keyguard / screen-state observations, ending at 331.83 seconds.
- `before.png`: empty field and zero taps during the locked/off interval.
- `after-330-seconds.png`: fresh text and a tap applied after the interval; visually inspected.
- `extended-input.png`: long press, scroll, and Delete while still locked/off; visually inspected.
- `final-input.json` and `extended-input.json`: corresponding fixture state.
- `panels-four-minutes.json`: direct physical-panel states during the interval.

The samples are periodic, not a continuous recording. The screenshots alone do not show the physical phone's lock state; interpret them with the observations and [experiment log](../../EXPERIMENTS_2026-09-17.md). This is proof of concept evidence, not a production APK certification.
