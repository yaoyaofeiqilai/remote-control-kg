#!/usr/bin/env python3
"""Headless WebRTC A/V smoke test via Socket.IO signaling."""

import argparse
import asyncio
import json
import time

import numpy as np
import socketio
from aiortc import RTCPeerConnection, RTCSessionDescription


async def consume_audio(track, stats, stop_at):
    while time.time() < stop_at:
        try:
            frame = await asyncio.wait_for(track.recv(), timeout=5.0)
        except asyncio.TimeoutError:
            stats["audio_timeouts"] += 1
            continue
        except Exception as exc:
            stats["audio_errors"].append(str(exc))
            break

        arr = frame.to_ndarray()
        f32 = arr.astype(np.float32)
        if f32.ndim == 1:
            rms = float(np.sqrt(np.mean(np.square(f32 / 32768.0))))
        else:
            rms = float(np.sqrt(np.mean(np.square(f32 / 32768.0))))
        stats["audio_frames"] += 1
        stats["audio_rms_max"] = max(stats["audio_rms_max"], rms)


async def consume_video(track, stats, stop_at):
    while time.time() < stop_at:
        try:
            await asyncio.wait_for(track.recv(), timeout=5.0)
        except asyncio.TimeoutError:
            stats["video_timeouts"] += 1
            continue
        except Exception as exc:
            stats["video_errors"].append(str(exc))
            break
        stats["video_frames"] += 1


async def run_case(args):
    sio = socketio.AsyncClient(logger=False, engineio_logger=False, reconnection=False)
    pc = RTCPeerConnection()

    stats = {
        "audio_frames": 0,
        "video_frames": 0,
        "audio_rms_max": 0.0,
        "audio_timeouts": 0,
        "video_timeouts": 0,
        "audio_errors": [],
        "video_errors": [],
        "webrtc_error": "",
        "connected": False,
        "track_events": [],
        "connection_states": [],
        "answer_has_audio": False,
        "answer_has_video": False,
        "answer_media_lines": [],
    }

    answer_future = asyncio.get_event_loop().create_future()
    tasks = []
    stop_at = time.time() + 3600.0

    @sio.event
    async def connect():
        stats["connected"] = True

    @sio.on("webrtc_answer")
    async def on_answer(data):
        if not answer_future.done():
            answer_future.set_result(data)

    @sio.on("webrtc_error")
    async def on_webrtc_error(data):
        err = data.get("error") if isinstance(data, dict) else str(data)
        stats["webrtc_error"] = str(err or "unknown")
        if not answer_future.done():
            answer_future.set_exception(RuntimeError(stats["webrtc_error"]))

    @pc.on("track")
    def on_track(track):
        stats["track_events"].append(track.kind)
        if track.kind == "audio":
            tasks.append(asyncio.create_task(consume_audio(track, stats, stop_at)))
        elif track.kind == "video":
            tasks.append(asyncio.create_task(consume_video(track, stats, stop_at)))

    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        stats["connection_states"].append(pc.connectionState)

    try:
        await sio.connect(args.url, transports=["websocket", "polling"], wait_timeout=10)

        pc.addTransceiver("video", direction="recvonly")
        pc.addTransceiver("audio", direction="recvonly")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        await sio.emit("webrtc_offer", {"sdp": offer.sdp, "type": offer.type})

        answer = await asyncio.wait_for(answer_future, timeout=15)
        answer_sdp = answer.get("sdp", "") if isinstance(answer, dict) else ""
        stats["answer_has_audio"] = "m=audio" in answer_sdp
        stats["answer_has_video"] = "m=video" in answer_sdp
        stats["answer_media_lines"] = [
            line for line in answer_sdp.splitlines()
            if (
                line.startswith("m=")
                or line.startswith("a=send")
                or line.startswith("a=recv")
                or line.startswith("a=inactive")
            )
        ][:24]
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type=answer.get("type", "answer"))
        )
        stop_at = time.time() + max(5.0, float(args.duration))

        await asyncio.sleep(max(5.0, float(args.duration)))
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await pc.close()
        if sio.connected:
            await sio.disconnect()

    transport_ok = (
        stats["connected"]
        and not stats["webrtc_error"]
        and stats["video_frames"] >= args.min_video_frames
        and stats["audio_frames"] >= args.min_audio_frames
    )
    rms_ok = stats["audio_rms_max"] >= args.min_rms
    ok = transport_ok and (args.allow_silence or rms_ok)

    result = {
        "ok": bool(ok),
        "url": args.url,
        "duration_sec": args.duration,
        "min_audio_frames": args.min_audio_frames,
        "min_video_frames": args.min_video_frames,
        "min_rms": args.min_rms,
        "allow_silence": bool(args.allow_silence),
        "transport_ok": bool(transport_ok),
        "rms_ok": bool(rms_ok),
        **stats,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5000")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--min-audio-frames", type=int, default=20)
    parser.add_argument("--min-video-frames", type=int, default=20)
    parser.add_argument("--min-rms", type=float, default=1e-5)
    parser.add_argument(
        "--allow-silence",
        action="store_true",
        help="Only require transport/frame thresholds, skip RMS gate.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    code = asyncio.run(run_case(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
