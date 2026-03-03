# Session Handoff (2026-03-04A)

## Current Goal (Resume Tomorrow)

- Audio transport should be ON by default after tablet connect.
- With audio ON, avoid delay buildup above ~160ms that leads to frequent reconnects.
- Keep quality and FPS constraints unchanged (45 FPS target).

## Work Completed Today

1. Delay anti-buildup control (server)
- File: `src/remote_control/server_app.py`
- Added runtime bitrate guard knobs:
  - `RC_WEBRTC_RUNTIME_BITRATE_GUARD` (default: enabled)
  - `RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE` (default: `0.25`)
- Integrated `playout_delay / jitter / playback_rate / backlog` into a single control loop:
  - sender timing catchup (`ts_catchup`) with fast-down/slow-up behavior
  - runtime bitrate scale (`webrtc_runtime_bitrate_scale`) with fast-down/slow-up behavior
- Tightened high-delay guard behavior:
  - earlier high-delay trigger
  - shorter reset cooldown (`45s -> 35s`)
- Exposed runtime bitrate fields in `/api/info` and `/api/video_health`.

2. Audio transport default ON (frontend + backend)
- Frontend defaults:
  - File: `static/app.js`
  - `state.audio.transportEnabled` default set to `true`
  - `initSocket()` now initializes with `setAudioTransportLocalState(true, false)`
  - `CLIENT_BUILD` updated to `20260304_audio_fix3`
- UI defaults:
  - File: `templates/index.html`
  - `audio-transport-toggle` now has `checked` by default
  - default text shows enabled state
  - cache-bust versions updated to `20260304_audio_fix3`
- Backend default:
  - File: `src/remote_control/server_app.py`
  - added `audio_transport_default_enabled = RC_AUDIO_TRANSPORT_DEFAULT_ENABLED` (default true)
  - `connect` now initializes `audio_transport_by_sid` from that default
  - this avoids first-connection race where UI says ON but no audio track is attached
- Startup defaults:
  - File: `start.bat`
  - added `RC_AUDIO_TRANSPORT_DEFAULT_ENABLED=1`

## Validation Done

- `python -m py_compile src/remote_control/server_app.py` passed.
- `node --check static/app.js` passed.

## Sampling Artifacts (Today)

- `auto_samples_audio_baseline_20260304_003422.jsonl`
- `auto_samples_audio_guard_20260304_004148.jsonl`
- `auto_samples_audio_guard2_20260304_004454.jsonl` (interrupted)

Important caveat:
- These runs include offline/partial-online segments.
- User reported tablet was not stably connected during at least one run.
- Treat these as code-regression checks only, not final tuning evidence.

## Current Runtime State

- Server process is not currently running (stopped after tests).
- Latest user report before stop:
  - tablet still showed audio default OFF / `A=0kbps`.
  - code fix for backend default-on has been applied but not yet re-validated with a stable tablet session.

## Start-From-Here Plan (Tomorrow)

1. Start server
- Run `start.bat` (or `start_admin.bat`).
- Verify `/api/info` includes `audio_transport_default_enabled=true`.

2. Confirm real tablet connection
- Wait for `client connected` log.
- Run a 100s sampling pass that only counts `client_up=true` rows.

3. Validate key metrics with audio ON
- `playout_delay_ms` trend (no continuous climb)
- `runtime_bitrate_scale` downshift on pressure and controlled recovery
- reconnect/reset frequency (`peer_reset` and reconnect behavior)

4. If delay still climbs
- Tune one axis at a time:
  - runtime bitrate recovery speed first
  - then ts_catchup slope in mid/high delay bands
  - finally reset threshold/cooldown

## Uncommitted Files

- `src/remote_control/server_app.py`
- `static/app.js`
- `templates/index.html`
- `start.bat`

## Temporary Files (Optional Cleanup)

- `auto_samples_audio_baseline_20260304_003145.jsonl`
- `auto_samples_audio_baseline_20260304_003422.jsonl`
- `auto_samples_audio_guard_20260304_004148.jsonl`
- `auto_samples_audio_guard2_20260304_004454.jsonl`
- `tmp_auto_latency_baseline.ps1`
- `tmp_auto_latency_guard.ps1`
- `tmp_auto_latency_guard2.ps1`
