#!/usr/bin/env python3
"""Smoke test for local VB-CABLE style input capture."""

import argparse
import json
import os
import sys
import time

import numpy as np

try:
    import sounddevice as sd
except Exception as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"sounddevice_import_failed: {exc}"}, ensure_ascii=False))
    sys.exit(2)


def list_input_devices():
    devices = []
    hostapis = sd.query_hostapis()
    for idx, dev in enumerate(sd.query_devices()):
        max_in = int(dev.get("max_input_channels", 0) or 0)
        if max_in <= 0:
            continue
        hostapi_name = ""
        hostapi_idx = dev.get("hostapi", None)
        if isinstance(hostapi_idx, int) and 0 <= hostapi_idx < len(hostapis):
            hostapi_name = str(hostapis[hostapi_idx].get("name", ""))
        devices.append(
            {
                "index": idx,
                "name": str(dev.get("name", "")),
                "hostapi": hostapi_name,
                "max_input_channels": max_in,
            }
        )
    return devices


def choose_device(devices, hint):
    if not devices:
        raise RuntimeError("no_input_devices")

    hint_l = (hint or "").strip().lower()
    ranked = []
    for dev in devices:
        name = dev["name"].lower()
        hostapi = dev["hostapi"].lower()
        if hint_l and hint_l not in name:
            continue
        score = 0
        if "cable output" in name:
            score += 300
        if "vb-audio" in name or "vb cable" in name or "cable" in name:
            score += 150
        if "wasapi" in hostapi:
            score += 20
        score += min(int(dev["max_input_channels"]), 2)
        ranked.append((score, dev))

    if hint_l and not ranked:
        raise RuntimeError(f"device_not_found: hint={hint}")

    if not ranked:
        for dev in devices:
            score = 1
            ranked.append((score, dev))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--device-hint", default=os.getenv("RC_AUDIO_DEVICE_NAME", "CABLE Output"))
    parser.add_argument("--sample-rate", type=int, default=int(os.getenv("RC_AUDIO_SAMPLE_RATE", "48000")))
    parser.add_argument("--channels", type=int, default=int(os.getenv("RC_AUDIO_CHANNELS", "2")))
    parser.add_argument("--frame-ms", type=int, default=int(os.getenv("RC_AUDIO_FRAME_MS", "20")))
    parser.add_argument("--min-rms", type=float, default=1e-4)
    args = parser.parse_args()

    frame_samples = max(80, int(args.sample_rate * args.frame_ms / 1000))
    channels = max(1, min(2, int(args.channels)))

    devices = list_input_devices()
    selected = choose_device(devices, args.device_hint)
    channels = min(channels, int(selected["max_input_channels"]))

    state = {
        "frames": 0,
        "rms_max": 0.0,
        "rms_avg": 0.0,
        "status_events": 0,
    }

    def callback(indata, frames, time_info, status):
        del frames, time_info
        if status:
            state["status_events"] += 1
        pcm = np.asarray(indata, dtype=np.float32)
        if pcm.ndim == 1:
            pcm = pcm.reshape(-1, 1)
        if pcm.shape[1] > channels:
            pcm = pcm[:, :channels]
        if pcm.shape[1] < channels:
            pad = np.zeros((pcm.shape[0], channels - pcm.shape[1]), dtype=np.float32)
            pcm = np.hstack([pcm, pad])
        rms = float(np.sqrt(np.mean(np.square(np.clip(pcm, -1.0, 1.0)))))
        state["frames"] += 1
        state["rms_max"] = max(state["rms_max"], rms)
        state["rms_avg"] += rms

    started = time.time()
    with sd.InputStream(
        samplerate=args.sample_rate,
        channels=channels,
        blocksize=frame_samples,
        dtype="float32",
        device=int(selected["index"]),
        callback=callback,
    ):
        time.sleep(max(1.0, float(args.duration)))

    elapsed = time.time() - started
    if state["frames"] > 0:
        state["rms_avg"] /= state["frames"]

    expected = max(1, int((elapsed * 1000.0) / max(1, args.frame_ms)))
    ok = (
        state["frames"] >= int(expected * 0.6)
        and state["rms_max"] >= args.min_rms
    )

    result = {
        "ok": bool(ok),
        "duration_sec": round(elapsed, 2),
        "expected_frames": expected,
        "frames": state["frames"],
        "rms_max": state["rms_max"],
        "rms_avg": state["rms_avg"],
        "status_events": state["status_events"],
        "selected_device": selected,
        "sample_rate": args.sample_rate,
        "channels": channels,
        "frame_ms": args.frame_ms,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
