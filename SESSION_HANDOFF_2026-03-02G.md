# Session Handoff (2026-03-02G)

## Current User Goal

- Keep full resolution and high quality (no quality compromise).
- Reach stable 60 FPS on tablet browser with low latency.
- Continue after possible reboot during GPU driver update.

## Completed In This Session

1. Restored and validated previous baseline context
- Recovered prior handoff state from `SESSION_HANDOFF_2026-03-02F.md`.
- Confirmed bottleneck pattern with user test data:
  - capture side near ~55 FPS
  - client render around ~36-37 FPS
  - no packet loss, decode time ~11-13 ms

2. Captured and interpreted user-provided runtime metrics
- `/api/info` showed only `h264_mf` + `libx264` initially.
- `/api/video_health` showed client decode not bottleneck.
- Confirmed encode pipeline remained primary limiter.

3. Handled DXGI regression caused by forcing Python to dGPU
- Temporary GPU preference override for `python.exe` caused DXGI init failure loop on this machine.
- Reverted GPU preference keys for:
  - `C:\Program Files\Python312\python.exe`
  - `E:\python\python\python.exe`
- Added DXGI hard-fail handling and dxcam teardown compatibility patch in `server_app.py`:
  - patch missing `is_capturing` path in dxcam stop/release lifecycle
  - detect unsupported DXGI feature-level errors and disable repeated retry spam
  - keep MSS fallback stable

4. Upgraded vendor AV stack to unlock hardware encoder probing
- Replaced vendored `av` package from 12.3.0 to 16.1.0 under `vendor/py312`.
- After upgrade, probe shows availability of:
  - `h264_nvenc`, `h264_qsv`, `h264_amf`, `h264_mf`, `libx264`

5. Fixed encoder option compatibility in vendored aiortc H264 codec
- Updated `vendor/py312/aiortc/codecs/h264.py`:
  - removed global `tune=zerolatency` (breaks NVENC init)
  - kept `tune=zerolatency` for `libx264` only
  - added per-hw-encoder option blocks for `h264_nvenc`, `h264_qsv`, `h264_amf`
  - set `h264_qsv` pix_fmt to `nv12`

6. Verified new runtime behavior locally
- `/api/info` now reports preferred/effective encoder capability includes `h264_nvenc` family.
- Practical selection fallback observed on this host:
  - `h264_nvenc` fails due NVIDIA driver API requirement
  - `h264_qsv` unavailable on current platform
  - encoder falls through to `h264_amf` and works

## Latest Verified Runtime Observation

- User test before AV upgrade (still useful baseline):
  - `/api/info`: `capture_fps` ~55, `video_encoder_effective`=`h264_mf`
  - `/api/video_health`: client `frames_per_second` ~37, `decode_ms` ~11.7, `packets_lost`=0
- Local post-upgrade probe:
  - `video_encoders_available`: now includes `h264_nvenc/h264_qsv/h264_amf/h264_mf/libx264`
- Local encoder init logs indicate:
  - NVENC requires newer driver: minimum 570.xx
  - Current installed driver seen earlier in session: 566.26

## Critical Open Issue

- True 60 FPS at 2560x1600 still not confirmed after AV upgrade.
- NVENC path is blocked by current NVIDIA driver version (<570).
- Need real device retest after driver update.

## Next Step (After Reboot / Driver Update)

1. Update NVIDIA driver to 570.xx or newer.
2. User starts server manually with `start.bat` (per user preference).
3. Connect tablet and run 20-30s.
4. Collect and paste:
```powershell
$base='http://127.0.0.1:5000'
(Invoke-WebRequest -UseBasicParsing "$base/api/info").Content
(Invoke-WebRequest -UseBasicParsing "$base/api/video_health").Content
```
5. Optional quick GPU encode check while streaming:
```powershell
nvidia-smi --query-gpu=utilization.gpu,utilization.encoder,utilization.decoder --format=csv -l 1
```

Decision target:
- If NVENC becomes active and client FPS reaches ~60, keep this path.
- If still below target, tune encoder preference/order and bitrate/fps caps with new metrics.

## User Preference (Important)

- After assistant-run tests, do not keep the server running in background.
- User will manually start server (`start.bat`) when needed for testing.

## Files Changed In This Session Chain

- `src/remote_control/server_app.py`
- `vendor/py312/aiortc/codecs/h264.py`
- `vendor/py312/av/*` (vendor AV package content upgraded to 16.1.0)
- `vendor/py312/av.libs/*`
- `vendor/py312/av-16.1.0.dist-info/*`
- `SESSION_HANDOFF_2026-03-02G.md`
- `SESSION_HANDOFF_LATEST.md`
