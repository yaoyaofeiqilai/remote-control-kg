# Session Handoff (2026-03-04C)

## Current Goal

- User rolled back the previous aggressive ultra-profile changes due to severe lag.
- Keep the current stable baseline architecture.
- Improve video quality only, with low-risk and incremental tuning (no complex mode switching).

## Work Completed This Session

1. Conservative quality tuning (`src/remote_control/server_app.py`)
- Raised default bitrate policy:
  - `RC_WEBRTC_BITRATE_KBPS` default: `30000` (was `24000`)
  - `RC_WEBRTC_START_BITRATE_KBPS` default: `32000` (was `24000`)
  - `RC_WEBRTC_MIN_BITRATE_KBPS` default: `2000` (was `300`)
  - `RC_WEBRTC_BITRATE_SCALE` default: `2.2` (was `2.0`)
  - `RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE` default: `0.45` (was `0.25`)
  - `RC_WEBRTC_AUDIO_TRANSPORT_BITRATE_CAP_SCALE` default: `0.90` (was `0.78`)
- Upgraded `_effective_webrtc_min_bitrate_kbps(...)` to use a dynamic floor:
  - Uses estimated bitrate + current quality/scale/fps + target pixels.
  - Applies stronger minimum bitrate under high-quality, high-scale, high-fps scenarios.
  - Preserves low-scale behavior (still allows lower bitrate when user sets low render scale).

2. Encoder-side quality tuning (`vendor/py312/aiortc/codecs/h264.py`)
- Raised high-resolution minimum bitrate default:
  - `RC_WEBRTC_HIGHRES_MIN_BITRATE_BPS` default: `16000000` (was `12000000`)
- Tuned NVENC candidate ladder for better motion detail while keeping fallback:
  - Primary candidate: `preset p4`, `tune ll`, `rc cbr`, `spatial_aq=1`, `temporal_aq=1`, `aq-strength=8`, `zerolatency=1`
  - Secondary candidate: `preset p3`, `tune ll`, with AQ enabled
  - Fallback candidate retained: `preset p2`, `tune ull`

3. Startup defaults aligned (`start.bat`)
- Added default env values so direct `start.bat` launches use the new quality-tuned baseline:
  - `RC_WEBRTC_BITRATE_SCALE=2.2`
  - `RC_WEBRTC_START_BITRATE_KBPS=32000`
  - `RC_WEBRTC_MIN_BITRATE_KBPS=2000`
  - `RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE=0.45`
  - `RC_WEBRTC_AUDIO_TRANSPORT_BITRATE_CAP_SCALE=0.90`
  - `RC_WEBRTC_HIGHRES_MIN_BITRATE_BPS=16000000`

## Validation Done

- Syntax checks:
  - `python -m py_compile src/remote_control/server_app.py vendor/py312/aiortc/codecs/h264.py` passed.
- Runtime/API sanity checks:
  - `/api/info` reflected new defaults and dynamic floor behavior.
  - Example baseline values observed at startup:
    - `quality=95`
    - `webrtc_scale=1.0`
    - `webrtc_bitrate_kbps=72990`
    - `webrtc_min_bitrate_effective_kbps=18977`
- Scale-down guard check:
  - After setting `webrtc_scale=0.25`, observed:
    - `webrtc_bitrate_kbps=4105`
    - `webrtc_min_bitrate_effective_kbps=2000`
  - Confirms dynamic floor does not over-constrain low-scale mode.
- End-to-end transport smoke:
  - `python tools/diagnostics/webrtc_audio_e2e.py --duration 10 --allow-silence` returned `ok: true`.
  - Audio/video tracks established and connection state reached `connected`.

## Observations

- During teardown after e2e test completion, repeated FFmpeg decode warnings appeared:
  - `No start code is found.`
  - `Error splitting the input into NAL units.`
- These appeared after normal session close and did not fail transport or e2e pass criteria.

## Current Runtime State

- Server is stopped after local testing.

## Start-From-Here Plan

1. User performs direct visual check on target device with current baseline.
2. If lag persists, tune only two knobs in small steps:
   - `RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE` in `0.35 .. 0.45`
   - `RC_WEBRTC_AUDIO_TRANSPORT_BITRATE_CAP_SCALE` in `0.85 .. 0.90`
3. Keep `quality=95` and `webrtc_scale=1.0` during comparison passes.

## Files Changed This Session

- `src/remote_control/server_app.py`
- `vendor/py312/aiortc/codecs/h264.py`
- `start.bat`

