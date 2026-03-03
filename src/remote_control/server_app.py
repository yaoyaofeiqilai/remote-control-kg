#!/usr/bin/env python3
"""
Remote control server for Windows hosts.
Provides screen capture and input control over web.
"""

import asyncio
import base64
import ctypes
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from fractions import Fraction

import mss
import numpy as np

DEBUG_LOG_ENABLED = os.getenv("RC_DEBUG", "0") == "1"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def debug_log(message):
    if DEBUG_LOG_ENABLED:
        print(message)


def _env_flag(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "off", "no")


def _env_int(name, default, minimum, maximum):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name, default, minimum, maximum):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    return max(minimum, min(maximum, value))

# Cleaned garbled comment.
DXCAM_AVAILABLE = False
DXCAM_PATCHED = False
dxcam = None


def _patch_dxcam_runtime(dx_module):
    """Patch known dxcam teardown bug when init fails partway."""
    global DXCAM_PATCHED
    if DXCAM_PATCHED:
        return

    camera_cls = getattr(dx_module, "DXCamera", None)
    if camera_cls is None:
        DXCAM_PATCHED = True
        return

    original_stop = getattr(camera_cls, "stop", None)
    if callable(original_stop):
        def _safe_stop(self, *args, **kwargs):
            if not hasattr(self, "is_capturing"):
                try:
                    setattr(self, "is_capturing", False)
                except Exception:
                    pass
            try:
                return original_stop(self, *args, **kwargs)
            except AttributeError as e:
                if "is_capturing" in str(e):
                    return None
                raise

        camera_cls.stop = _safe_stop

    DXCAM_PATCHED = True


def load_dxcam():
    """Lazy-load dxcam to avoid startup-time import crashes."""
    global DXCAM_AVAILABLE, dxcam
    try:
        import warnings
        warnings.filterwarnings('ignore')
        import dxcam as dx
        _patch_dxcam_runtime(dx)
        dxcam = dx
        DXCAM_AVAILABLE = True
        return True
    except Exception as e:
        print(f"[DXGI] load failed: {e}")
        return False

# Cleaned garbled comment.
try:
    from PIL import Image
except ImportError as e:
    print(f"[Error] Failed to import Pillow: {e}")
    print("Run: python -m pip install Pillow")
    exit(1)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VENDOR_DIR = os.path.join(PROJECT_ROOT, "vendor", "py312")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

from flask import Flask, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pyautogui

# Cleaned garbled comment.
try:
    from .input_sender import get_input_sender, InputSender
    INPUT_SENDER_AVAILABLE = True
    print("[Input] low-level SendInput API available")
except Exception as e:
    print(f"[Input] failed to load low-level SendInput API: {e}")
    INPUT_SENDER_AVAILABLE = False

XINPUT_AVAILABLE = False
vg = None
XUSB_BUTTON = None
try:
    if os.name == 'nt':
        import vgamepad as _vg
        vg = _vg
        XUSB_BUTTON = vg.XUSB_BUTTON
        XINPUT_AVAILABLE = True
except Exception as e:
    print(f"[Gamepad] vgamepad unavailable: {e}")

WEBRTC_AVAILABLE = False
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.rtcrtpsender import RTCRtpSender
    from aiortc.mediastreams import AudioStreamTrack, VideoStreamTrack
    from av import AudioFrame, VideoFrame
    WEBRTC_AVAILABLE = True
except Exception as e:
    print(f"[WebRTC] dependency load failed: {e}")

AV_MODULE_AVAILABLE = False
av_mod = None
try:
    import av as _av_mod
    av_mod = _av_mod
    AV_MODULE_AVAILABLE = True
except Exception:
    pass

# Cleaned garbled comment.
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATE_DIR)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    ping_timeout=90,
    ping_interval=20,
)


@app.after_request
def _disable_cache_for_ui(resp):
    path = str(request.path or "")
    if path == "/" or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

SOUNDDEVICE_AVAILABLE = False
sd = None
try:
    import sounddevice as _sd
    sd = _sd
    SOUNDDEVICE_AVAILABLE = True
except Exception as e:
    print(f"[Audio] sounddevice load failed: {e}")

SOUNDCARD_AVAILABLE = False
sc = None
try:
    import soundcard as _sc
    sc = _sc
    SOUNDCARD_AVAILABLE = True
except Exception as e:
    print(f"[Audio] soundcard load failed: {e}")

# Cleaned garbled comment.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

# Cleaned garbled comment.
connected_clients = 0
quality = _env_int("RC_QUALITY", 95, 10, 95)  # Cleaned garbled comment.
fps = 45  # Cleaned garbled comment.

webrtc_enabled = True
webrtc_capture_backend = (os.getenv("RC_CAPTURE_BACKEND", "auto") or "auto").strip().lower()
if webrtc_capture_backend not in ("auto", "dxgi", "mss"):
    webrtc_capture_backend = "auto"
webrtc_fps_max = _env_int("RC_WEBRTC_FPS_MAX", 120, 30, 240)
webrtc_target_fps = _env_int("RC_WEBRTC_FPS", 45, 5, webrtc_fps_max)
fps = int(webrtc_target_fps)
_screen_size = pyautogui.size()
webrtc_scale = _env_float("RC_WEBRTC_SCALE", 1.0, 0.25, 1.0)
webrtc_max_width = _env_int("RC_WEBRTC_MAX_WIDTH", int(_screen_size.width), 320, 7680)
webrtc_max_height = _env_int("RC_WEBRTC_MAX_HEIGHT", int(_screen_size.height), 240, 4320)
capture_all_monitors = _env_flag("RC_CAPTURE_ALL_MONITORS", False)
webrtc_bitrate_auto = _env_flag("RC_WEBRTC_AUTO_BITRATE", True)
webrtc_max_bitrate_kbps = _env_int("RC_WEBRTC_MAX_BITRATE_KBPS", 80000, 1000, 200000)
webrtc_target_bitrate_kbps = _env_int("RC_WEBRTC_BITRATE_KBPS", 24000, 500, webrtc_max_bitrate_kbps)
webrtc_start_bitrate_kbps = _env_int("RC_WEBRTC_START_BITRATE_KBPS", 24000, 500, webrtc_max_bitrate_kbps)
webrtc_min_bitrate_kbps = _env_int("RC_WEBRTC_MIN_BITRATE_KBPS", 300, 300, webrtc_max_bitrate_kbps)
webrtc_bitrate_scale = _env_float("RC_WEBRTC_BITRATE_SCALE", 2.0, 0.5, 3.0)
webrtc_ts_catchup_enabled = _env_flag("RC_WEBRTC_TS_CATCHUP", True)
webrtc_ts_catchup_min = _env_float("RC_WEBRTC_TS_CATCHUP_MIN", 0.45, 0.30, 1.0)
webrtc_force_h264_only = _env_flag("RC_WEBRTC_FORCE_H264_ONLY", True)
webrtc_h264_conservative_level = _env_flag("RC_WEBRTC_H264_CONSERVATIVE_LEVEL", False)
webrtc_h264_profile_prefix = (os.getenv("RC_WEBRTC_H264_PROFILE_PREFIX", "42e0") or "42e0").strip().lower()
if len(webrtc_h264_profile_prefix) != 4 or any(ch not in "0123456789abcdef" for ch in webrtc_h264_profile_prefix):
    webrtc_h264_profile_prefix = "42e0"
last_h264_signal = {
    "profile_level_id": "",
    "level_idc": 0,
    "max_fs": 0,
    "max_mbps": 0,
    "signal_fps": 0,
    "target_w": 0,
    "target_h": 0,
}
last_video_codec_policy = {
    "h264_only": bool(webrtc_force_h264_only),
    "video_pt_count": 0,
    "h264_pt_count": 0,
}
webrtc_peers = {}
webrtc_audio_tracks = {}
webrtc_loop = None
webrtc_loop_thread = None
webrtc_frame_pump = None
webrtc_sender_ts_catchup = 1.0
webrtc_sender_ts_lock = threading.Lock()
webrtc_sender_ts_by_sid = {}


def _estimate_webrtc_bitrate_kbps():
    """Estimate a sane video bitrate target from quality/fps/scale."""
    try:
        size = pyautogui.size()
        screen_w = int(size.width)
        screen_h = int(size.height)
    except Exception:
        screen_w = int(getattr(_screen_size, "width", 1920))
        screen_h = int(getattr(_screen_size, "height", 1080))

    scale = max(0.25, min(1.0, float(webrtc_scale)))
    fps_now = max(15, min(int(webrtc_fps_max), int(webrtc_target_fps)))
    quality_now = max(10, min(95, int(quality)))

    target_w = max(320, int(screen_w * scale))
    target_h = max(240, int(screen_h * scale))
    mpix_per_s = (float(target_w) * float(target_h) * float(fps_now)) / 1_000_000.0

    # 10..95 => 0.4..1.5
    quality_factor = 0.4 + ((quality_now - 10) / 85.0) * 1.1
    kbps = int(mpix_per_s * 120.0 * quality_factor * float(webrtc_bitrate_scale))

    # High-res / high-fps mode should aggressively reserve bandwidth to keep cadence.
    if target_w >= 2200 and target_h >= 1300 and fps_now >= 60 and scale >= 0.95:
        kbps = max(kbps, 50000)
        if quality_now >= 90:
            kbps = max(kbps, 60000)

    return max(1200, min(int(webrtc_max_bitrate_kbps), kbps))


def _sync_webrtc_bitrate_target():
    """Refresh bitrate target when quality/fps/scale changes."""
    global webrtc_target_bitrate_kbps
    if webrtc_bitrate_auto:
        webrtc_target_bitrate_kbps = _estimate_webrtc_bitrate_kbps()
    return int(webrtc_target_bitrate_kbps)


def _effective_webrtc_min_bitrate_kbps(target_kbps: int) -> int:
    """Resolve effective min bitrate hint from configured policy."""
    target_kbps = max(500, int(target_kbps))
    configured = max(300, int(webrtc_min_bitrate_kbps))
    return max(300, min(target_kbps, configured))


_sync_webrtc_bitrate_target()


def _probe_video_encoders():
    """Probe H264 encoder availability from current AV build."""
    result = {
        "available": [],
        "hardware_available": [],
        "preferred": "libx264",
        "active": "",
    }
    candidates = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_mf", "h264_omx", "libx264")
    if not AV_MODULE_AVAILABLE or av_mod is None:
        return result

    available = []
    for name in candidates:
        try:
            av_mod.CodecContext.create(name, "w")
            available.append(name)
        except Exception:
            pass
    result["available"] = available
    result["hardware_available"] = [n for n in available if n != "libx264"]
    if result["hardware_available"]:
        result["preferred"] = result["hardware_available"][0]
    elif "libx264" in available:
        result["preferred"] = "libx264"
    return result


video_encoder_status = _probe_video_encoders()


def _get_active_video_encoder_name():
    try:
        import aiortc.codecs.h264 as h264_mod
        name = str(getattr(h264_mod, "LAST_ENCODER_NAME", "") or "")
        return name
    except Exception:
        return ""


audio_enabled = _env_flag("RC_AUDIO_ENABLED", True)
audio_device_name = (os.getenv("RC_AUDIO_DEVICE_NAME", "CABLE Output") or "").strip()
audio_prefer_wasapi_loopback = _env_flag("RC_AUDIO_PREFER_WASAPI_LOOPBACK", True)
audio_sample_rate = _env_int("RC_AUDIO_SAMPLE_RATE", 48000, 8000, 192000)
audio_channels = _env_int("RC_AUDIO_CHANNELS", 2, 1, 2)
audio_frame_ms = _env_int("RC_AUDIO_FRAME_MS", 20, 10, 120)
audio_debug = _env_flag("RC_AUDIO_DEBUG", False)
audio_frame_samples = max(80, int(audio_sample_rate * audio_frame_ms / 1000))

audio_status_lock = threading.Lock()
audio_status = {
    "enabled": bool(audio_enabled),
    "sounddevice_available": bool(SOUNDDEVICE_AVAILABLE),
    "soundcard_available": bool(SOUNDCARD_AVAILABLE),
    "webrtc_available": bool(WEBRTC_AVAILABLE),
    "device_name_hint": audio_device_name,
    "sample_rate": int(audio_sample_rate),
    "channels": int(audio_channels),
    "frame_ms": int(audio_frame_ms),
    "frame_samples": int(audio_frame_samples),
    "selected_device": None,
    "device_index": None,
    "capture_mode": "",
    "capture_running": False,
    "frames_generated": 0,
    "dropped_frames": 0,
    "discontinuities": 0,
    "last_rms": 0.0,
    "last_frame_ts": 0.0,
    "last_error": "",
    "client_stats": {},
}
if audio_enabled and not SOUNDDEVICE_AVAILABLE:
    audio_status["last_error"] = "sounddevice_unavailable"

