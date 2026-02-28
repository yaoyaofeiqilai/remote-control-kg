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
