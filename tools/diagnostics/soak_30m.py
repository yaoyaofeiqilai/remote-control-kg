#!/usr/bin/env python3
"""Soak test: poll /api/audio_health for long-run stability."""

import argparse
import json
import time
import urllib.error
import urllib.request


def fetch_json(url, timeout=5.0):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5000/api/audio_health")
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--min-up-ratio", type=float, default=0.95)
    parser.add_argument("--max-down-streak", type=int, default=30)
    args = parser.parse_args()

    duration = max(10, int(args.duration))
    interval = max(1, int(args.interval))
    started = time.time()
    end_at = started + duration

    total = 0
    up_count = 0
    client_up_count = 0
    down_streak = 0
    max_down_streak = 0
    errors = 0
    last_error = ""

    while time.time() < end_at:
        total += 1
        try:
            data = fetch_json(args.url, timeout=4.0)
            up = bool(data.get("up", False))
            client_up = bool(data.get("client_up", False))
            if up:
                up_count += 1
            if client_up:
                client_up_count += 1
            if up and client_up:
                down_streak = 0
            else:
                down_streak += interval
                max_down_streak = max(max_down_streak, down_streak)
                last_error = str(data.get("last_error", "") or last_error)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            errors += 1
            down_streak += interval
            max_down_streak = max(max_down_streak, down_streak)
            last_error = str(exc)

        now = time.time()
        if now >= end_at:
            break
        time.sleep(min(interval, end_at - now))

    elapsed = time.time() - started
    up_ratio = (up_count / total) if total else 0.0
    client_up_ratio = (client_up_count / total) if total else 0.0

    ok = (
        total > 0
        and up_ratio >= args.min_up_ratio
        and max_down_streak <= args.max_down_streak
    )

    result = {
        "ok": bool(ok),
        "elapsed_sec": round(elapsed, 2),
        "samples": total,
        "up_ratio": round(up_ratio, 4),
        "client_up_ratio": round(client_up_ratio, 4),
        "network_or_parse_errors": errors,
        "max_down_streak_sec": max_down_streak,
        "last_error": last_error,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