video_status_lock = threading.Lock()
video_status = {
    "client_stats": {},
    "track_stats": {},
}

# Cleaned garbled comment.
dxgi_camera = None
dxgi_capture_enabled = webrtc_capture_backend in ("auto", "dxgi")  # Cleaned garbled comment.
dxgi_capture_target_fps = _env_int("RC_DXGI_CAPTURE_FPS", 120, 30, 240)
dxgi_output_color = (os.getenv("RC_DXGI_OUTPUT_COLOR", "RGB") or "RGB").strip().upper()
if dxgi_output_color not in ("RGB", "BGRA"):
    dxgi_output_color = "RGB"
dxgi_lock = threading.RLock()
dxgi_failure_count = 0
dxgi_retry_after = 0.0
dxgi_hard_disabled = False

mss_local = threading.local()

# Cleaned garbled comment.
game_mode = False  # Cleaned garbled comment.
input_sender = None
if INPUT_SENDER_AVAILABLE:
    input_sender = get_input_sender()

xinput_lock = threading.RLock()
xinput_pad = None
xinput_owner_sid = None
xinput_last_buttons = 0
xinput_state_count = 0
xinput_state_last_log = 0.0
xinput_state_queue = deque(maxlen=256)
xinput_state_event = threading.Event()
xinput_worker_started = False
xinput_apply_count = 0
xinput_apply_nonzero = 0
xinput_apply_last_log = 0.0


def _audio_set_status(**kwargs):
    with audio_status_lock:
        audio_status.update(kwargs)


def _audio_inc(field, delta=1):
    with audio_status_lock:
        audio_status[field] = int(audio_status.get(field, 0)) + int(delta)


def _audio_set_error(message):
    _audio_set_status(last_error=str(message or ""))


def _audio_snapshot():
    with audio_status_lock:
        return dict(audio_status)


def _video_set_client_stats(stats):
    with video_status_lock:
        video_status["client_stats"] = dict(stats or {})


def _video_set_track_stats(stats):
    with video_status_lock:
        video_status["track_stats"] = dict(stats or {})


def _video_snapshot():
    with video_status_lock:
        return dict(video_status)


def _webrtc_sender_ts_cleanup_locked(now_ts: float):
    stale_before = float(now_ts) - 6.0
    stale_sids = [sid for sid, item in webrtc_sender_ts_by_sid.items() if float(item.get("ts", 0.0)) < stale_before]
    for sid in stale_sids:
        webrtc_sender_ts_by_sid.pop(sid, None)


def _webrtc_sender_ts_recompute_locked():
    global webrtc_sender_ts_catchup
    if not webrtc_ts_catchup_enabled or not webrtc_sender_ts_by_sid:
        webrtc_sender_ts_catchup = 1.0
        return
    factor = min(float(v.get("factor", 1.0) or 1.0) for v in webrtc_sender_ts_by_sid.values())
    webrtc_sender_ts_catchup = float(max(float(webrtc_ts_catchup_min), min(1.0, factor)))


def _webrtc_sender_ts_remove_sid(sid: str):
    sid = str(sid or "")
    if not sid:
        return
    with webrtc_sender_ts_lock:
        webrtc_sender_ts_by_sid.pop(sid, None)
        _webrtc_sender_ts_recompute_locked()


def _webrtc_sender_ts_update_from_client_stats(stats):
    global webrtc_sender_ts_catchup
    if not webrtc_ts_catchup_enabled:
        return
    sid = str((stats or {}).get("sid", "") or "")
    if not sid:
        return
    delay = float((stats or {}).get("playout_delay_ewma_ms", 0.0) or 0.0)
    if delay <= 0.0:
        delay = float((stats or {}).get("playout_delay_ms", 0.0) or 0.0)
    if delay <= 0.0:
        return

    now_ts = float(time.time())
    with webrtc_sender_ts_lock:
        prev = webrtc_sender_ts_by_sid.get(sid, {})
        prev_factor = float(prev.get("factor", 1.0) or 1.0)
        hold_until = float(prev.get("hold_until", 0.0) or 0.0)

        # Base proportional target around a 30ms objective.
        if delay <= 30.0:
            target = 1.0
        else:
            # Delay 30 -> 1.0, delay 250 -> about 0.38 (later clamped by min).
            target = 1.0 - min(0.70, ((delay - 30.0) / 355.0))

        # Enter/extend an anti-rebound hold window when delay is clearly high.
        if delay >= 220.0:
            hold_until = max(hold_until, now_ts + 10.0)
            target = min(target, 0.48)
        elif delay >= 170.0:
            hold_until = max(hold_until, now_ts + 8.0)
            target = min(target, 0.56)
        elif delay >= 125.0:
            hold_until = max(hold_until, now_ts + 6.0)
            target = min(target, 0.66)

        if now_ts < hold_until:
            # Keep moderate catch-up active for a short window to avoid quick bounce back.
            target = min(target, 0.70)

        # Fast apply when tightening catch-up; slow release when returning to 1.0.
        if target < prev_factor:
            factor = (prev_factor * 0.55) + (float(target) * 0.45)
        else:
            factor = (prev_factor * 0.90) + (float(target) * 0.10)
        factor = float(max(float(webrtc_ts_catchup_min), min(1.0, factor)))
        webrtc_sender_ts_by_sid[sid] = {
            "factor": factor,
            "delay_ms": float(delay),
            "hold_until": float(hold_until),
            "ts": now_ts,
        }
        _webrtc_sender_ts_cleanup_locked(now_ts)
        _webrtc_sender_ts_recompute_locked()


def _webrtc_sender_ts_get_factor():
    with webrtc_sender_ts_lock:
        return float(webrtc_sender_ts_catchup)


def _audio_list_input_devices():
    if not SOUNDDEVICE_AVAILABLE or sd is None:
        return []

    devices = []
    try:
        hostapis = sd.query_hostapis()
        all_devices = sd.query_devices()
    except Exception as e:
        _audio_set_error(f"query_devices_failed: {e}")
        return []

    for idx, dev in enumerate(all_devices):
        max_input = int(dev.get("max_input_channels", 0) or 0)
        if max_input <= 0:
            continue

        hostapi_name = ""
        hostapi_idx = dev.get("hostapi", None)
        if isinstance(hostapi_idx, int) and 0 <= hostapi_idx < len(hostapis):
            hostapi_name = str(hostapis[hostapi_idx].get("name", ""))

        devices.append({
            "index": int(idx),
            "name": str(dev.get("name", "")),
            "hostapi": hostapi_name,
            "max_input_channels": max_input,
            "default_samplerate": float(dev.get("default_samplerate", 0.0) or 0.0),
        })

    return devices


def _audio_select_input_device(devices):
    if not devices:
        raise RuntimeError("no_input_device")

    hint = (audio_device_name or "").strip().lower()
    def _score_device(dev):
        name = dev["name"].lower()
        hostapi = dev["hostapi"].lower()
        score = 0

        # Best candidates for system output capture.
        if "cable output" in name:
            score += 700
        if "vb-audio" in name or "vb cable" in name or "cable" in name:
            score += 350

        loopback_tokens = (
            "stereo mix",
            "\u7acb\u4f53\u58f0\u6df7\u97f3",
            "loopback",
            "what u hear",
            "wave out mix",
            "monitor of",
        )
        if any(tok in name for tok in loopback_tokens):
            score += 500

        # Prefer APIs that usually expose better capture behavior on Windows.
        if "wasapi" in hostapi:
            score += 60
        if "wdm" in hostapi:
            score += 40
        if "mme" in hostapi:
            score += 10

        # Avoid choosing microphones by default.
        mic_tokens = (
            "microphone",
            "mic",
            "\u9ea6\u514b\u98ce",
            "\u9635\u5217",
            "array",
        )
        if any(tok in name for tok in mic_tokens):
            score -= 200

        score += min(int(dev.get("max_input_channels", 0) or 0), 2) * 8
        if float(dev.get("default_samplerate", 0.0) or 0.0) >= 48000.0:
            score += 15
        return score

    matched = []
    for dev in devices:
        name = dev["name"].lower()
        if hint and hint not in name:
            continue
        matched.append((_score_device(dev), dev))

    if hint and not matched:
        _audio_set_error(f"device_not_found_fallback: hint={audio_device_name}")

    if not matched:
        for dev in devices:
            matched.append((_score_device(dev), dev))

    matched.sort(key=lambda item: item[0], reverse=True)
    return matched[0][1]


def _audio_rank_input_devices(devices):
    ranked = []
    tmp_devices = list(devices)
    seen = set()
    while tmp_devices:
        selected = _audio_select_input_device(tmp_devices)
        idx = int(selected.get("index", -1))
        if idx in seen:
            break
        seen.add(idx)
        ranked.append(selected)
        tmp_devices = [d for d in tmp_devices if int(d.get("index", -1)) != idx]
    return ranked


def _audio_list_wasapi_output_devices():
    if not SOUNDDEVICE_AVAILABLE or sd is None:
        return []

    devices = []
    try:
        hostapis = sd.query_hostapis()
        all_devices = sd.query_devices()
    except Exception as e:
        _audio_set_error(f"query_output_devices_failed: {e}")
        return []

    for idx, dev in enumerate(all_devices):
        max_output = int(dev.get("max_output_channels", 0) or 0)
        if max_output <= 0:
            continue

        hostapi_name = ""
        hostapi_idx = dev.get("hostapi", None)
        if isinstance(hostapi_idx, int) and 0 <= hostapi_idx < len(hostapis):
            hostapi_name = str(hostapis[hostapi_idx].get("name", ""))
        if "wasapi" not in hostapi_name.lower():
            continue

        devices.append({
            "index": int(idx),
            "name": str(dev.get("name", "")),
            "hostapi": hostapi_name,
            "max_output_channels": max_output,
            "default_samplerate": float(dev.get("default_samplerate", 0.0) or 0.0),
        })

    return devices


def _audio_list_loopback_speakers():
    if not SOUNDCARD_AVAILABLE or sc is None:
        return []
    try:
        speakers = sc.all_speakers()
    except Exception as e:
        _audio_set_error(f"list_loopback_speakers_failed: {e}")
        return []

    rows = []
    for sp in speakers:
        try:
            channels = int(getattr(sp, "channels", 0) or 0)
        except Exception:
            channels = 0
        rows.append({
            "id": str(getattr(sp, "id", "")),
            "name": str(getattr(sp, "name", "")),
            "channels": max(1, channels),
        })
    return rows


def _audio_select_loopback_speaker(speakers):
    if not speakers:
        raise RuntimeError("no_loopback_speaker")

    hint = (audio_device_name or "").strip().lower()
    default_speaker_id = ""
    try:
        if SOUNDCARD_AVAILABLE and sc is not None and hasattr(sc, "default_speaker"):
            default_speaker = sc.default_speaker()
            default_speaker_id = str(getattr(default_speaker, "id", "") or "")
    except Exception:
        default_speaker_id = ""

    def _score(sp):
        name = sp["name"].lower()
        score = 0
        if "cable input" in name:
            score += 800
        if "vb-audio" in name or "vb cable" in name or "cable" in name:
            score += 300
        if "speaker" in name or "speakers" in name:
            score += 120
        if "headphone" in name or "headset" in name:
            score += 80
        if "virtual" in name or "todesk" in name:
            score -= 120
        if default_speaker_id and str(sp.get("id", "")) == default_speaker_id:
            score += 220
        score += min(int(sp.get("channels", 0) or 0), 2) * 8
        return score

    matched = []
    for sp in speakers:
        name = sp["name"].lower()
        if hint and hint not in name:
            continue
        matched.append((_score(sp), sp))

    if hint and not matched:
        _audio_set_error(f"loopback_speaker_hint_not_found_fallback: hint={audio_device_name}")

    if not matched:
        for sp in speakers:
            matched.append((_score(sp), sp))

    matched.sort(key=lambda item: item[0], reverse=True)
    return matched[0][1]


