# Session Handoff (2026-03-02F)

## Current User Goal

- Keep full resolution and high quality (no quality compromise).
- Reach stable 60 FPS on tablet browser with low latency.
- Continue from current repo state after user reboots PC and enables GPU.

## Completed In This Session

1. Removed remaining server-side FPS clamp behavior
- `ScreenVideoTrack.recv()` no longer caps send rate to `capture_fps + 1`.
- Sender cadence now follows requested WebRTC FPS directly.

2. Raised quality / bitrate defaults for quality-first mode
- Default quality now `95` (`RC_QUALITY` env supported).
- Auto bitrate defaults raised and capped to `80000 kbps`.
- High-res/high-fps auto-bitrate path aggressively reserves bandwidth.

3. Improved DXGI capture runtime behavior
- Added independent `dxgi_capture_target_fps` (`RC_DXGI_CAPTURE_FPS`, default `120`).
- DXGI start/reconfigure now uses max(requested_fps, dxgi_capture_target_fps) within max cap.
- `/api/info` now exposes `dxgi_capture_target_fps`.

4. WebRTC SDP H264 negotiation updates (mobile decode compatibility)
- H264 `fmtp` now includes `max-fs` and `max-mbps`.
- `profile-level-id` is rewritten to `42e0xx` with cap at level `4.2` (`42e02a`) for broader browser/device compatibility.
- Added answer fmtp debug log:
  - `[WebRTC] answer video fmtp: ...`

5. Added video-side diagnostics pipeline
- New endpoint `/api/video_health`.
- New Socket.IO event `video_client_stats` from frontend to server.
- Tracks client decode stats:
  - `frames_per_second`, `decode_ms`, `frames_decoded`, `frames_dropped`, `jitter_ms`, `packets_lost`, `bytes_received`.

6. Frontend cache bust
- Static version bumped to `v12` in `templates/index.html`.

7. Vendor aiortc stability/perf changes persisted from this session chain
- `h264.py`: raised `MAX_BITRATE` to `80 Mbps`.
- `rtcpeerconnection.py`: swallow close-race `InvalidStateError("... closed")` during async connect.

## Latest Verified Runtime Observation (User-Reported)

- Server info:
  - `capture_fps`: ~54
  - `webrtc_fps`: 60
  - `quality`: 95
  - `webrtc_bitrate_kbps`: 80000
  - `video_encoder_effective`: `h264_mf`
  - `video_hw_encoders_available`: `["h264_mf"]`
- Video health:
  - `frames_per_second`: 34
  - `decode_ms`: ~12.7
  - `frames_dropped`: 0
  - `packets_lost`: 0

Interpretation:
- Network is not the primary bottleneck.
- Current hard bottleneck is video encode pipeline throughput (currently `h264_mf` path).

## Critical Open Issue

- At `2560x1600`, quality `95`, and target `60 FPS`, stream remains around `~34-35 FPS`.
- With only `h264_mf` available, sustained true 60 is unlikely on this machine profile under current constraints.

## Next Step After User Reboot (High Priority)

1. Confirm hardware encoder availability immediately after startup:
```powershell
curl http://127.0.0.1:5000/api/info
```
Required fields:
- `video_encoders_available`
- `video_hw_encoders_available`
- `video_encoder_effective`

2. Connect tablet and capture runtime health:
```powershell
curl http://127.0.0.1:5000/api/video_health
```
Required fields:
- `capture_fps`
- `client_stats.frames_per_second`
- `client_stats.decode_ms`

3. Paste server log line:
- `[WebRTC] answer video fmtp: ...`

4. Decision branch:
- If `h264_nvenc` / `h264_qsv` / `h264_amf` appears:
  - switch encoder preference to that path and re-test 60 FPS.
- If still only `h264_mf`:
  - server-side encode throughput remains limiting factor; continue with GPU encoder enablement path.

## Files Changed In This Session Chain

- `src/remote_control/server_app.py`
- `static/app.js`
- `templates/index.html`
- `vendor/py312/aiortc/codecs/h264.py`
- `vendor/py312/aiortc/rtcpeerconnection.py`
- `SESSION_HANDOFF_LATEST.md`
- `SESSION_HANDOFF_2026-03-02F.md`
