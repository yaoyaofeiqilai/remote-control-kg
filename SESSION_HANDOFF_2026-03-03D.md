# Session Handoff (2026-03-03D)

## Current User Goal

- Keep image quality and resolution unchanged (no quality downgrade).
- Keep default FPS at `45` (including Web UI default).
- Stop latency from continuously increasing over time.
- Push steady latency toward `~30ms` (preferably below).

## Conversation Record (Saved)

User-reported issues across this conversation:

1. Latency drift and reconnection loop
- Start latency was often low (`~8-15ms`) after connect.
- Latency then climbed gradually (`200ms -> 300ms -> 400ms`), followed by auto reconnect.

2. Constraints repeatedly confirmed by user
- Do not reduce quality.
- Do not reduce FPS.
- Default FPS must be `45`.
- Use real tablet auto-connection data for tuning.
- Run autonomous tuning loops with max `100s` per test.

3. User requested explicit progress persistence
- "Save conversation record and update progress document."

## Code/Runtime Work Completed

1. Server-side latency control refinement (`src/remote_control/server_app.py`)
- Added effective delay fusion to avoid stale EWMA over-driving catch-up:
  - `delay = max(raw, min(ewma, raw + 20ms))`
- Kept aggressive tighten / slow release sender catch-up behavior:
  - tighten: `0.40/0.60`
  - release: `0.93/0.07`
- Added stronger middle-zone floors to avoid lingering in `35~55ms` band.
- Audio default remains off (`RC_AUDIO_ENABLED=0`) for latency stability.

2. Client-side low-latency control refinement (`static/app.js`)
- `CLIENT_BUILD` now: `20260303_latency_tune2c`
- Added `getEffectivePlayoutDelayMs()` and used it consistently for:
  - playback catch-up rate decisions
  - latency drift checks
  - HUD delay display
  - soft-flush telemetry delay reporting
- Low-latency receiver hints kept at zero-target mode:
  - `playoutDelayHint=0.0`
  - `jitterBufferTarget=0.0`

3. Web cache bust + FPS default confirmation (`templates/index.html`)
- Asset version updated to `latency_tune2c`.
- FPS slider default confirmed as `value="45"`.

## 100s Automated Test Progress (This Session)

Important samples (all from `/api/video_health` polling loops):

- Baseline before this round of tuning:
  - `auto_samples_now_20260303_225223.jsonl`
  - avg `38.54ms`, end `37.08ms`, max `57.71ms`

- Improved round:
  - `auto_samples_now_tune2_20260303_225723.jsonl`
  - avg `35.72ms`, end `35.63ms`, max `72.76ms`

- Over-aggressive round (reverted):
  - `auto_samples_now_tune3_20260303_230012.jsonl`
  - avg `51.65ms`

- Best round in this session:
  - `auto_samples_now_tune2b_20260303_230321.jsonl`
  - avg `31.82ms`, end `28.49ms`, max `62.95ms`

- After EWMA-fusion update (`tune2c`):
  - `auto_samples_tune2c_20260303_231409.jsonl`
  - avg `34.80ms`, tail80 avg `30.62ms`, p50 `31.99ms`, p90 `48.83ms`, end `38.17ms`

## Current Status

- Major regression (runaway `200~400ms`) is significantly improved in controlled 100s loops.
- Latency still has intermittent spikes (`~50-100ms`) under some periods.
- Target "`always <=30ms`" is not yet fully achieved.

## Current Runtime Snapshot

- Listener state:
  - `0.0.0.0:5000 LISTENING` PID `9916`
- `/api/info`:
  - `video_encoder_active: h264_nvenc`
  - `webrtc_fps: 45`
  - `webrtc_scale: 1.0`
- Instant sample at handoff time showed elevated delay (active catch-up):
  - `playout_delay_ms ~68.9`
  - `playout_delay_ewma_ms ~62.0`
  - `playback_rate 1.22`

## Next Session Starting Point

1. Keep current code baseline (`latency_tune2c`), do not revert.
2. Start with one fresh 100s run and compare:
- `avg`
- `tail30 avg`
- `p90`
- `max`
3. If spikes persist, tune only one control at a time (avoid coupled over-corrections):
- sender catch-up floor in `35~60ms`
- client playback-rate threshold in `30~60ms`
- peer reset guard threshold/cooldown

