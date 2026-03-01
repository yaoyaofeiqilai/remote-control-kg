# Session Handoff (2026-03-01)

First action when resuming this repo: run the pending audio verification test before any new code changes.

## Sleep Resume Reminder

When you come back, please test first:

1. Open admin terminal in project folder.
2. Run:
   - `set RC_AUDIO_DEVICE_INDEX=29`
   - `start.bat`
3. Connect from tablet and collect these logs:
   - `[WebRTC] offer received ...`
   - `[Audio] loopback ready: mode=input, device=立体声混音 ...`
   - `[Audio] WebRTC track capture_ready=True`
   - `[WebRTC] answer sent ...`
4. Confirm whether tablet can hear PC audio.

## What Changed In This Session

### Backend WebRTC / Audio (`src/remote_control/server_app.py`)

- Fixed WebRTC sender conflict:
  - replaced incorrect `await transceiver.sender.replaceTrack(...)` with sync call.
  - prevents: `Track already has a sender`.
- Added sounddevice compatibility for older runtime (`sounddevice==0.4.7`):
  - detect that `WasapiSettings(loopback=True)` is unsupported.
  - fallback path now prefers capturable input devices.
- Reworked audio capture candidate selection:
  - new `_build_capture_candidates()` includes input devices.
  - prefers loopback-like input names (`stereo mix`, `loopback`, etc.).
- Updated capture open logic:
  - supports input-device capture mode (`mode=input`).
  - keeps WASAPI output loopback path only when runtime supports loopback flag.
- Improved diagnostics:
  - `/api/audio_info` now includes `max_input_channels`.
  - `/api/audio_info` now includes `wasapi_loopback_param_supported`.
  - loopback ready log now prints capture mode and device.

### Local Sanity Checks Already Done

- `python -m py_compile src/remote_control/server_app.py` passed.
- `import remote_control.server_app` passed.
- Local `SystemAudioTrack` probe succeeded:
  - `capture_ready=True`
  - selected `立体声混音 (Realtek HD Audio Stereo input)`

## Current Risk / Pending Validation

- Need real tablet end-to-end confirmation that audio is actually audible remotely.
- If still silent after `capture_ready=True`, next step is browser-side audio autoplay/unlock and track stats inspection.

## Working Tree State

- There are intentional uncommitted changes in multiple files.
- Do not auto-revert existing modifications.
