# GYUVIS 자세 알림

This is a rule-based posture reminder, not a medical assessment. It runs
MediaPipe Pose locally against the webcam feed and never stores or transmits
frames. Only a warning event is sent to the local GyuNexus Core API.

## Setup

1. Copy `.env.example` to `.env` and set `POSTURE_API_TOKEN` to the same value
   as Core's `GYUVIS_POSTURE_API_TOKEN`.
2. Install the isolated dependencies with the active virtual-environment Python:

   ```bash
   python -m pip install -r posture_alert/requirements.txt
   ```

3. Sit naturally in your normal screen-facing posture and run
   `python -m posture_alert.calibration`. It records only normalized landmark metrics for five
   seconds in `data/posture_baseline.json`.
4. Run `python -m posture_alert.main`.

When `BAD` persists for `POSTURE_BAD_DURATION_SECONDS` (12 seconds by default),
the local Core API speaks `GYUVIS_POSTURE_WARNING_MESSAGE` through the existing
Edge TTS configuration. Normal posture, warning-level movement, or missing
landmarks resets the bad-posture timer.

At the same confirmed-warning point, every connected Windows screen flashes
red four times by default. It is click-through, so it does not block mouse or
keyboard input. macOS supports a best-effort single-display flash but cannot
offer the same click-through/multi-display behavior through Tk; a failure is
logged and does not stop posture detection. Set `POSTURE_SCREEN_ALERT_ENABLED=0`
to disable it. On macOS, grant Camera access to the terminal/Python app in
System Settings → Privacy & Security → Camera.

## Tuning for an angled/side webcam

- If ordinary typing warns too easily, increase `POSTURE_FORWARD_HEAD_DELTA`
  from `0.18` to `0.24` and/or `POSTURE_HEAD_DOWN_ANGLE_DELTA_DEGREES` from
  `16` to `20`, then recalibrate.
- If a clearly lowered head does not warn, lower those values gradually and
  recalibrate after changing camera position.
- Keep the webcam and monitor position fixed after calibration.
- `POSTURE_FRAME_SKIP=3` at 640x480 keeps CPU use modest. Raise it to `4` or
  `5` if necessary, but do not lower `POSTURE_BAD_DURATION_SECONDS` to make up
  for a slower camera loop.
