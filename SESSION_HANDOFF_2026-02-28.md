# Session Handoff (2026-02-28)

This handoff records the latest verified state for the `remote-control` project so the next session can continue immediately.

## User Goals (Current)

1. Add remote audio return and keep A/V in sync.
2. Make tablet external keyboard input behave like native PC keyboard input.
3. Make tablet external mouse input behave like native PC mouse input.
4. Keep performance stable and avoid regressions.

## What Has Been Implemented

### Backend (`src/remote_control/server_app.py`)

- Added WebRTC audio track support:
  - `SystemAudioTrack(AudioStreamTrack)` with timestamped PCM output.
  - Audio track attach in WebRTC offer flow.
  - Audio codec preference set to OPUS.
  - Peer close cleanup for audio tracks.
- Added/updated diagnostics routes:
  - `/api/audio_info`
  - `/audio_info` (alias)
  - `/api/build_info`
- Added startup diagnostics output:
  - build tag
  - audio diagnostic URLs
- Added safer run option:
  - `allow_unsafe_werkzeug=True` in `socketio.run(...)` for this environment.
- Added audio device controls:
  - env var `RC_AUDIO_DEVICE_INDEX` (default `-1`).
  - candidate selection now prioritizes default output matching WASAPI endpoint and deprioritizes virtual outputs.
- Adjusted DXGI path:
  - avoid starting dxcam internal thread explicitly; use pull-style frame grab to reduce dxcam thread crash risk.

### Input Layer (`src/remote_control/input_sender.py`)

- Expanded key mapping support (function keys/navigation keys).
- Added `VkKeyScanW` based VK resolution fallback for improved key compatibility.

### Frontend (`static/app.js`, `templates/index.html`, `static/style.css`)

- WebRTC audio receiving path added:
  - audio transceiver, remote stream track handling.
  - audio element unlock/play flow for mobile browser policies.
- Added hardware keyboard forwarding improvements:
  - key normalization.
  - key state tracking and release-on-blur/pagehide.
  - repeat (`press`) flow support.
  - optional keyboard lock attempt for `Escape`/`Meta`.
- Added hardware mouse forwarding improvements:
  - pointer/button/wheel forwarding.
  - rAF-based relative move batching.
- Added fallback UI controls for system keys:
  - top-right `Esc` and `Win` buttons (`#system-shortcuts`).
  - virtual keyboard `Win` key.
- Added back-key forwarding fallback using history trap (`popstate -> Escape press`).
- Bumped static asset version in HTML to force refresh:
  - `style.css?v=20260228_4`
  - `app.js?v=20260228_4`

### Startup Script (`start.bat`)

- Dependency check now includes:
  - `sounddevice`, `aiortc`, `av`.

## Verified From User Logs

- Service is running latest build:
  - `构建标识: 2026-02-28-audio-input-v4`
- `/api/audio_info` is reachable and returns device list.
- Static assets request previously showed `v20260228_3`; code has now been bumped to `v20260228_4` to force fresh client script.
- dxcam thread crash appeared in logs before latest DXGI adjustment.

## Current Known Risk / Focus

1. Audio still may be silent if wrong output endpoint is selected at runtime.
2. Need to verify WebRTC audio negotiation is actually occurring on target device.
3. Need user confirmation that `v20260228_4` is loaded (to validate Esc/Win/repeat fixes are active).

## Required Next-Step Validation

1. Start server with forced Realtek WASAPI index from current diagnostics:
   - `set RC_AUDIO_DEVICE_INDEX=13`
   - run `start.bat` (admin).
2. On tablet, open page and confirm requests include:
   - `/static/app.js?v=20260228_4`
   - `/static/style.css?v=20260228_4`
3. Capture these server log lines during connection:
   - `[WebRTC] offer received ...`
   - `[WebRTC] answer sent ...`
   - `[Audio] loopback ready: ...`
   - `[Audio] WebRTC track capture_ready=...`
4. Retest:
   - long-press `Backspace`
   - `Esc`/`Win` top-right shortcut buttons
   - virtual keyboard `Win` key

## Working Tree State

There are uncommitted changes and they are intentional. Do not revert them automatically.

