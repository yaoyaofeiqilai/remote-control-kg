# Session Handoff (2026-03-03B)

## Current User Goal

- Keep full resolution and high quality (no quality compromise).
- Reach stable 60 FPS on mobile browser with low latency.
- Keep startup simple: run only `start.bat`.

## What Was Done In This Session

1. Confirmed real bottleneck location with runtime telemetry.
- `capture_fps` stayed near `59~60`.
- `track_stats.recv_fps` and client decode FPS stayed lower (`~40~50`), so bottleneck is server send/encode path, not packet loss.

2. Kept and validated useful diagnostics/perf-safe changes in backend.
- File: `src/remote_control/server_app.py`
- `ScreenVideoTrack` scheduler uses `perf_counter` timeline.
- `/api/video_health` includes `track_stats` (e.g. `recv_fps`, `interval_ms`, `wait_ms`) for direct bottleneck attribution.
- WebRTC bitrate fields now exposed in `/api/info` and `/api/video_health`.

3. Kept stable H264 encoder robustness changes.
- File: `vendor/py312/aiortc/codecs/h264.py`
- Runtime failed-encoder blacklist remains (`FAILED_ENCODERS`).
- Env-configurable encoder order remains (`RC_WEBRTC_H264_ENCODER_ORDER`).
- Current stable NVENC option set is `preset p2/p3`, `tune ull`, `rc cbr`, `zerolatency=1`.
- `PACKET_MAX` is back to stable `1300`.

4. Added startup guard to prevent duplicate server processes.
- File: `start.bat`
- Added `:cleanup_stale_server` step before launch.
- It kills stale `python.exe` processes listening on `0.0.0.0:5000`.
- This addresses previously observed "multiple listeners on :5000" causing black screen / unstable behavior.

5. Reverted unstable experimental changes from this session.
- Removed pump-side prebuilt `VideoFrame` fast path experiment (caused instability/timeouts in this environment).
- Reverted aggressive packet/preset experiment that reintroduced black screen.

## Latest Verified Observations

- Duplicate listeners on `:5000` were observed before (`python` x2); this was confirmed to cause bad behavior.
- After cleanup and single-instance run, telemetry typically showed:
  - `capture_fps`: around `59~60`
  - `track_stats.recv_fps`: around `40~50`
  - `client_stats.frames_per_second`: around `41~48`
  - `decode_ms`: around `9~10`
- A short controlled local diagnostic run (`python server.py --dxgi`) returned:
  - `/api/info` HTTP 200
  - `/api/video_health` HTTP 200

## Current Risk / Open Issue

- Mobile black screen can still appear after repeated restart cycles if process state is bad.
- Main performance gap remains: send/encode side not yet sustaining true 60 FPS at full-res high-quality under dynamic content.

## First Steps Next Session (After Reboot)

1. Start server once via `start.bat` (single window only).
2. Confirm single listener:
```powershell
netstat -ano | findstr :5000
```
3. Collect health snapshots:
```powershell
$base='http://127.0.0.1:5000'
(Invoke-WebRequest -UseBasicParsing "$base/api/info" -TimeoutSec 3).Content
1..10 | % { (Invoke-WebRequest -UseBasicParsing "$base/api/video_health" -TimeoutSec 3).Content; Start-Sleep -Milliseconds 500 }
```
4. If black screen/timeout recurs, collect latest console logs from the server window immediately.

## User Preference Reminder

- User starts/stops server manually with `start.bat`.
- Do not leave server running in background after assistant-side diagnostics.