def _audio_rank_loopback_output_devices(devices):
    if not devices:
        return []

    hint = (audio_device_name or "").strip().lower()
    default_out = None
    try:
        default_pair = sd.default.device if sd is not None else None
        if isinstance(default_pair, (list, tuple)) and len(default_pair) >= 2:
            default_out = int(default_pair[1])
    except Exception:
        default_out = None

    def _score_device(dev):
        name = dev["name"].lower()
        score = 0
        # For VB-CABLE loopback on playback side, device name is usually "CABLE Input".
        if "cable input" in name:
            score += 800
        if "vb-audio" in name or "vb cable" in name or "cable" in name:
            score += 300

        loopback_hint_tokens = (
            "speaker",
            "speakers",
            "headphone",
            "headset",
            "output",
            "\u626c\u58f0\u5668",
            "\u8033\u673a",
        )
        if any(tok in name for tok in loopback_hint_tokens):
            score += 120

        if default_out is not None and int(dev.get("index", -1)) == default_out:
            score += 180

        score += min(int(dev.get("max_output_channels", 0) or 0), 2) * 8
        if float(dev.get("default_samplerate", 0.0) or 0.0) >= 48000.0:
            score += 15
        return score

    matched = []
    for dev in devices:
        name = dev["name"].lower()
        if hint and hint not in name:
            continue
        matched.append((_score_device(dev), dev))

    if hint and not matched:
        _audio_set_error(f"loopback_hint_not_found_fallback: hint={audio_device_name}")

    if not matched:
        for dev in devices:
            matched.append((_score_device(dev), dev))

    matched.sort(key=lambda item: item[0], reverse=True)
    return [dev for _, dev in matched]


def is_running_as_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

if not is_running_as_admin():
    print("[Hint] Not running as administrator: input injection on elevated windows may fail.")
    print("[Hint] Please use start_admin.bat to launch in administrator mode.")


def _is_dxgi_unsupported_error(err):
    text = str(err or "")
    lowered = text.lower()
    if (
        "unsupported" in lowered
        or "not supported" in lowered
        or "feature level" in lowered
    ):
        return True
    try:
        first_arg = getattr(err, "args", [None])[0]
        code = int(first_arg)
        if code == -2005270524:
            return True
    except Exception:
        pass
    return False


def init_dxgi_camera():
    """Initialize DXGI camera."""
    global dxgi_camera, dxcam, dxgi_failure_count, dxgi_retry_after, dxgi_capture_enabled, dxgi_hard_disabled

    # Cleaned garbled comment.
    if dxcam is None and not load_dxcam():
        return False
    if dxgi_hard_disabled:
        return False

    with dxgi_lock:
        if dxgi_camera is not None:
            return True

        try:
            # Cleaned garbled comment.
            try:
                dxgi_camera = dxcam.create(output_color=dxgi_output_color)
            except TypeError:
                dxgi_camera = dxcam.create()
            try:
                if hasattr(dxgi_camera, "start"):
                    target = max(30, min(int(dxgi_capture_target_fps), int(webrtc_fps_max)))
                    try:
                        dxgi_camera.start(target_fps=target, video_mode=True)
                    except TypeError:
                        dxgi_camera.start(target_fps=target)
            except Exception as e:
                print(f"[DXGI] start failed: {e}")
            dxgi_failure_count = 0
            dxgi_retry_after = 0.0
            print(
                f"[DXGI] camera initialized, output={dxgi_camera.width}x{dxgi_camera.height}, "
                f"color={dxgi_output_color}"
            )
            return True
        except Exception as e:
            print(f"[DXGI] initialization failed: {e}")
            dxgi_camera = None
            if _is_dxgi_unsupported_error(e):
                dxgi_hard_disabled = True
                dxgi_capture_enabled = False
                dxgi_retry_after = float("inf")
                print("[DXGI] unsupported on current adapter/feature level; disabling DXGI retries.")
            return False

def release_dxgi_camera():
    """Release DXGI camera."""
    global dxgi_camera
    with dxgi_lock:
        if dxgi_camera:
            try:
                if hasattr(dxgi_camera, "stop"):
                    try:
                        dxgi_camera.stop()
                    except Exception:
                        pass
                dxgi_camera.release()
                print("[DXGI] camera released")
            except Exception as e:
                print(f"[DXGI] release failed: {e}")
            dxgi_camera = None


def reconfigure_dxgi_capture_fps():
    """Apply latest target FPS to a running DXGI capture instance."""
    global dxgi_camera
    with dxgi_lock:
        if dxgi_camera is None:
            return False
        target = max(30, min(int(dxgi_capture_target_fps), int(webrtc_fps_max)))
        try:
            if hasattr(dxgi_camera, "stop"):
                dxgi_camera.stop()
            if hasattr(dxgi_camera, "start"):
                try:
                    dxgi_camera.start(target_fps=target, video_mode=True)
                except TypeError:
                    dxgi_camera.start(target_fps=target)
            return True
        except Exception as e:
            print(f"[DXGI] reconfigure FPS failed: {e}")
            return False


def handle_dxgi_error(err):
    """Record DXGI failures and back off before retry."""
    global dxgi_failure_count, dxgi_retry_after, dxgi_capture_enabled, dxgi_hard_disabled
    if _is_dxgi_unsupported_error(err):
        dxgi_hard_disabled = True
        dxgi_capture_enabled = False
        dxgi_retry_after = float("inf")
        print(f"[DXGI Error] {err}, fallback to MSS, DXGI disabled until manual re-enable")
        release_dxgi_camera()
        return
    dxgi_failure_count = min(dxgi_failure_count + 1, 8)
    backoff = min(30.0, float(2 ** (dxgi_failure_count - 1)))
    dxgi_retry_after = time.time() + backoff
    print(f"[DXGI Error] {err}, fallback to MSS, retry in {backoff:.0f}s")
    release_dxgi_camera()


def should_try_dxgi():
    if (not dxgi_capture_enabled) or dxgi_hard_disabled:
        return False
    return time.time() >= dxgi_retry_after


