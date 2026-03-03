# Session Handoff (2026-03-03C)

## Current User Goal

- Keep full resolution and high quality (no quality compromise).
- Reach stable 60 FPS on mobile browser with low latency.
- Keep startup simple: run only `start.bat`.

## User Decision In This Turn

- User asked whether discrete GPU should perform better.
- Conclusion: yes, in this project it is very likely better because current bottleneck is server encode/send path and iGPU run is on `h264_amf`.
- User plans to reboot/switch to discrete GPU mode and retest.

## What Was Verified Before Reboot

1. Server/process state
- Single listener on `:5000` (PID `29636`), one active client.

2. Runtime encoder and GPU state
- `/api/info` showed:
  - `video_encoder_active: h264_amf`
  - `video_encoder_preferred: h264_nvenc`
  - `screen_size: 2560x1600`
  - `webrtc_scale: 1.0`
- Host GPU list showed only integrated GPU active:
  - `AMD Radeon(TM) 610M`

3. Bottleneck telemetry snapshot (integrated GPU run)
- 30-sample average (same method as prior sessions):
  - `capture_avg: 59.08`
  - `track_recv_fps avg: 42.44` (min `39.4`, max `49.9`)
  - `client_fps avg: 41.5` (min `29`, max `46`)
  - `decode_ms avg: 34.12`
  - `track_wait_ms avg: 0`
- This remains consistent with encode/send-side bottleneck rather than capture-side bottleneck.

## Code Changes Made In This Turn

1. Updated default encoder order to prefer MF before AMF when NVENC/QSV unavailable.
- File: `start.bat`
- Default now:
  - `h264_nvenc,h264_qsv,h264_mf,h264_amf,libx264`

2. Added more low-latency AMF option candidates (AMF fallback tuning).
- File: `vendor/py312/aiortc/codecs/h264.py`
- Added AMF candidates including:
  - `usage=ultralowlatency`
  - `quality=speed`
  - `rc=cbr`
  - existing repeat headers / aud / gop signaling retained.

3. Sanity check
- `python -m py_compile vendor/py312/aiortc/codecs/h264.py` passed.

## Important Note

- The new encoder-order / AMF-tuning changes require server restart to take effect.

## First Steps After Reboot (Discrete GPU Test)

1. Start server once via `start.bat`.
2. Confirm single listener:
```powershell
netstat -ano | findstr :5000
```
3. Confirm active encoder:
```powershell
$base='http://127.0.0.1:5000'
(Invoke-WebRequest -UseBasicParsing "$base/api/info" -TimeoutSec 3).Content
```
- Expectation with discrete GPU available: `video_encoder_active` becomes `h264_nvenc` after stream starts.
4. Collect continuous health samples (same as baseline) for before/after comparison:
```powershell
1..12 | % { (Invoke-WebRequest -UseBasicParsing "$base/api/video_health" -TimeoutSec 3).Content; Start-Sleep -Milliseconds 500 }
```

## User Preference Reminder

- User starts/stops server manually with `start.bat`.
- Do not leave server running in background after assistant-side diagnostics.
