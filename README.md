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
