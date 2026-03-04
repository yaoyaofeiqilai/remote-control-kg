# Remote Control (Windows Host)

A LAN remote-control server for controlling a Windows PC from a tablet/phone browser.

## Current Architecture

- `server.py`: backward-compatible launcher (kept for old workflows).
- `src/remote_control/server_app.py`: main backend runtime (Flask + Socket.IO + capture/input pipeline).
- `src/remote_control/input_sender.py`: low-level Windows `SendInput` wrapper.
- `static/` + `templates/`: web client UI.
- `tools/diagnostics/`: optional diagnostic scripts and test assets.

## Quick Start

1. Install dependencies once:
   - Run `install.bat`
2. Start server (admin is auto-handled):
   - Run `start.bat`
3. Open the URL shown in terminal on your tablet/phone browser.

## Startup Scripts

- `start.bat`
  - Auto-elevates to administrator if needed.
  - Auto-detects Python 3.12.
  - Checks/install dependencies when missing.
  - Starts server with `--dxgi` by default.
  - Initializes `artifacts/` output directories (`logs`, `samples`, `pids`, `baseline`).
- `start_admin.bat`
  - Compatibility wrapper that always starts admin flow.

## One-Click GitHub Deploy

Use `deploy_github.bat`.

```bat
deploy_github.bat https://github.com/<USER>/<REPO>.git "your commit message"
```

What it does:
- Initializes git repo if needed.
- Configures `origin` remote if URL provided.
- Stages all changes.
- Commits if there are staged changes.
- Pushes current branch to `origin`.

## Optional Diagnostics

- `tools/diagnostics/test_dxgi.py`
- `tools/diagnostics/test_uac_capture.py`
- `tools/diagnostics/test_uac_now.py`
- `tools/diagnostics/uac_test_dpi.py`
- `tools/diagnostics/audio_smoke.py`
- `tools/diagnostics/webrtc_audio_e2e.py`
- `tools/diagnostics/soak_30m.py`

Diagnostics output defaults:
- logs: `artifacts/logs/`
- sampled metrics: `artifacts/samples/`
- pids: `artifacts/pids/`

## Audio (VB-CABLE Preferred, Auto Fallback)

Default audio source hint is `CABLE Output`.
If the hinted device is not found, backend now falls back to the best available input device and reports `device_not_found_fallback` in `status.last_error`.

Env vars:
- `RC_AUDIO_ENABLED=1`
- `RC_AUDIO_DEVICE_NAME=CABLE Output`
- `RC_AUDIO_SAMPLE_RATE=48000`
- `RC_AUDIO_CHANNELS=2`
- `RC_AUDIO_FRAME_MS=20`

Example:

```bat
set RC_AUDIO_DEVICE_NAME=CABLE Output
start.bat
```

Quick checks:

```bat
python tools/diagnostics/audio_smoke.py --duration 15
python tools/diagnostics/webrtc_audio_e2e.py --url http://127.0.0.1:5000 --duration 12
python tools/diagnostics/webrtc_audio_e2e.py --url http://127.0.0.1:5000 --duration 12 --allow-silence
python tools/diagnostics/soak_30m.py --url http://127.0.0.1:5000/api/audio_health --duration 1800
```

`webrtc_audio_e2e.py` behavior:
- Default: requires transport success and `audio_rms_max >= --min-rms`.
- `--allow-silence`: only requires transport/frame thresholds (useful when source is expected to be silent).

## Debug Logging

Verbose debug output is disabled by default.

Enable temporarily:

```bat
set RC_DEBUG=1
start.bat
```

## Notes

- Keep usage inside trusted LAN environments.
- For UAC popup capture/control reliability, run as administrator.

## Maintenance Cleanup

Use the cleanup utility to remove stale runtime artifacts and old handoff files.

```bat
python tools/maintenance/cleanup_repo.py
python tools/maintenance/cleanup_repo.py --apply --keep-handoffs 3
```
