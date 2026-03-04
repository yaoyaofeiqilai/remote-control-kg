# Session Handoff (2026-03-04B)

## Current Goal

- Keep audio transport ON by default.
- With audio ON, reduce delay and avoid delay-buildup-triggered reconnects.
- Keep quality/FPS target unchanged (quality 95, 45 FPS).

## Work Completed Today

1. Server-side latency control updates (`src/remote_control/server_app.py`)
- Tuned delay guard around a tighter low-latency target band.
- Added/adjusted runtime bitrate shaping knobs:
  - `RC_WEBRTC_RUNTIME_BITRATE_IDLE_SCALE` (default now `0.80`)
  - `RC_WEBRTC_AUDIO_TRANSPORT_BITRATE_CAP_SCALE` (default now `0.78`)
- Kept runtime bitrate floor control:
  - `RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE` (existing)
- Changed ts-catchup scheduling behavior:
  - sender pacing remains on target FPS cadence
  - catchup influences RTP timestamp progression (not packet pacing burst)
- Added delayed-stats handling (`stats_stale`) in guard path for stale client metrics.
- Added peer-reset switch:
  - `RC_WEBRTC_DELAY_PEER_RESET` (default now `false`)
  - avoids server-initiated reset by default to reduce forced reconnect.
- Audio Opus maxaveragebitrate default changed to `200000` bps.

2. Frontend updates (`static/app.js`, `templates/index.html`)
- `CLIENT_BUILD` updated to `20260304_audio_fix6`.
- Cache-bust versions updated to `20260304_audio_fix6`.
- Tuned playback catchup tiers and latency drift reaction thresholds.
- Added stale-stats fallback reporting (`stats_stale: true`) when `getStats()` polling fails.

3. Startup/reliability scripts
- `start.bat`
  - default `RC_WEBRTC_AUDIO_OPUS_MAXAVERAGEBITRATE_BPS=200000`
  - added auto-restart loop (`RC_SERVER_AUTORESTART`, `RC_SERVER_RESTART_DELAY_SEC`)
- Added diagnostics/helpers:
  - `tools/diagnostics/restart_server_fast.ps1`
  - `tools/diagnostics/sample_tablet_latency.py`
  - `tools/diagnostics/run_sample_with_server.ps1`
  - `tools/diagnostics/server_watchdog.ps1`

## Validation Done

- `python -m py_compile src/remote_control/server_app.py` passed.
- `node --check static/app.js` passed.
- Multiple 100s tablet sampling passes executed with audio transport ON.

## Representative Sampling Results (100s)

- `auto_samples_live_tuned_20260304_124358.jsonl`
  - avg `23.89ms`, p90 `71.03ms`, max `125.95ms`
  - disconnect/reconnect: `0 / 0`
- `auto_samples_live_tuned_cycle_20260304_122247.jsonl`
  - avg `14.12ms`, p90 `39.35ms`, max `118.56ms`
  - reconnect `1` (startup-phase reconnect pattern)
- `auto_samples_live_tuned_20260304_124548.jsonl`
  - avg `68.14ms`, p90 `109.38ms`, max `110.98ms`
  - disconnect/reconnect: `0 / 0` (but sustained high-delay plateau)

Key finding:
- reconnect behavior improved in several runs, but latency is still not consistently <30ms across all 100s runs.
- intermittent high-delay plateaus still occur depending on run/session conditions.

## Current Runtime State

- Server is currently stopped (per user request for manual testing).
- Watchdog is stopped.

## Start-From-Here Plan

1. Start server manually (`start.bat` or `python server.py --dxgi`) and confirm tablet on `audio_fix6`.
2. Run `python tools/diagnostics/sample_tablet_latency.py --duration 100 --timeout 3` for comparable baseline.
3. Prioritize reducing high-delay plateaus without enabling server peer-reset:
   - tune `runtime_bitrate` recovery and floor behavior first
   - then tune ts-catchup mid/high-delay bands
4. Re-check reconnect metrics (`disconnect_events`, `reconnect_events`, `sid_change_events`) each pass.

## Files Changed This Session

- `src/remote_control/server_app.py`
- `static/app.js`
- `templates/index.html`
- `start.bat`
- `tools/diagnostics/restart_server_fast.ps1`
- `tools/diagnostics/sample_tablet_latency.py`
- `tools/diagnostics/run_sample_with_server.ps1`
- `tools/diagnostics/server_watchdog.ps1`

