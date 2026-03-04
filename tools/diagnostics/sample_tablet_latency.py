#!/usr/bin/env python3
"""Poll /api/video_health for tablet latency/reconnect diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_json(url: str, timeout: float = 2.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with _OPENER.open(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(math.floor((len(sorted_vals) - 1) * q))
    return float(sorted_vals[max(0, min(len(sorted_vals) - 1, idx))])


def build_summary(rows: list[dict[str, Any]], sample_file: str) -> dict[str, Any]:
    parsed = [r for r in rows if isinstance(r, dict)]
    online = [
        r
        for r in parsed
        if bool(r.get("client_up"))
        and float(r.get("playout_delay_ms", 0.0) or 0.0) > 0.0
    ]
    states = [bool(r.get("client_up")) for r in parsed if "client_up" in r]
    poll_failed = sum(1 for r in parsed if r.get("err") == "poll_failed")

    disconnect_events = 0
    reconnect_events = 0
    max_down_streak = 0
    down_streak = 0
    for i, state in enumerate(states):
        if not state:
            down_streak += 1
            max_down_streak = max(max_down_streak, down_streak)
        else:
            down_streak = 0
        if i > 0 and state != states[i - 1]:
            if states[i - 1] and not state:
                disconnect_events += 1
            elif (not states[i - 1]) and state:
                reconnect_events += 1

    sid_change_events = 0
    last_sid = ""
    for r in parsed:
        if not bool(r.get("client_up")):
            continue
        sid = str(r.get("client_sid", "") or "")
        if sid and last_sid and sid != last_sid:
            sid_change_events += 1
        if sid:
            last_sid = sid

    if not online:
        return {
            "sample_file": sample_file,
            "online_samples": 0,
            "poll_failed": int(poll_failed),
            "disconnect_events": int(disconnect_events),
            "reconnect_events": int(reconnect_events),
            "sid_change_events": int(sid_change_events),
            "max_down_streak_s": int(max_down_streak),
        }

    delays = [float(r.get("playout_delay_ms", 0.0) or 0.0) for r in online]
    scales = [float(r.get("runtime_bitrate_scale", 0.0) or 0.0) for r in online]
    playback = [float(r.get("playback_rate", 1.0) or 1.0) for r in online]
    bitrate = [float(r.get("bitrate_kbps", 0.0) or 0.0) for r in online]
    tail = delays[-20:] if len(delays) > 20 else delays
    within_30 = sum(1 for d in delays if d <= 30.0)
    within_40 = sum(1 for d in delays if d <= 40.0)
    over_80 = sum(1 for d in delays if d >= 80.0)

    return {
        "sample_file": sample_file,
        "online_samples": int(len(delays)),
        "avg_delay_ms": round(float(statistics.fmean(delays)), 2),
        "p50_delay_ms": round(float(quantile(delays, 0.50)), 2),
        "p90_delay_ms": round(float(quantile(delays, 0.90)), 2),
        "p95_delay_ms": round(float(quantile(delays, 0.95)), 2),
        "max_delay_ms": round(float(max(delays)), 2),
        "tail20_avg_ms": round(float(statistics.fmean(tail)), 2),
        "end_delay_ms": round(float(delays[-1]), 2),
        "delay_std_ms": round(float(statistics.pstdev(delays)) if len(delays) > 1 else 0.0, 2),
        "delay_le_30_ratio": round(float(within_30) / float(len(delays)), 4),
        "delay_le_40_ratio": round(float(within_40) / float(len(delays)), 4),
        "delay_ge_80_count": int(over_80),
        "bitrate_avg_kbps": round(float(statistics.fmean(bitrate)), 1),
        "runtime_scale_avg": round(float(statistics.fmean(scales)), 3),
        "runtime_scale_min": round(float(min(scales)), 3),
        "playback_rate_avg": round(float(statistics.fmean(playback)), 3),
        "playback_rate_max": round(float(max(playback)), 3),
        "poll_failed": int(poll_failed),
        "disconnect_events": int(disconnect_events),
        "reconnect_events": int(reconnect_events),
        "sid_change_events": int(sid_change_events),
        "max_down_streak_s": int(max_down_streak),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--duration", type=int, default=100)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    duration = max(10, int(args.duration))
    interval = max(0.2, float(args.interval))
    timeout = max(0.5, float(args.timeout))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sample_file = args.output.strip() or f"auto_samples_live_tuned_{ts}.jsonl"

    rows: list[dict[str, Any]] = []
    next_tick = time.time()
    for i in range(duration):
        now_ms = int(time.time() * 1000.0)
        row: dict[str, Any] = {"t_ms": now_ms, "i": i}
        try:
            vh = fetch_json(f"{args.base_url.rstrip('/')}/api/video_health", timeout=timeout)
            client = vh.get("client_stats") or {}
            track = vh.get("track_stats") or {}
            row.update(
                {
                    "client_up": bool(vh.get("client_up", False)),
                    "client_sid": str(client.get("sid", "") or ""),
                    "client_ts": float(client.get("ts", 0.0) or 0.0),
                    "bitrate_kbps": float(vh.get("bitrate_kbps", 0.0) or 0.0),
                    "runtime_bitrate_scale": float(vh.get("runtime_bitrate_scale", 0.0) or 0.0),
                    "recv_fps": float(track.get("recv_fps", 0.0) or 0.0),
                    "ts_catchup": float(track.get("ts_catchup", 0.0) or 0.0),
                    "playout_delay_ms": float(client.get("playout_delay_ms", 0.0) or 0.0),
                    "playout_delay_ewma_ms": float(client.get("playout_delay_ewma_ms", 0.0) or 0.0),
                    "jitter_ms": float(client.get("jitter_ms", 0.0) or 0.0),
                    "frames_backlog": float(client.get("frames_backlog", 0.0) or 0.0),
                    "playback_rate": float(client.get("playback_rate", 1.0) or 1.0),
                    "client_build": str(client.get("client_build", "") or ""),
                }
            )
            if (i % 10) == 0:
                try:
                    ah = fetch_json(f"{args.base_url.rstrip('/')}/api/audio_health", timeout=timeout)
                    row["audio_capture_running"] = bool(ah.get("capture_running", False))
                    row["audio_client_up"] = bool(ah.get("client_up", False))
                except Exception:
                    pass
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            row["err"] = "poll_failed"
            row["msg"] = str(exc)

        rows.append(row)
        next_tick += interval
        sleep_s = next_tick - time.time()
        if sleep_s > 0:
            time.sleep(sleep_s)

    with open(sample_file, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = build_summary(rows, sample_file)
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
