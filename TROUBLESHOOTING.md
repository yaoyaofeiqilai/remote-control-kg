# Troubleshooting

## 1) Python not found

- Install Python 3.12+.
- Verify:

```bat
python --version
py -3.12 --version
```

## 2) Dependency install failed

Try:

```bat
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

If your network is slow, use a mirror:

```bat
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 3) Tablet cannot connect

- Ensure PC and tablet are on the same LAN/WiFi/hotspot.
- Allow Python through Windows firewall.
- Verify server is reachable from host machine:

```bat
curl http://127.0.0.1:5000
```

## 4) Black screen or capture issues

- Start with admin (`start.bat` auto-elevates).
- Test DXGI support:

```bat
python tools/diagnostics/test_dxgi.py
```

## 5) High latency

- Lower quality/FPS in settings.
- Prefer 5GHz WiFi or direct hotspot.
- Close heavy background apps on host.

## 6) Collect diagnostics

```bat
python check_install.py
python server.py > error.log 2>&1
```

## 7) Audio has no sound

1. Ensure VB-CABLE is installed and `CABLE Output` appears in Windows recording devices.
2. Check backend audio status:

```bat
curl http://127.0.0.1:5000/api/audio_info
curl http://127.0.0.1:5000/api/audio_health
```

3. Run local smoke tests:

```bat
python tools/diagnostics/audio_smoke.py --duration 15
python tools/diagnostics/webrtc_audio_e2e.py --url http://127.0.0.1:5000 --duration 12
```

4. In silent environments, verify transport without RMS gate:

```bat
python tools/diagnostics/webrtc_audio_e2e.py --url http://127.0.0.1:5000 --duration 12 --allow-silence
```

5. If `status.last_error` shows `device_not_found_fallback`, backend already fell back to another input. To force VB-CABLE, set an exact name:

```bat
set RC_AUDIO_DEVICE_NAME=CABLE Output (VB-Audio Virtual Cable)
start.bat
```

6. Interpretation:
- `transport_ok=true` means negotiation and frame delivery are working.
- `rms_ok=false` usually means the source is currently silent, not necessarily a transport failure.
