# Session Handoff (2026-03-03A)

## Current User Goal

- Keep full resolution and high quality (no quality compromise).
- Reach stable 60 FPS on mobile browser with low latency.
- Keep startup simple: only run `start.bat`, encoder path auto-selects.

## What Was Completed In This Session

1. Freeze / reconnect path hardened on frontend.
- File: `static/app.js`
- Freeze watchdog no longer treats `bytesReceived` growth as "video is fine".
- Uses decoded-frame progression (`framesDecoded` / `framesPerSecond`) first.
- Result: reconnect now triggers correctly when stream is flowing but decode is stuck.

2. Capture + send hot-path performance tuning (no quality reduction).
- File: `src/remote_control/server_app.py`
- DXGI defaults changed to higher-throughput mode:
  - `RC_DXGI_CAPTURE_FPS` default `120`
  - `RC_DXGI_OUTPUT_COLOR` default `BGRA`
- Frame pump timing switched to `perf_counter()` next-tick scheduler to reduce drift.
- `ScreenVideoTrack` now reuses `VideoFrame` when frame pointer is unchanged, lowering per-frame conversion overhead.
- Added `RC_WEBRTC_START_BITRATE_KBPS` (default `24000`) while keeping max bitrate policy.

3. H264 encoder fallback logic made robust and non-disruptive.
- File: `vendor/py312/aiortc/codecs/h264.py`
- Added stronger AMF/MF option sets for mobile decode compatibility (shorter GOP + repeated headers).
- Added runtime failed-encoder blacklist:
  - if `h264_nvenc` / `h264_qsv` fails once, it is blacklisted for current process lifetime.
  - avoids repeated re-init churn on reconnects.
- Added env-configurable encoder order:
  - `RC_WEBRTC_H264_ENCODER_ORDER`

4. Startup behavior aligned with user request ("just run start.bat").
- File: `start.bat`
- If user does not set encoder order manually, default order is now:
  - `h264_nvenc,h264_qsv,h264_amf,h264_mf,libx264`
- This keeps NVENC first by default, auto-falls back when unavailable, no extra launch args required.

## Latest Runtime Observations

- On battery / power-saving state, runtime may show:
  - `CUDA_ERROR_NO_DEVICE` for NVENC init.
- This indicates process cannot access a CUDA-capable NVIDIA device at runtime.
- In that state, expected behavior is automatic fallback to `h264_amf` / `h264_mf`.
- NVENC path was **not removed**; it remains first in default order.

## Critical Reminder For Next Session

- First action next session: **test this exact encoder auto-selection change**.
- Required test matrix:
  1. Start with only `start.bat` while on battery state.
  2. Verify fallback path is stable (no repeated NVENC/QSV init spam on reconnect).
  3. Plug in / switch to high-performance state, restart with `start.bat`.
  4. Verify whether encoder returns to NVENC automatically.

## Required Data To Collect During Next Test

Run and paste:

```powershell
$base='http://127.0.0.1:5000'
(Invoke-WebRequest -UseBasicParsing "$base/api/info").Content
(Invoke-WebRequest -UseBasicParsing "$base/api/video_health").Content
```

Collect once after initial connect, and once right after any reconnect/freeze event.

## User Preference Reminder

- Do not leave server running in background after assistant-side tests.
- User starts server manually with `start.bat`.