def get_local_ip():
    """Return local LAN IP."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def get_mss():
    inst = getattr(mss_local, "inst", None)
    monitor = getattr(mss_local, "monitor", None)
    if inst is None or monitor is None:
        inst = mss.mss()
        monitors = getattr(inst, "monitors", []) or []
        monitor = None
        if capture_all_monitors:
            monitor = monitors[0] if monitors else None
        else:
            if len(monitors) > 1:
                # Prefer a single physical monitor close to OS-reported screen size.
                try:
                    screen = pyautogui.size()
                    sw = int(screen.width)
                    sh = int(screen.height)
                    best = None
                    best_score = None
                    for mon in monitors[1:]:
                        mw = int(mon.get("width", 0))
                        mh = int(mon.get("height", 0))
                        if mw <= 0 or mh <= 0:
                            continue
                        score = abs(mw - sw) + abs(mh - sh)
                        if best is None or score < best_score:
                            best = mon
                            best_score = score
                    monitor = best if best is not None else monitors[1]
                except Exception:
                    monitor = monitors[1]
            elif monitors:
                monitor = monitors[0]
        if monitor is None:
            raise RuntimeError("mss monitor list is empty")
        mss_local.inst = inst
        mss_local.monitor = monitor
    return inst, monitor


def capture_screen_frame_np():
    """
    Capture one frame for WebRTC.
    Returns: (ndarray, pixel_format) where pixel_format is 'rgb24' or 'bgra'.
    """
    global dxgi_camera

    if should_try_dxgi():
        try:
            with dxgi_lock:
                if dxgi_camera is None:
                    if not init_dxgi_camera():
                        raise Exception("DXGI init failed")

                if hasattr(dxgi_camera, "get_latest_frame"):
                    frame = dxgi_camera.get_latest_frame()
                else:
                    frame = dxgi_camera.grab()
            if frame is not None:
                if frame.ndim == 3 and frame.shape[2] == 4:
                    if not frame.flags["C_CONTIGUOUS"]:
                        frame = np.ascontiguousarray(frame)
                    return frame, "bgra"
                if frame.ndim == 3 and frame.shape[2] == 3:
                    if frame.flags["C_CONTIGUOUS"]:
                        return frame, "rgb24"
                    return np.ascontiguousarray(frame), "rgb24"
                if frame.ndim == 3 and frame.shape[2] > 3:
                    rgb = frame[:, :, :3]
                    if rgb.flags["C_CONTIGUOUS"]:
                        return rgb, "rgb24"
                    return np.ascontiguousarray(rgb), "rgb24"
            return None, None
        except Exception as e:
            handle_dxgi_error(e)

    try:
        inst, monitor = get_mss()
        screenshot = inst.grab(monitor)
        bgra = np.frombuffer(screenshot.bgra, dtype=np.uint8)
        bgra = bgra.reshape((screenshot.height, screenshot.width, 4))
        if not bgra.flags["C_CONTIGUOUS"]:
            bgra = np.ascontiguousarray(bgra)
        return bgra, "bgra"
    except Exception as e:
        print(f"[Screen Capture Error] {e}")
        return None, None


def resize_rgb_frame(frame, target_w, target_h):
    """Resize RGB ndarray with Pillow for non-integer scales."""
    h, w = frame.shape[:2]
    target_w = int(max(2, target_w))
    target_h = int(max(2, target_h))
    if target_w == w and target_h == h:
        return frame
    try:
        resample = Image.Resampling.BILINEAR
    except Exception:
        resample = Image.BILINEAR
    img = Image.fromarray(frame, mode="RGB")
    resized = img.resize((target_w, target_h), resample=resample)
    arr = np.asarray(resized, dtype=np.uint8)
    if arr.flags["C_CONTIGUOUS"]:
        return arr
    return np.ascontiguousarray(arr)


def to_rgb24(frame, pixel_format):
    """Convert captured frame to rgb24 when processing requires it."""
    if frame is None:
        return None
    if pixel_format == "rgb24":
        if frame.flags["C_CONTIGUOUS"]:
            return frame
        return np.ascontiguousarray(frame)
    if pixel_format == "bgra":
        rgb = frame[:, :, [2, 1, 0]]
        return np.ascontiguousarray(rgb)
    if frame.ndim == 3 and frame.shape[2] >= 3:
        rgb = frame[:, :, :3]
        if rgb.flags["C_CONTIGUOUS"]:
            return rgb
        return np.ascontiguousarray(rgb)
    return None


class WebRTCFramePump:
    def __init__(self):
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._latest = None
        self._latest_ts = 0.0
        self._capture_fps = 0.0
        self._fps_counter = 0
        self._fps_window_start = float(time.time())
        self._running = False
        self._thread = None
        self._generation = 0
        self._last_error_log_ts = 0.0

    def start(self):
        with self._state_lock:
            if self._running and self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            self._generation += 1
            generation = self._generation
            self._thread = threading.Thread(
                target=self._run,
                args=(generation,),
                daemon=True,
                name=f"WebRTCFramePump-{generation}",
            )
            self._thread.start()

    def stop(self):
        with self._state_lock:
            self._running = False
            self._generation += 1

    def get_latest(self):
        with self._lock:
            return self._latest

    def frame_age(self):
        with self._lock:
            if self._latest is None or self._latest_ts <= 0.0:
                return float("inf")
            return max(0.0, float(time.time() - self._latest_ts))

    def capture_fps(self):
        with self._lock:
            return float(self._capture_fps)

    def restart(self, reason="unknown"):
        print(f"[WebRTC] frame pump restart: {reason}")
        self.stop()

        # Reset cached frame to avoid serving stale image forever.
        with self._lock:
            self._latest = None
            self._latest_ts = 0.0

        # Best-effort reset of capture backends.
        try:
            release_dxgi_camera()
        except Exception:
            pass
        try:
            inst = getattr(mss_local, "inst", None)
            if inst is not None:
                try:
                    inst.close()
                except Exception:
                    pass
                try:
                    delattr(mss_local, "inst")
                except Exception:
                    pass
                try:
                    delattr(mss_local, "monitor")
                except Exception:
                    pass
        except Exception:
            pass

        self.start()

    def _run(self, generation):
        global webrtc_target_fps, webrtc_scale, webrtc_max_width, webrtc_max_height
        next_tick = time.perf_counter()

        def _sleep_to_next_frame():
            nonlocal next_tick
            target_fps = max(15, min(int(webrtc_fps_max), int(webrtc_target_fps)))
            interval = 1.0 / float(target_fps)
            now_tick = time.perf_counter()
            if next_tick < (now_tick - interval):
                next_tick = now_tick
            next_tick += interval
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)

        while True:
            with self._state_lock:
                if (not self._running) or (generation != self._generation):
                    break

            try:
                frame, pixel_format = capture_screen_frame_np()
            except Exception as e:
                now = time.time()
                if now - self._last_error_log_ts >= 2.0:
                    print(f"[WebRTC] frame capture error: {e}")
                    self._last_error_log_ts = now
                _sleep_to_next_frame()
                continue

            if frame is None:
                _sleep_to_next_frame()
                continue

            # Apply requested scale first.
            scale = float(webrtc_scale)
            if scale < 0.99:
                rgb = to_rgb24(frame, pixel_format)
                if rgb is None:
                    frame = None
                    pixel_format = None
                else:
                    frame = rgb
                    pixel_format = "rgb24"
                    h, w = frame.shape[:2]
                    target_w = max(2, int(round(float(w) * max(0.25, min(1.0, scale)))))
                    target_h = max(2, int(round(float(h) * max(0.25, min(1.0, scale)))))
                    frame = resize_rgb_frame(frame, target_w, target_h)

            # Hard safety cap for mobile/browser stability.
            if frame is not None:
                h, w = frame.shape[:2]
                max_w = max(1, int(webrtc_max_width))
                max_h = max(1, int(webrtc_max_height))
                if w > max_w or h > max_h:
                    rgb = to_rgb24(frame, pixel_format)
                    if rgb is None:
                        frame = None
                        pixel_format = None
                    else:
                        frame = rgb
                        pixel_format = "rgb24"
                        h, w = frame.shape[:2]
                        ratio = min(float(max_w) / float(w), float(max_h) / float(h))
                        target_w = max(2, int(round(float(w) * ratio)))
                        target_h = max(2, int(round(float(h) * ratio)))
                        frame = resize_rgb_frame(frame, target_w, target_h)

            if frame is None:
                _sleep_to_next_frame()
                continue

            if not frame.flags["C_CONTIGUOUS"]:
                frame = np.ascontiguousarray(frame)
            with self._lock:
                self._latest = (frame, pixel_format or "rgb24")
                self._latest_ts = float(time.time())
                self._fps_counter += 1
                now = time.time()
                window = now - self._fps_window_start
                if window >= 1.0:
                    self._capture_fps = float(self._fps_counter) / float(max(window, 1e-6))
                    self._fps_counter = 0
                    self._fps_window_start = now

            _sleep_to_next_frame()


if WEBRTC_AVAILABLE:
    class SystemAudioTrack(AudioStreamTrack):
        kind = "audio"

        def __init__(self):
            super().__init__()
            self._sample_rate = int(audio_sample_rate)
            self._channels = int(audio_channels)
            self._frame_samples = int(audio_frame_samples)
            self._queue = queue.Queue(maxsize=240)
            self._pending = np.zeros((0, self._channels), dtype=np.int16)
            self._stream = None
            self._loopback_cm = None
            self._loopback_rec = None
            self._pts = 0
            self._wall_start = None
            self._closed = False

        def _try_start_soundcard_loopback(self):
            if not (audio_prefer_wasapi_loopback and SOUNDCARD_AVAILABLE and sc is not None):
                return False

            speakers = _audio_list_loopback_speakers()
            if not speakers:
                return False

            selected = _audio_select_loopback_speaker(speakers)
            selected_channels = min(self._channels, int(selected.get("channels", 2) or 2))
            selected_channels = max(1, selected_channels)

            rate_candidates = [int(self._sample_rate)]
            # Typical stable fallback rates.
            for r in (48000, 44100):
                if r not in rate_candidates:
                    rate_candidates.append(r)

            last_error = None
            for try_rate in rate_candidates:
                try:
                    speaker_id = str(selected.get("id", ""))
                    mic = sc.get_microphone(id=speaker_id, include_loopback=True)
                    self._sample_rate = int(try_rate)
                    self._channels = int(selected_channels)
                    self._frame_samples = max(80, int(self._sample_rate * audio_frame_ms / 1000))
                    self._pending = np.zeros((0, self._channels), dtype=np.int16)

                    self._loopback_cm = mic.recorder(
                        samplerate=self._sample_rate,
                        channels=self._channels,
                        blocksize=self._frame_samples,
                    )
                    self._loopback_rec = self._loopback_cm.__enter__()
                except Exception as e:
                    last_error = e
                    self._loopback_cm = None
                    self._loopback_rec = None
                    continue

                _audio_set_status(
                    capture_mode="soundcard_loopback",
                    capture_running=True,
                    selected_device=selected["name"],
                    device_index=None,
                    channels=int(self._channels),
                    sample_rate=int(self._sample_rate),
                    frame_samples=int(self._frame_samples),
                    last_error="",
                )
                print(
                    f"[Audio] capture ready: mode=soundcard_loopback, device={selected['name']}, "
                    f"rate={self._sample_rate}, ch={self._channels}, frame={self._frame_samples}"
                )
                return True

            _audio_set_error(f"soundcard_loopback_start_failed: {last_error}")
            return False

        def _ensure_capture(self):
            if self._stream is not None or self._loopback_rec is not None:
                return
            if not audio_enabled:
                raise RuntimeError("audio_disabled")

            # Preferred path: speaker loopback (works even when local playback is silent).
            if self._try_start_soundcard_loopback():
                return

            if not SOUNDDEVICE_AVAILABLE or sd is None:
                raise RuntimeError("sounddevice_unavailable")

            input_devices = _audio_list_input_devices()
            try:
                input_candidates = _audio_rank_input_devices(input_devices)
            except Exception as e:
                _audio_set_error(f"select_input_device_failed: {e}")
                raise

            candidates = []
            for dev in input_candidates:
                candidates.append(("input", dev))

            last_start_error = None
            for capture_mode, selected in candidates:
                max_ch = int(selected.get("max_input_channels", 0) or 0)

                selected_channels = min(self._channels, max_ch)
                if selected_channels < 1:
                    continue

                rate_candidates = [int(self._sample_rate)]
                default_rate = int(float(selected.get("default_samplerate", 0.0) or 0.0))
                if default_rate > 0 and default_rate not in rate_candidates:
                    rate_candidates.append(default_rate)

                for try_rate in rate_candidates:
                    self._sample_rate = int(try_rate)
                    self._frame_samples = max(80, int(self._sample_rate * audio_frame_ms / 1000))
                    self._channels = selected_channels
                    self._pending = np.zeros((0, self._channels), dtype=np.int16)

                    def _callback(indata, frames, time_info, status):
                        if self._closed:
                            return
                        if status:
                            _audio_inc("discontinuities", 1)
                            _audio_set_error(f"callback_status: {status}")

                        try:
                            pcm = np.asarray(indata, dtype=np.float32)
                            if pcm.ndim == 1:
                                pcm = pcm.reshape(-1, 1)
                            if pcm.shape[1] < self._channels:
                                pad = np.zeros((pcm.shape[0], self._channels - pcm.shape[1]), dtype=np.float32)
                                pcm = np.hstack([pcm, pad])
                            elif pcm.shape[1] > self._channels:
                                pcm = pcm[:, :self._channels]

                            pcm = np.clip(pcm, -1.0, 1.0)
                            int16_pcm = (pcm * 32767.0).astype(np.int16, copy=False)
                        except Exception as e:
                            _audio_set_error(f"callback_convert_failed: {e}")
                            return

                        try:
                            self._queue.put_nowait(int16_pcm.copy())
                        except queue.Full:
                            try:
                                self._queue.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                self._queue.put_nowait(int16_pcm.copy())
                            except Exception:
                                pass
                            _audio_inc("dropped_frames", 1)

                    try:
                        stream_kwargs = {
                            "samplerate": self._sample_rate,
                            "blocksize": self._frame_samples,
                            "channels": self._channels,
                            "dtype": "float32",
                            "device": int(selected["index"]),
                            "callback": _callback,
                        }
                        self._stream = sd.InputStream(**stream_kwargs)
                        self._stream.start()
                    except Exception as e:
                        last_start_error = e
                        self._stream = None
                        continue

                    _audio_set_status(
                        capture_mode=capture_mode,
                        capture_running=True,
                        selected_device=selected["name"],
                        device_index=int(selected["index"]),
                        channels=int(self._channels),
                        sample_rate=int(self._sample_rate),
                        frame_samples=int(self._frame_samples),
                        last_error="",
                    )
                    print(
                        f"[Audio] capture ready: mode={capture_mode}, device={selected['name']}, "
                        f"rate={self._sample_rate}, ch={self._channels}, frame={self._frame_samples}"
                    )
                    return

            _audio_set_error(f"input_stream_start_failed: {last_start_error}")
            raise RuntimeError(f"input_stream_start_failed: {last_start_error}")

        def _append_chunk(self, chunk):
            if chunk is None:
                return
            if chunk.ndim == 1:
                chunk = chunk.reshape(-1, 1)
            if chunk.shape[1] > self._channels:
                chunk = chunk[:, :self._channels]
            elif chunk.shape[1] < self._channels:
                pad = np.zeros((chunk.shape[0], self._channels - chunk.shape[1]), dtype=np.int16)
                chunk = np.hstack([chunk, pad])

            if self._pending.size == 0:
                self._pending = chunk
            else:
                self._pending = np.vstack([self._pending, chunk])

            max_buffered = self._frame_samples * 20
            if self._pending.shape[0] > max_buffered:
                self._pending = self._pending[-max_buffered:, :]
                _audio_inc("dropped_frames", 1)

        def _pop_frame(self):
            if self._pending.shape[0] < self._frame_samples:
                return None
            frame = self._pending[:self._frame_samples, :]
            self._pending = self._pending[self._frame_samples:, :]
            return frame

        async def recv(self):
            self._ensure_capture()

            frame_data = self._pop_frame()
            while frame_data is None:
                if self._loopback_rec is not None:
                    try:
                        chunk = await asyncio.to_thread(
                            self._loopback_rec.record,
                            numframes=self._frame_samples,
                        )
                        pcm = np.asarray(chunk, dtype=np.float32)
                        if pcm.ndim == 1:
                            pcm = pcm.reshape(-1, 1)
                        if pcm.shape[1] > self._channels:
                            pcm = pcm[:, :self._channels]
                        elif pcm.shape[1] < self._channels:
                            pad = np.zeros((pcm.shape[0], self._channels - pcm.shape[1]), dtype=np.float32)
                            pcm = np.hstack([pcm, pad])
                        pcm = np.clip(pcm, -1.0, 1.0)
                        frame_data = (pcm * 32767.0).astype(np.int16, copy=False)
                        if frame_data.shape[0] < self._frame_samples:
                            pad = np.zeros((self._frame_samples - frame_data.shape[0], self._channels), dtype=np.int16)
                            frame_data = np.vstack([frame_data, pad])
                        elif frame_data.shape[0] > self._frame_samples:
                            frame_data = frame_data[:self._frame_samples, :]
                        break
                    except Exception as e:
                        frame_data = np.zeros((self._frame_samples, self._channels), dtype=np.int16)
                        _audio_inc("dropped_frames", 1)
                        _audio_set_error(f"loopback_record_failed_fill_silence: {e}")
                        break

                try:
                    chunk = await asyncio.to_thread(self._queue.get, True, 1.0)
                    self._append_chunk(chunk)
                    frame_data = self._pop_frame()
                except queue.Empty:
                    frame_data = np.zeros((self._frame_samples, self._channels), dtype=np.int16)
                    _audio_inc("dropped_frames", 1)
                    _audio_set_error("capture_timeout_fill_silence")
                    break

            rms = float(np.sqrt(np.mean((frame_data.astype(np.float32) / 32768.0) ** 2)))
            _audio_inc("frames_generated", 1)
            _audio_set_status(last_rms=rms, last_frame_ts=float(time.time()))

            layout = "stereo" if self._channels == 2 else "mono"
            # aiortc's Opus encoder expects packed s16 input.
            packed = np.ascontiguousarray(frame_data.reshape(1, -1))
            af = AudioFrame.from_ndarray(packed, format="s16", layout=layout)
            af.sample_rate = self._sample_rate
            af.pts = self._pts
            af.time_base = Fraction(1, self._sample_rate)
            self._pts += af.samples

            if self._wall_start is None:
                self._wall_start = time.time()
            else:
                target = self._wall_start + (self._pts / float(self._sample_rate))
                delay = target - time.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            return af

        def stop(self):
            self._closed = True
            stream = self._stream
            self._stream = None
            loopback_cm = self._loopback_cm
            self._loopback_cm = None
            self._loopback_rec = None
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            if loopback_cm is not None:
                try:
                    loopback_cm.__exit__(None, None, None)
                except Exception:
                    pass
            _audio_set_status(capture_running=False, capture_mode="")
            super().stop()

    class ScreenVideoTrack(VideoStreamTrack):
        def __init__(self, pump: WebRTCFramePump):
            super().__init__()
            self._pump = pump
            self._last = None
            self._last_vf = None
            self._blank_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            self._created_ts = float(time.time())
            self._last_pump_restart_ts = 0.0
            self._stale_count = 0
            self._clock_rate = 90000
            self._time_base = Fraction(1, self._clock_rate)
            self._timestamp = 0
            self._started_at_perf = None
            self._recv_window_start_perf = None
            self._recv_counter = 0
            self._recv_fps = 0.0
            self._last_recv_perf = None
            self._last_stats_push_perf = None

        async def recv(self):
            global webrtc_target_fps
            requested_fps = max(15, min(int(webrtc_fps_max), int(webrtc_target_fps)))
            # Keep sender cadence on requested FPS; frame pump always exposes latest frame.
            target_fps = requested_fps
            ts_catchup = _webrtc_sender_ts_get_factor()
            ticks_per_frame = max(1, int((self._clock_rate / target_fps) * ts_catchup))
            wait_s = 0.0
            now_perf = time.perf_counter()
            if self._started_at_perf is None:
                self._started_at_perf = now_perf
                self._timestamp = 0
            else:
                self._timestamp += ticks_per_frame
                target_time = self._started_at_perf + (self._timestamp / float(self._clock_rate))
                # Drop scheduling debt if loop falls too far behind.
                if target_time < (now_perf - 0.25):
                    self._started_at_perf = now_perf - (self._timestamp / float(self._clock_rate))
                    target_time = self._started_at_perf + (self._timestamp / float(self._clock_rate))
                wait_s = target_time - now_perf
            if wait_s > 0:
                await asyncio.sleep(wait_s)

            # If frame pump is stale for too long, restart capture backend.
            frame_age = self._pump.frame_age()
            capture_fps = float(self._pump.capture_fps())
            if frame_age == float("inf") and (time.time() - self._created_ts) < 3.0:
                frame_age = 0.0
            if frame_age > 3.0 and capture_fps < 1.0:
                self._stale_count += 1
            else:
                self._stale_count = 0
            if self._stale_count >= 3:
                now = time.time()
                if now - self._last_pump_restart_ts >= 6.0:
                    self._last_pump_restart_ts = now
                    self._stale_count = 0
                    self._pump.restart(f"stalled age={frame_age:.2f}s")

            latest = self._pump.get_latest()
            if latest is None:
                latest = self._last
            if latest is None:
                await asyncio.sleep(0.005)
                latest = self._pump.get_latest() or self._last

            if latest is None:
                latest = (self._blank_frame, "rgb24")

            if latest is self._last and self._last_vf is not None:
                vf = self._last_vf
            else:
                self._last = latest
                frame, pixel_format = latest
                vf = VideoFrame.from_ndarray(frame, format=(pixel_format or "rgb24"))
                self._last_vf = vf
            vf.pts = self._timestamp
            vf.time_base = self._time_base

            now_perf = time.perf_counter()
            interval_ms = 0.0
            if self._last_recv_perf is not None:
                interval_ms = max(0.0, (now_perf - self._last_recv_perf) * 1000.0)
            self._last_recv_perf = now_perf
            if self._recv_window_start_perf is None:
                self._recv_window_start_perf = now_perf
                self._recv_counter = 1
            else:
                self._recv_counter += 1
                window = now_perf - self._recv_window_start_perf
                if window >= 1.0:
                    self._recv_fps = float(self._recv_counter) / float(max(window, 1e-6))
                    self._recv_counter = 0
                    self._recv_window_start_perf = now_perf
            if (self._last_stats_push_perf is None) or ((now_perf - self._last_stats_push_perf) >= 0.5):
                self._last_stats_push_perf = now_perf
                _video_set_track_stats({
                    "recv_fps": round(float(self._recv_fps), 1),
                    "target_fps": int(target_fps),
                    "ts_catchup": round(float(ts_catchup), 3),
                    "frame_age_ms": round(float(frame_age) * 1000.0, 1) if frame_age != float("inf") else -1.0,
                    "wait_ms": round(float(max(wait_s, 0.0)) * 1000.0, 3),
                    "interval_ms": round(float(interval_ms), 3),
                })
            return vf


@app.route('/')
def index():
    """Render control page."""
    return render_template('index.html')


@app.route('/api/info')
def server_info():
    """Basic server info endpoint."""
    capture_fps = 0.0
    active_encoder = _get_active_video_encoder_name()
    if webrtc_frame_pump is not None:
        try:
            capture_fps = float(webrtc_frame_pump.capture_fps())
        except Exception:
            capture_fps = 0.0
    return {
        'ip': get_local_ip(),
        'port': 5000,
        'clients': connected_clients,
        'screen_size': pyautogui.size(),
        'quality': quality,
        'fps': fps,
        'mjpeg_enabled': False,
        'webrtc_capture_backend': 'dxgi' if dxgi_capture_enabled else 'mss',
        'dxgi_capture_target_fps': int(dxgi_capture_target_fps),
        'dxgi_output_color': str(dxgi_output_color),
        'webrtc_fps': webrtc_target_fps,
        'webrtc_fps_max': int(webrtc_fps_max),
        'webrtc_scale': webrtc_scale,
        'webrtc_bitrate_kbps': webrtc_target_bitrate_kbps,
        'webrtc_max_bitrate_kbps': int(webrtc_max_bitrate_kbps),
        'webrtc_start_bitrate_kbps': int(webrtc_start_bitrate_kbps),
        'webrtc_min_bitrate_kbps': int(webrtc_min_bitrate_kbps),
        'webrtc_min_bitrate_effective_kbps': int(_effective_webrtc_min_bitrate_kbps(webrtc_target_bitrate_kbps)),
        'webrtc_bitrate_scale': float(webrtc_bitrate_scale),
        'webrtc_force_h264_only': bool(webrtc_force_h264_only),
        'webrtc_video_pt_count': int(last_video_codec_policy.get('video_pt_count', 0) or 0),
        'webrtc_h264_pt_count': int(last_video_codec_policy.get('h264_pt_count', 0) or 0),
        'webrtc_h264_conservative_level': bool(webrtc_h264_conservative_level),
        'webrtc_h264_profile_level_id': str(last_h264_signal.get('profile_level_id', '') or ''),
        'webrtc_h264_max_fs': int(last_h264_signal.get('max_fs', 0) or 0),
        'webrtc_h264_max_mbps': int(last_h264_signal.get('max_mbps', 0) or 0),
        'webrtc_h264_signal_fps': int(last_h264_signal.get('signal_fps', 0) or 0),
        'capture_fps': round(capture_fps, 1),
        'capture_all_monitors': bool(capture_all_monitors),
        'video_encoder_active': active_encoder,
        'video_encoder_preferred': video_encoder_status.get('preferred', 'libx264'),
        'video_encoder_effective': active_encoder or video_encoder_status.get('preferred', 'libx264'),
        'video_encoders_available': list(video_encoder_status.get('available', [])),
        'video_hw_encoders_available': list(video_encoder_status.get('hardware_available', [])),
    }



@app.route('/api/audio_info')
@app.route('/audio_info')
def audio_info():
    devices = _audio_list_input_devices()
    loopback_speakers = _audio_list_loopback_speakers()
    loopback_outputs = _audio_list_wasapi_output_devices()
    status = _audio_snapshot()
    return {
        'enabled': bool(audio_enabled),
        'webrtc_available': bool(WEBRTC_AVAILABLE),
        'sounddevice_available': bool(SOUNDDEVICE_AVAILABLE),
        'soundcard_available': bool(SOUNDCARD_AVAILABLE),
        'device_name_hint': audio_device_name,
        'prefer_wasapi_loopback': bool(audio_prefer_wasapi_loopback),
        'sample_rate': int(audio_sample_rate),
        'channels': int(audio_channels),
        'frame_ms': int(audio_frame_ms),
        'frame_samples': int(audio_frame_samples),
        'status': status,
        'devices': devices,
        'loopback_speakers': loopback_speakers,
        'loopback_outputs': loopback_outputs,
    }


@app.route('/api/audio_health')
def audio_health():
    status = _audio_snapshot()
    client = status.get('client_stats') or {}
    up = bool(
        status.get('capture_running')
        and float(status.get('last_rms', 0.0)) > 0.00001
        and (time.time() - float(status.get('last_frame_ts', 0.0))) < 5.0
    )
    client_up = bool(
        float(client.get('bytes_received', 0.0)) > 0
        and (time.time() - float(client.get('ts', 0.0))) < 15.0
    )
    return {
        'up': bool(up),
        'client_up': bool(client_up),
        'capture_running': bool(status.get('capture_running')),
        'selected_device': status.get('selected_device'),
        'frames_generated': int(status.get('frames_generated', 0)),
        'dropped_frames': int(status.get('dropped_frames', 0)),
        'discontinuities': int(status.get('discontinuities', 0)),
        'last_rms': float(status.get('last_rms', 0.0)),
        'last_error': status.get('last_error', ''),
        'client_stats': client,
    }


@app.route('/api/video_health')
def video_health():
    capture_fps = 0.0
    if webrtc_frame_pump is not None:
        try:
            capture_fps = float(webrtc_frame_pump.capture_fps())
        except Exception:
            capture_fps = 0.0
    status = _video_snapshot()
    client = status.get('client_stats') or {}
    track = status.get('track_stats') or {}
    client_up = bool(
        float(client.get('bytes_received', 0.0)) > 0
        and (time.time() - float(client.get('ts', 0.0))) < 15.0
    )
    return {
        'capture_fps': float(round(capture_fps, 1)),
        'target_fps': int(webrtc_target_fps),
        'bitrate_kbps': int(webrtc_target_bitrate_kbps),
        'start_bitrate_kbps': int(webrtc_start_bitrate_kbps),
        'min_bitrate_kbps': int(_effective_webrtc_min_bitrate_kbps(webrtc_target_bitrate_kbps)),
        'encoder': _get_active_video_encoder_name() or video_encoder_status.get('preferred', ''),
        'client_up': bool(client_up),
        'track_stats': track,
        'client_stats': client,
    }
# Cleaned garbled comment.

@socketio.on('connect')
def handle_connect():
    """Client connected."""
    global connected_clients
    connected_clients += 1
    print(f"[Socket] client connected, connected_clients={connected_clients}")
    emit('connected', {
        'status': 'ok',
        'screen_width': pyautogui.size().width,
        'screen_height': pyautogui.size().height
    })
    emit('xinput_status', {'available': bool(XINPUT_AVAILABLE)})


@socketio.on('disconnect')
def handle_disconnect():
    """Cleaned garbled docstring."""
    global connected_clients
    connected_clients = max(0, connected_clients - 1)
    print(f"[Socket] client disconnected, connected_clients={connected_clients}")

    sid = request.sid
    _webrtc_sender_ts_remove_sid(str(sid or ""))
    try:
        snapshot = _video_snapshot()
        cstats = snapshot.get("client_stats") or {}
        if str(cstats.get("sid", "")) == str(sid):
            _video_set_client_stats({})
    except Exception:
        pass
    global xinput_pad, xinput_owner_sid, xinput_last_buttons
    if sid == xinput_owner_sid:
        with xinput_lock:
            try:
                if xinput_pad is not None:
                    xinput_pad.reset()
                    xinput_pad.update()
            except Exception:
                pass
            if xinput_state_queue:
                xinput_state_queue.clear()
            xinput_owner_sid = None
            xinput_last_buttons = 0
    if WEBRTC_AVAILABLE and sid in webrtc_peers and webrtc_loop is not None:
        asyncio.run_coroutine_threadsafe(_webrtc_close_peer(sid), webrtc_loop)


def ensure_webrtc_runtime():
    global webrtc_loop, webrtc_loop_thread, webrtc_frame_pump, dxgi_capture_enabled
    if not (WEBRTC_AVAILABLE and webrtc_enabled):
        return False

    if audio_enabled and (not SOUNDDEVICE_AVAILABLE or sd is None):
        _audio_set_error("sounddevice_unavailable")

    # Keep current capture mode; do not force-enable DXGI for WebRTC runtime.
    # Default MSS is more stable on some systems.
    if dxgi_capture_enabled and dxgi_camera is None:
        try:
            init_dxgi_camera()
        except Exception:
            pass

    if webrtc_loop is None:
        webrtc_loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(webrtc_loop)
            webrtc_loop.run_forever()

        webrtc_loop_thread = threading.Thread(target=_run, daemon=True)
        webrtc_loop_thread.start()

    if webrtc_frame_pump is None:
        webrtc_frame_pump = WebRTCFramePump()
        webrtc_frame_pump.start()
    else:
        # Recover if pump thread died unexpectedly.
        webrtc_frame_pump.start()

    return True


async def _webrtc_wait_ice_complete(pc: RTCPeerConnection, timeout_s: float = 2.0):
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def _on_state_change():
        if pc.iceGatheringState == "complete":
            done.set()

    try:
        await asyncio.wait_for(done.wait(), timeout=timeout_s)
    except Exception:
        return


def _webrtc_attach_track(pc: RTCPeerConnection, kind: str, track):
    for transceiver in pc.getTransceivers():
        if transceiver.kind != kind:
            continue
        try:
            # For recvonly offers from client, force answer direction to sendonly.
            transceiver.direction = "sendonly"
        except Exception:
            pass
        try:
            transceiver.sender.replaceTrack(track)
            return True
        except Exception:
            pass
    try:
        pc.addTrack(track)
        return True
    except Exception:
        return False


def _webrtc_apply_codec_preferences(pc: RTCPeerConnection):
    try:
        video_caps = RTCRtpSender.getCapabilities("video").codecs
        h264 = [c for c in video_caps if (c.name or "").upper() == "H264"]
        if h264:
            # Prefer constrained-baseline profile when both are available.
            h264.sort(
                key=lambda c: 0
                if str((c.parameters or {}).get("profile-level-id", "")).lower().startswith("42e0")
                else 1
            )
            for transceiver in pc.getTransceivers():
                if transceiver.kind == "video" and hasattr(transceiver, "setCodecPreferences"):
                    transceiver.setCodecPreferences(h264)
                    break
    except Exception:
        pass

    try:
        audio_caps = RTCRtpSender.getCapabilities("audio").codecs
        opus = [c for c in audio_caps if (c.name or "").upper() == "OPUS"]
        if opus:
            for transceiver in pc.getTransceivers():
                if transceiver.kind == "audio" and hasattr(transceiver, "setCodecPreferences"):
                    transceiver.setCodecPreferences(opus)
                    break
    except Exception:
        pass


def _h264_level_limits_for_target(target_w: int, target_h: int, target_fps: int):
    """Return (level_idc_hex, max_fs, max_mbps) for current target stream."""
    mb_w = max(1, int((target_w + 15) // 16))
    mb_h = max(1, int((target_h + 15) // 16))
    max_fs_needed = int(mb_w * mb_h)
    max_mbps_needed = int(max_fs_needed * max(15, int(target_fps)))

    # (level_idc_hex, max_fs, max_mbps)
    levels = [
        (0x1F, 3600, 108000),     # 3.1
        (0x28, 8192, 245760),     # 4.0
        (0x29, 8192, 245760),     # 4.1
        (0x2A, 8704, 522240),     # 4.2
        (0x32, 22080, 589824),    # 5.0
        (0x33, 36864, 983040),    # 5.1
        (0x34, 36864, 2073600),   # 5.2
    ]
    selected = levels[-1]
    for row in levels:
        _, fs_cap, mbps_cap = row
        if max_fs_needed <= fs_cap and max_mbps_needed <= mbps_cap:
            selected = row
            break

    # Cap signaled level at 5.1 for better mobile compatibility.
    if selected[0] > 0x33:
        selected = (0x33, 36864, 983040)
    return selected


def _h264_munge_fmtp_line(line: str, target_fps: int) -> str:
    global last_h264_signal
    try:
        screen = pyautogui.size()
        sw = int(screen.width)
        sh = int(screen.height)
    except Exception:
        sw = int(getattr(_screen_size, "width", 1920))
        sh = int(getattr(_screen_size, "height", 1080))

    scale = max(0.25, min(1.0, float(webrtc_scale)))
    target_w = max(320, min(int(webrtc_max_width), int(sw * scale)))
    target_h = max(240, min(int(webrtc_max_height), int(sh * scale)))

    # Signal up to 60fps capability for high-res H264 to avoid over-signaling 120fps.
    signal_fps = max(15, min(60, int(target_fps)))
    level_idc, max_fs, max_mbps = _h264_level_limits_for_target(target_w, target_h, signal_fps)

    if " " not in line:
        return line
    head, body = line.split(" ", 1)
    params = [tok.strip() for tok in body.split(";") if tok.strip()]

    def _get_param(key: str):
        key_l = key.lower()
        for token in params:
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            if k.strip().lower() == key_l:
                return k.strip(), v.strip()
        return None, None

    def _set_param(key: str, value: str):
        key_l = key.lower()
        for idx, token in enumerate(params):
            if "=" not in token:
                continue
            k, _ = token.split("=", 1)
            if k.strip().lower() == key_l:
                params[idx] = f"{k.strip()}={value}"
                return
        params.append(f"{key}={value}")

    # Conservative profile-level-id capping can hard-limit decode FPS at high resolutions.
    if webrtc_h264_conservative_level:
        signaled_level_idc = min(int(level_idc), 0x2A)  # up to Level 4.2
    else:
        signaled_level_idc = int(level_idc)
    profile_level_id = f"{webrtc_h264_profile_prefix}{signaled_level_idc:02x}"
    _set_param("profile-level-id", profile_level_id)

    _set_param("max-fs", str(max_fs))
    _set_param("max-mbps", str(max_mbps))
    _set_param("level-asymmetry-allowed", "1")
    _set_param("packetization-mode", "1")
    last_h264_signal = {
        "profile_level_id": profile_level_id,
        "level_idc": int(signaled_level_idc),
        "max_fs": int(max_fs),
        "max_mbps": int(max_mbps),
        "signal_fps": int(signal_fps),
        "target_w": int(target_w),
        "target_h": int(target_h),
    }
    return f"{head} {';'.join(params)}"


def _webrtc_munge_answer_sdp(sdp: str, bitrate_kbps: int, target_fps: int) -> str:
    """Inject video bitrate/fps hints into SDP answer."""
    bitrate_kbps = max(500, min(int(webrtc_max_bitrate_kbps), int(bitrate_kbps)))
    start_bitrate_kbps = max(500, min(int(bitrate_kbps), int(webrtc_start_bitrate_kbps)))
    min_bitrate_kbps = max(300, min(int(bitrate_kbps), int(_effective_webrtc_min_bitrate_kbps(bitrate_kbps))))
    # Keep SDP framerate hint aligned with codec pipeline capability.
    target_fps = max(15, min(120, int(target_fps)))
    sdp_fps_hint = max(15, min(60, int(target_fps)))

    lines = sdp.splitlines()
    out = []
    in_video = False
    framerate_set = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if stripped.startswith("m="):
            if in_video and not framerate_set:
                out.append(f"a=framerate:{sdp_fps_hint}")
            in_video = stripped.startswith("m=video")
            framerate_set = False
            out.append(line)
            if in_video:
                out.append(f"b=AS:{bitrate_kbps}")
                out.append(f"b=TIAS:{bitrate_kbps * 1000}")
            continue

        if in_video:
            if lower.startswith("b=as:") or lower.startswith("b=tias:"):
                continue
            if lower.startswith("a=framerate:"):
                out.append(f"a=framerate:{sdp_fps_hint}")
                framerate_set = True
                continue
            if lower.startswith("a=fmtp:"):
                is_h264_fmtp = ("profile-level-id=" in lower) or ("packetization-mode=" in lower)
                if is_h264_fmtp:
                    line = _h264_munge_fmtp_line(line, target_fps=target_fps)
                    line_lower = line.strip().lower()
                    extras = []
                    if "x-google-start-bitrate=" not in line_lower:
                        extras.append(f"x-google-start-bitrate={start_bitrate_kbps}")
                    if "x-google-max-bitrate=" not in line_lower:
                        extras.append(f"x-google-max-bitrate={bitrate_kbps}")
                    if "x-google-min-bitrate=" not in line_lower:
                        extras.append(f"x-google-min-bitrate={min_bitrate_kbps}")
                    if extras:
                        line = f"{line};{';'.join(extras)}"
            out.append(line)
            continue

        out.append(line)

    if in_video and not framerate_set:
        out.append(f"a=framerate:{sdp_fps_hint}")

    sep = "\r\n" if "\r\n" in sdp else "\n"
    return sep.join(out) + sep


def _webrtc_force_h264_video_only(sdp: str) -> str:
    """Keep only H264 (and its RTX payloads) in video m-sections."""
    global last_video_codec_policy
    sep = "\r\n" if "\r\n" in sdp else "\n"
    lines = sdp.splitlines()
    if not lines:
        return sdp

    out = []
    i = 0
    total_video_pts = 0
    total_h264_pts = 0
    changed = False

    while i < len(lines):
        line = lines[i]
        if not line.startswith("m="):
            out.append(line)
            i += 1
            continue

        j = i + 1
        while j < len(lines) and not lines[j].startswith("m="):
            j += 1
        section = lines[i:j]
        mline = section[0]

        if not mline.startswith("m=video "):
            out.extend(section)
            i = j
            continue

        parts = mline.split()
        if len(parts) < 4:
            out.extend(section)
            i = j
            continue

        pts = parts[3:]
        total_video_pts += len(pts)

        codec_by_pt = {}
        apt_by_pt = {}
        for sline in section[1:]:
            lower = sline.lower()
            if lower.startswith("a=rtpmap:"):
                body = sline[9:]
                if " " not in body:
                    continue
                pt, spec = body.split(" ", 1)
                codec_name = spec.split("/", 1)[0].strip().upper()
                codec_by_pt[pt.strip()] = codec_name
            elif lower.startswith("a=fmtp:"):
                body = sline[7:]
                if " " not in body:
                    continue
                pt, attrs = body.split(" ", 1)
                pt = pt.strip()
                for token in attrs.split(";"):
                    tok = token.strip().lower()
                    if tok.startswith("apt="):
                        apt_by_pt[pt] = tok.split("=", 1)[1].strip()
                        break

        keep_h264 = [pt for pt in pts if codec_by_pt.get(pt, "") == "H264"]
        if not keep_h264:
            out.extend(section)
            i = j
            continue
        total_h264_pts += len(keep_h264)

        keep_set = set(keep_h264)
        for pt in pts:
            if codec_by_pt.get(pt, "") == "RTX" and apt_by_pt.get(pt, "") in keep_set:
                keep_set.add(pt)
        keep_ordered = [pt for pt in pts if pt in keep_set]
        if not keep_ordered:
            out.extend(section)
            i = j
            continue

        new_mline = " ".join(parts[:3] + keep_ordered)
        out.append(new_mline)
        if new_mline != mline:
            changed = True

        for sline in section[1:]:
            lower = sline.lower()
            if lower.startswith("a=rtpmap:") or lower.startswith("a=fmtp:") or lower.startswith("a=rtcp-fb:"):
                body = sline.split(":", 1)[1]
                pt = body.split(" ", 1)[0].strip()
                if pt not in keep_set:
                    changed = True
                    continue
            out.append(sline)

        i = j

    last_video_codec_policy = {
        "h264_only": True,
        "video_pt_count": int(total_video_pts),
        "h264_pt_count": int(total_h264_pts),
    }
    if not changed:
        return sdp
    return sep.join(out) + sep


async def _webrtc_close_peer(sid: str, keep_frame_pump: bool = False):
    global webrtc_frame_pump
    _webrtc_sender_ts_remove_sid(str(sid or ""))
    audio_track = webrtc_audio_tracks.pop(sid, None)
    if audio_track is not None:
        try:
            audio_track.stop()
        except Exception:
            pass

    pc = webrtc_peers.pop(sid, None)
    if pc:
        try:
            await pc.close()
        except Exception:
            pass

    if (not keep_frame_pump) and (not webrtc_peers) and webrtc_frame_pump is not None:
        try:
            webrtc_frame_pump.stop()
        except Exception:
            pass
        webrtc_frame_pump = None


async def _webrtc_handle_offer(sid: str, offer_sdp: str, offer_type: str):
    # Replace existing peer for this sid, but keep frame pump alive during renegotiation.
    await _webrtc_close_peer(sid, keep_frame_pump=True)

    pc = RTCPeerConnection()
    webrtc_peers[sid] = pc

    @pc.on("connectionstatechange")
    async def _on_connection_state_change():
        # "disconnected" can be transient on Wi-Fi; avoid tearing down immediately.
        if pc.connectionState in ("failed", "closed"):
            await _webrtc_close_peer(sid)
    try:
        if webrtc_force_h264_only:
            offer_sdp = _webrtc_force_h264_video_only(offer_sdp)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type=offer_type))

        if webrtc_frame_pump is not None:
            video_track = ScreenVideoTrack(webrtc_frame_pump)
            _webrtc_attach_track(pc, "video", video_track)

        if audio_enabled:
            if SOUNDDEVICE_AVAILABLE and WEBRTC_AVAILABLE:
                try:
                    audio_track = SystemAudioTrack()
                    if _webrtc_attach_track(pc, "audio", audio_track):
                        webrtc_audio_tracks[sid] = audio_track
                        print("[Audio] WebRTC track attached")
                    else:
                        audio_track.stop()
                        _audio_set_error("attach_audio_track_failed")
                except Exception as e:
                    _audio_set_status(capture_running=False)
                    _audio_set_error(f"audio_track_init_failed: {e}")
                    print(f"[Audio] track init failed: {e}")
            else:
                _audio_set_error("sounddevice_unavailable")

        _webrtc_apply_codec_preferences(pc)

        _sync_webrtc_bitrate_target()
        answer = await pc.createAnswer()
        answer_sdp = _webrtc_munge_answer_sdp(
            answer.sdp,
            bitrate_kbps=webrtc_target_bitrate_kbps,
            target_fps=webrtc_target_fps,
        )
        if webrtc_force_h264_only:
            answer_sdp = _webrtc_force_h264_video_only(answer_sdp)
        try:
            for _line in answer_sdp.splitlines():
                _lower = _line.strip().lower()
                if _lower.startswith("a=fmtp:") and "profile-level-id=" in _lower:
                    print(f"[WebRTC] answer video fmtp: {_line.strip()}")
                    break
            _video_section = False
            _printed_rtpmap = False
            for _line in answer_sdp.splitlines():
                _stripped = _line.strip()
                if _stripped.startswith("m="):
                    if _video_section and _printed_rtpmap:
                        break
                    _video_section = _stripped.startswith("m=video ")
                    if _video_section:
                        print(f"[WebRTC] answer video m-line: {_stripped}")
                    continue
                if _video_section and _stripped.lower().startswith("a=rtpmap:") and not _printed_rtpmap:
                    print(f"[WebRTC] answer first rtpmap: {_stripped}")
                    _printed_rtpmap = True
        except Exception:
            pass
        await pc.setLocalDescription(RTCSessionDescription(sdp=answer_sdp, type=answer.type))
        await _webrtc_wait_ice_complete(pc)
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    except Exception:
        await _webrtc_close_peer(sid, keep_frame_pump=True)
        raise


@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    if not ensure_webrtc_runtime():
        emit('webrtc_error', {'error': 'webrtc_not_available'})
        return

    sid = request.sid
    offer_sdp = data.get('sdp', '')
    offer_type = data.get('type', 'offer')
    if not offer_sdp:
        emit('webrtc_error', {'error': 'empty_offer'})
        return

    fut = asyncio.run_coroutine_threadsafe(_webrtc_handle_offer(sid, offer_sdp, offer_type), webrtc_loop)
    try:
        answer = fut.result(timeout=15)
        emit('webrtc_answer', answer)
    except Exception as e:
        try:
            asyncio.run_coroutine_threadsafe(_webrtc_close_peer(sid, keep_frame_pump=True), webrtc_loop)
        except Exception:
            pass
        emit('webrtc_error', {'error': str(e)})


@socketio.on('audio_client_stats')
def handle_audio_client_stats(data):
    if not isinstance(data, dict):
        return
    cleaned = {
        'sid': request.sid,
        'ts': float(time.time()),
        'bytes_received': float(data.get('bytes_received', 0.0) or 0.0),
        'packets_lost': int(data.get('packets_lost', 0) or 0),
        'jitter_ms': float(data.get('jitter_ms', 0.0) or 0.0),
        'audio_level': float(data.get('audio_level', 0.0) or 0.0),
        'playing': bool(data.get('playing', False)),
        'unlocked': bool(data.get('unlocked', False)),
        'error': str(data.get('error', '') or ''),
    }
    _audio_set_status(client_stats=cleaned)


@socketio.on('video_client_stats')
def handle_video_client_stats(data):
    if not isinstance(data, dict):
        return
    cleaned = {
        'bytes_received': float(data.get('bytes_received', 0.0) or 0.0),
        'packets_lost': int(data.get('packets_lost', 0) or 0),
        'frames_decoded': int(data.get('frames_decoded', 0) or 0),
        'frames_dropped': int(data.get('frames_dropped', 0) or 0),
        'frames_received': int(data.get('frames_received', 0) or 0),
        'frames_backlog': float(data.get('frames_backlog', 0.0) or 0.0),
        'frames_per_second': float(data.get('frames_per_second', 0.0) or 0.0),
        'decode_ms': float(data.get('decode_ms', 0.0) or 0.0),
        'jitter_ms': float(data.get('jitter_ms', 0.0) or 0.0),
        'playout_delay_ms': float(data.get('playout_delay_ms', 0.0) or 0.0),
        'playout_delay_ewma_ms': float(data.get('playout_delay_ewma_ms', 0.0) or 0.0),
        'processing_delay_ms': float(data.get('processing_delay_ms', 0.0) or 0.0),
        'playback_rate': float(data.get('playback_rate', 1.0) or 1.0),
        'codec': str(data.get('codec', '') or ''),
        'decoder_impl': str(data.get('decoder_impl', '') or ''),
        'power_efficient': bool(data.get('power_efficient', False)),
        'client_build': str(data.get('client_build', '') or '')[:64],
        'sid': request.sid,
        'ts': time.time(),
    }
    _video_set_client_stats(cleaned)
    _webrtc_sender_ts_update_from_client_stats(cleaned)


@socketio.on('set_mode')
def handle_set_mode(data):
    """Switch client control mode."""
    global game_mode
    mode = data.get('mode', 'touch')

    if mode == 'gamepad':
        game_mode = True
        debug_log(f"[Mode] gamepad enabled, input_sender={input_sender is not None}")
    else:
        game_mode = False
        debug_log(f"[Mode] switched to {mode}")

    emit('mode_changed', {'mode': mode, 'game_mode': game_mode})


@socketio.on('mouse_move')
def handle_mouse_move(data):
    """Cleaned garbled docstring."""
    try:
        x = data.get('x', 0)
        y = data.get('y', 0)
        # Cleaned garbled comment.
        screen_width, screen_height = pyautogui.size()
        x = max(0, min(x, screen_width))
        y = max(0, min(y, screen_height))

        if game_mode and input_sender:
            input_sender.move_absolute(x, y)
        elif input_sender:
            # Cleaned garbled comment.
            if not input_sender.set_mouse_pos(x, y):
                # Cleaned garbled comment.
                pyautogui.moveTo(x, y, duration=0)
        else:
            pyautogui.moveTo(x, y, duration=0)
    except Exception as e:
        print(f"Mouse move error: {e}")


@socketio.on('mouse_move_relative')
def handle_mouse_move_relative(data):
    """Handle relative mouse movement."""
    global game_mode
    try:
        dx = data.get('dx', 0)
        dy = data.get('dy', 0)
        raw = data.get('raw', None)
        raw_input = bool(game_mode) if raw is None else bool(raw)
        if input_sender:
            input_sender.move_relative(dx, dy, raw_input=raw_input)
        else:
            pyautogui.moveRel(dx, dy, duration=0)
    except Exception as e:
        print(f"Relative mouse move error: {e}")


@socketio.on('get_mouse_pos')
def handle_get_mouse_pos(sid=None):
    """Cleaned garbled docstring."""
    try:
        if input_sender:
            x, y = input_sender.get_mouse_pos()
        else:
            x, y = pyautogui.position()
        emit('mouse_pos', {'x': x, 'y': y})
    except Exception as e:
        print(f"Get mouse position error: {e}")


@socketio.on('mouse_click')
def handle_mouse_click(data):
    """Cleaned garbled docstring."""
    try:
        button = data.get('button', 'left')
        action = data.get('action', 'down')

        if input_sender:
            if action == 'down':
                if button == 'left':
                    input_sender.left_down()
                elif button == 'right':
                    input_sender.right_down()
                elif button == 'middle':
                    input_sender.middle_down()
            else:
                if button == 'left':
                    input_sender.left_up()
                elif button == 'right':
                    input_sender.right_up()
                elif button == 'middle':
                    input_sender.middle_up()
        else:
            if action == 'down':
                pyautogui.mouseDown(button=button)
            else:
                pyautogui.mouseUp(button=button)
    except Exception as e:
        print(f"Mouse click error: {e}")


@socketio.on('mouse_scroll')
def handle_mouse_scroll(data):
    """Cleaned garbled docstring."""
    try:
        dx = data.get('dx', 0)
        dy = data.get('dy', 0)

        if game_mode and input_sender:
            input_sender.scroll(dy, dx)
        else:
            # Cleaned garbled comment.
            if dy != 0:
                pyautogui.scroll(int(dy))
            # Cleaned garbled comment.
            if dx != 0:
                pyautogui.hscroll(int(dx))
    except Exception as e:
        print(f"Mouse scroll error: {e}")


@socketio.on('key_event')
def handle_key_event(data):
    """Cleaned garbled docstring."""
    try:
        key = data.get('key', '')
        action = data.get('action', 'down')

        # Cleaned garbled comment.
        key_map = {
            'Enter': 'return',
            'Return': 'return',
            'Space': 'space',
            'Spacebar': 'space',
            'Tab': 'tab',
            'Backspace': 'backspace',
            'Delete': 'delete',
            'Escape': 'esc',
            'Esc': 'esc',
            'ArrowUp': 'up',
            'ArrowDown': 'down',
            'ArrowLeft': 'left',
            'ArrowRight': 'right',
            'Control': 'ctrl',
            'Ctrl': 'ctrl',
            'Alt': 'alt',
            'Shift': 'shift',
            'Meta': 'win',
            'Windows': 'win',
            'Win': 'win',
            'OS': 'win',
            'Super': 'win',
            'Home': 'home',
            'End': 'end',
            'PageUp': 'pageup',
            'PageDown': 'pagedown',
            'Insert': 'insert',
            'CapsLock': 'capslock',
            'NumLock': 'numlock',
            'ScrollLock': 'scrolllock',
            'PrintScreen': 'printscreen',
            'Pause': 'pause',
            'ContextMenu': 'contextmenu',
            'Apps': 'contextmenu',
        }

        for i in range(1, 25):
            key_map[f'F{i}'] = f'f{i}'

        mapped_key = key_map.get(key, key)

        if input_sender:
            if action == 'down':
                input_sender.key_down(mapped_key)
            else:
                input_sender.key_up(mapped_key)
        else:
            if len(mapped_key) == 1 or mapped_key in key_map.values():
                if action == 'down':
                    pyautogui.keyDown(mapped_key)
                else:
                    pyautogui.keyUp(mapped_key)
    except Exception as e:
        print(f"Keyboard event error: {e}")


# Cleaned garbled comment.
wasd_state = {'w': False, 'a': False, 's': False, 'd': False}

def send_key(key, down):
    """Send key press/release through the selected input backend."""
    if input_sender:
        if down:
            input_sender.key_down(key)
        else:
            input_sender.key_up(key)
    else:
        if down:
            pyautogui.keyDown(key)
        else:
            pyautogui.keyUp(key)


def _xinput_worker_loop():
    global xinput_pad, xinput_last_buttons
    global xinput_apply_count, xinput_apply_nonzero, xinput_apply_last_log
    while True:
        xinput_state_event.wait()
        while True:
            with xinput_lock:
                if not xinput_state_queue:
                    xinput_state_event.clear()
                    break
                item = xinput_state_queue.popleft()
            sid, payload = item
            pad = _xinput_ensure_for_sid(sid)
            if pad is None:
                continue
            ok = _xinput_apply_state(pad, payload or {})
            if ok:
                xinput_apply_count += 1
                if payload:
                    if int(payload.get('buttons', 0) or 0) != 0 or \
                       int(payload.get('lt', 0) or 0) != 0 or \
                       int(payload.get('rt', 0) or 0) != 0 or \
                       int(payload.get('lx', 0) or 0) != 0 or \
                       int(payload.get('ly', 0) or 0) != 0 or \
                       int(payload.get('rx', 0) or 0) != 0 or \
                       int(payload.get('ry', 0) or 0) != 0:
                        xinput_apply_nonzero += 1
                now = time.time()
                if now - xinput_apply_last_log >= 1.0:
                    debug_log(f"[XInput] applied {xinput_apply_count}/s, non-zero {xinput_apply_nonzero}/s")
                    xinput_apply_last_log = now
                    xinput_apply_count = 0
                    xinput_apply_nonzero = 0
            if not ok:
                with xinput_lock:
                    if xinput_pad is pad:
                        try:
                            xinput_pad.reset()
                            xinput_pad.update()
                        except Exception:
                            pass
                        xinput_pad = None
                        xinput_last_buttons = 0


def _xinput_start_worker_once():
    global xinput_worker_started
    with xinput_lock:
        if xinput_worker_started:
            return
        t = threading.Thread(target=_xinput_worker_loop, daemon=True, name="XInputWorker")
        t.start()
        xinput_worker_started = True


def _xinput_clamp_i16(v):
    try:
        x = int(v)
    except Exception:
        x = 0
    return max(-32768, min(32767, x))


def _xinput_clamp_u8(v):
    try:
        x = int(v)
    except Exception:
        x = 0
    return max(0, min(255, x))


_XINPUT_BUTTON_MAP = {
    0x0001: lambda: XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    0x0002: lambda: XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    0x0004: lambda: XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    0x0008: lambda: XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    0x0010: lambda: XUSB_BUTTON.XUSB_GAMEPAD_START,
    0x0020: lambda: XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    0x0040: lambda: XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    0x0080: lambda: XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    0x0100: lambda: XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    0x0200: lambda: XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    0x0400: lambda: XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
    0x1000: lambda: XUSB_BUTTON.XUSB_GAMEPAD_A,
    0x2000: lambda: XUSB_BUTTON.XUSB_GAMEPAD_B,
    0x4000: lambda: XUSB_BUTTON.XUSB_GAMEPAD_X,
    0x8000: lambda: XUSB_BUTTON.XUSB_GAMEPAD_Y,
}


def _xinput_ensure_for_sid(sid):
    global xinput_pad, xinput_owner_sid, xinput_last_buttons
    if not XINPUT_AVAILABLE or vg is None or XUSB_BUTTON is None:
        return None
    with xinput_lock:
        if xinput_pad is None:
            try:
                xinput_pad = vg.VX360Gamepad()
            except Exception as e:
                print(f"[Gamepad] virtual controller creation failed: {e}")
                xinput_pad = None
                xinput_owner_sid = None
                xinput_last_buttons = 0
                return None
            try:
                xinput_pad.reset()
                xinput_pad.update()
            except Exception:
                pass
        if xinput_owner_sid != sid:
            # Cleaned garbled comment.
            try:
                xinput_pad.reset()
                xinput_pad.update()
            except Exception:
                pass
            xinput_owner_sid = sid
            xinput_last_buttons = 0
        return xinput_pad


def _xinput_apply_state(pad, payload):
    global xinput_last_buttons

    lx = _xinput_clamp_i16(payload.get('lx', 0))
    ly = _xinput_clamp_i16(payload.get('ly', 0))
    rx = _xinput_clamp_i16(payload.get('rx', 0))
    ry = _xinput_clamp_i16(payload.get('ry', 0))
    lt = _xinput_clamp_u8(payload.get('lt', 0))
    rt = _xinput_clamp_u8(payload.get('rt', 0))
    buttons = payload.get('buttons', 0)
    try:
        buttons = int(buttons)
    except Exception:
        buttons = 0

    try:
        pad.left_joystick(x_value=lx, y_value=ly)
        pad.right_joystick(x_value=rx, y_value=ry)
        pad.left_trigger(value=lt)
        pad.right_trigger(value=rt)
    except Exception as e:
        print(f"[Gamepad] failed to set stick/trigger state: {e}")
        return False

    prev = xinput_last_buttons
    for bit, btn_factory in _XINPUT_BUTTON_MAP.items():
        try:
            btn = btn_factory()
        except Exception:
            continue
        was = (prev & bit) != 0
        now = (buttons & bit) != 0
        if now and not was:
            try:
                pad.press_button(button=btn)
            except Exception:
                pass
        elif was and not now:
            try:
                pad.release_button(button=btn)
            except Exception:
                pass

    xinput_last_buttons = buttons
    try:
        pad.update()
    except Exception as e:
        print(f"[Gamepad] failed to submit controller state: {e}")
        return False
    return True


@socketio.on('xinput_connect')
def handle_xinput_connect(data):
    sid = request.sid
    if not XINPUT_AVAILABLE:
        emit('xinput_status', {'available': False})
        return
    _xinput_start_worker_once()
    pad = _xinput_ensure_for_sid(sid)
    if pad is None:
        emit('xinput_status', {'available': False})
        return
    emit('xinput_status', {'available': True})


@socketio.on('xinput_disconnect')
def handle_xinput_disconnect(data=None):
    sid = request.sid
    global xinput_pad, xinput_owner_sid, xinput_last_buttons
    with xinput_lock:
        if xinput_owner_sid != sid:
            return
        try:
            if xinput_pad is not None:
                xinput_pad.reset()
                xinput_pad.update()
        except Exception:
            pass
        if xinput_state_queue:
            xinput_state_queue.clear()
        xinput_owner_sid = None
        xinput_last_buttons = 0


@socketio.on('xinput_state')
def handle_xinput_state(data):
    sid = request.sid
    global xinput_state_count, xinput_state_last_log
    _xinput_start_worker_once()
    xinput_state_count += 1
    now = time.time()
    if now - xinput_state_last_log >= 1.0:
        debug_log(f"[XInput] recv {xinput_state_count}/s, owner={xinput_owner_sid == sid}")
        xinput_state_last_log = now
        xinput_state_count = 0
    with xinput_lock:
        xinput_state_queue.append((sid, data or {}))
    xinput_state_event.set()

@socketio.on('gamepad_input')
def handle_gamepad(data):
    """Cleaned garbled docstring."""
    global wasd_state
    try:
        # Cleaned garbled comment.
        if data.get('type') == 'movement':
            x = data.get('x', 0)  # Cleaned garbled comment.
            y = data.get('y', 0)  # Cleaned garbled comment.

            # Cleaned garbled comment.
            deadzone = 0.3

            new_w = y < -deadzone
            new_s = y > deadzone
            new_a = x < -deadzone
            new_d = x > deadzone

            # Cleaned garbled comment.
            if new_w != wasd_state['w']:
                send_key('w', new_w)
                wasd_state['w'] = new_w
            if new_s != wasd_state['s']:
                send_key('s', new_s)
                wasd_state['s'] = new_s
            if new_a != wasd_state['a']:
                send_key('a', new_a)
                wasd_state['a'] = new_a
            if new_d != wasd_state['d']:
                send_key('d', new_d)
                wasd_state['d'] = new_d

        # Cleaned garbled comment.
        elif data.get('type') == 'action':
            button = data.get('button')
            pressed = data.get('pressed', False)

            key = None
            if button == 'A':
                key = 'space'  # Cleaned garbled comment.
            elif button == 'B':
                key = 'esc'  # Cleaned garbled comment.
            elif button == 'X':
                key = 'e'  # Cleaned garbled comment.
            elif button == 'Y':
                key = 'r'  # Cleaned garbled comment.

            if key:
                send_key(key, pressed)

    except Exception as e:
        print(f"Gamepad input error: {e}")


@socketio.on('set_quality')
def handle_set_quality(data, sid=None):
    """Cleaned garbled docstring."""
    global quality
    new_quality = max(10, min(95, data.get('quality', 60)))
    quality = new_quality
    bitrate_kbps = _sync_webrtc_bitrate_target()
    print(f"[Settings] quality updated: {quality}, webrtc_bitrate={bitrate_kbps}kbps")
    emit('quality_updated', {'quality': quality, 'webrtc_bitrate_kbps': bitrate_kbps})


@socketio.on('set_fps')
def handle_set_fps(data, sid=None):
    """Cleaned garbled docstring."""
    global fps, webrtc_target_fps
    try:
        requested_fps = int(data.get('fps', webrtc_target_fps))
    except Exception:
        requested_fps = int(webrtc_target_fps)
    new_fps = max(15, min(int(webrtc_fps_max), requested_fps))
    unchanged = (int(fps) == int(new_fps) and int(webrtc_target_fps) == int(new_fps))
    fps = new_fps
    webrtc_target_fps = new_fps
    if not unchanged and dxgi_capture_enabled and dxgi_camera is not None:
        reconfigure_dxgi_capture_fps()

    bitrate_kbps = _sync_webrtc_bitrate_target()
    if not unchanged:
        print(f"[Settings] FPS updated: {fps}, webrtc_bitrate={bitrate_kbps}kbps")
    emit('fps_updated', {
        'fps': fps,
        'webrtc_fps': webrtc_target_fps,
        'webrtc_fps_max': int(webrtc_fps_max),
        'webrtc_bitrate_kbps': bitrate_kbps
    })


@socketio.on('set_webrtc_scale')
def handle_set_webrtc_scale(data):
    global webrtc_scale
    try:
        scale = float(data.get('scale', webrtc_scale))
    except Exception:
        scale = webrtc_scale

    webrtc_scale = max(0.25, min(1.0, float(scale)))
    bitrate_kbps = _sync_webrtc_bitrate_target()
    emit('webrtc_scale_updated', {'scale': webrtc_scale, 'webrtc_bitrate_kbps': bitrate_kbps})


@socketio.on('set_capture_mode')
def handle_set_capture_mode(data):
    """Cleaned garbled docstring."""
    global dxgi_capture_enabled, dxgi_failure_count, dxgi_retry_after, dxgi_hard_disabled
    mode = data.get('mode', 'auto')

    if mode == 'dxgi':
        dxgi_hard_disabled = False
        dxgi_retry_after = 0.0
        dxgi_failure_count = 0
        dxgi_capture_enabled = init_dxgi_camera()
        if dxgi_capture_enabled:
            emit('capture_mode_updated', {'mode': 'dxgi', 'status': 'ok'})
        else:
            emit('capture_mode_updated', {'mode': 'mss', 'status': 'error', 'message': 'DXGI init failed'})
    elif mode == 'mss':
        dxgi_capture_enabled = False
        release_dxgi_camera()
        emit('capture_mode_updated', {'mode': 'mss', 'status': 'ok'})
    else:  # auto
        dxgi_hard_disabled = False
        dxgi_capture_enabled = True
        ok = init_dxgi_camera()
        emit('capture_mode_updated', {'mode': 'dxgi' if ok else 'mss', 'status': 'ok'})


@socketio.on('get_capture_info')
def handle_get_capture_info():
    """Return current capture mode info."""
    emit('capture_info', {
        'mode': 'dxgi' if dxgi_camera else 'mss',
        'dxgi_available': dxcam is not None,
        'dxgi_active': dxgi_camera is not None
    })


# Cleaned garbled comment.

def main():
    ip = get_local_ip()
    port = 5000

    # Cleaned garbled comment.
    use_dxgi = '--dxgi' in sys.argv

    # Performance default: try DXGI unless explicitly configured as MSS only.
    if use_dxgi or dxgi_capture_enabled:
        print("[Startup] trying DXGI capture mode...")
        ok = init_dxgi_camera()
        if not ok and webrtc_capture_backend == "dxgi":
            print("[Startup] DXGI forced but init failed, fallback to MSS disabled by config.")

    print("=" * 50)
    print("    Remote control server started")
    print("=" * 50)
    print(f"  Host IP: {ip}")
    print(f"  Port: {port}")
    print(f"  Screen size: {pyautogui.size()}")
    print(f"  Capture backend pref: {webrtc_capture_backend}")
    print(f"  Capture mode: {'DXGI (hardware)' if dxgi_camera else 'MSS (software)'}")
    print(f"  Video encoder preferred: {video_encoder_status.get('preferred', 'libx264')}")
    print(f"  Video HW encoders: {video_encoder_status.get('hardware_available', [])}")
    print(f"  Audio: {'ON' if audio_enabled else 'OFF'}")
    print(f"  Audio device hint: {audio_device_name or '(auto)'}")
    print("-" * 50)
    print(f"  Control UI: http://{ip}:{port}")
    print(f"  Audio info: http://{ip}:{port}/api/audio_info")
    print(f"  Audio health: http://{ip}:{port}/api/audio_health")
    print("=" * 50)
    print("\nMake sure tablet and PC are on the same Wi-Fi/LAN.")
    print("Open the Control UI URL above from the tablet browser.")
    if dxgi_camera:
        print("\n[Hint] DXGI capture enabled; run as admin to capture UAC prompts.")
    else:
        print("\n[Hint] DXGI init failed, running MSS fallback.")
    print()

    try:
        # Cleaned garbled comment.
        socketio.run(
            app,
            host='0.0.0.0',
            port=port,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )
    finally:
        # Cleaned garbled comment.
        for sid, track in list(webrtc_audio_tracks.items()):
            try:
                track.stop()
            except Exception:
                pass
        webrtc_audio_tracks.clear()
        release_dxgi_camera()


if __name__ == '__main__':
    main()


