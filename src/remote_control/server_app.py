#!/usr/bin/env python3
"""
Remote control server for Windows hosts.
Provides screen capture and input control over web.
"""

import asyncio
import base64
import ctypes
import io
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
dxcam = None

def load_dxcam():
    """Lazy-load dxcam to avoid startup-time import crashes."""
    global DXCAM_AVAILABLE, dxcam
    try:
        import warnings
        warnings.filterwarnings('ignore')
        import dxcam as dx
        dxcam = dx
        DXCAM_AVAILABLE = True
        return True
    except Exception as e:
        print(f"[DXGI] load failed: {e}")
        return False

# Cleaned garbled comment.
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"[Error] Failed to import Pillow: {e}")
    print("Run: python -m pip install Pillow")
    exit(1)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VENDOR_DIR = os.path.join(PROJECT_ROOT, "vendor", "py312")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

from flask import Flask, Response, render_template, request
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

# Cleaned garbled comment.
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATE_DIR)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False)

SOUNDDEVICE_AVAILABLE = False
sd = None
try:
    import sounddevice as _sd
    sd = _sd
    SOUNDDEVICE_AVAILABLE = True
except Exception as e:
    print(f"[Audio] sounddevice load failed: {e}")

# Cleaned garbled comment.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

# Cleaned garbled comment.
connected_clients = 0
screen_capture_running = False
quality = 60  # Cleaned garbled comment.
fps = 30  # Cleaned garbled comment.

webrtc_enabled = True
webrtc_target_fps = _env_int("RC_WEBRTC_FPS", 24, 5, 60)
_screen_size = pyautogui.size()
webrtc_scale = _env_float("RC_WEBRTC_SCALE", 1.0, 0.25, 1.0)
webrtc_max_width = _env_int("RC_WEBRTC_MAX_WIDTH", int(_screen_size.width), 320, 7680)
webrtc_max_height = _env_int("RC_WEBRTC_MAX_HEIGHT", int(_screen_size.height), 240, 4320)
webrtc_peers = {}
webrtc_audio_tracks = {}
webrtc_loop = None
webrtc_loop_thread = None
webrtc_frame_pump = None

audio_enabled = _env_flag("RC_AUDIO_ENABLED", True)
audio_device_name = (os.getenv("RC_AUDIO_DEVICE_NAME", "CABLE Output") or "").strip()
audio_sample_rate = _env_int("RC_AUDIO_SAMPLE_RATE", 48000, 8000, 192000)
audio_channels = _env_int("RC_AUDIO_CHANNELS", 2, 1, 2)
audio_frame_ms = _env_int("RC_AUDIO_FRAME_MS", 20, 10, 120)
audio_debug = _env_flag("RC_AUDIO_DEBUG", False)
audio_frame_samples = max(80, int(audio_sample_rate * audio_frame_ms / 1000))

audio_status_lock = threading.Lock()
audio_status = {
    "enabled": bool(audio_enabled),
    "sounddevice_available": bool(SOUNDDEVICE_AVAILABLE),
    "webrtc_available": bool(WEBRTC_AVAILABLE),
    "device_name_hint": audio_device_name,
    "sample_rate": int(audio_sample_rate),
    "channels": int(audio_channels),
    "frame_ms": int(audio_frame_ms),
    "frame_samples": int(audio_frame_samples),
    "selected_device": None,
    "device_index": None,
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

# Cleaned garbled comment.
dxgi_camera = None
dxgi_capture_enabled = False  # Cleaned garbled comment.
dxgi_lock = threading.RLock()
dxgi_failure_count = 0
dxgi_retry_after = 0.0

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
            "立体声混音",
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
        mic_tokens = ("microphone", "mic", "麦克风", "阵列", "array")
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


def is_running_as_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

if not is_running_as_admin():
    print("[Hint] Not running as administrator: input injection on elevated windows may fail.")
    print("[Hint] Please use start_admin.bat to launch in administrator mode.")

def init_dxgi_camera():
    """Initialize DXGI camera."""
    global dxgi_camera, dxcam, dxgi_failure_count, dxgi_retry_after

    # Cleaned garbled comment.
    if dxcam is None and not load_dxcam():
        return False

    with dxgi_lock:
        if dxgi_camera is not None:
            return True

        try:
            # Cleaned garbled comment.
            try:
                dxgi_camera = dxcam.create(output_color="RGB")
            except TypeError:
                dxgi_camera = dxcam.create()
            try:
                if hasattr(dxgi_camera, "start"):
                    dxgi_camera.start(target_fps=webrtc_target_fps)
            except Exception:
                pass
            dxgi_failure_count = 0
            dxgi_retry_after = 0.0
            print(f"[DXGI] camera initialized, output={dxgi_camera.width}x{dxgi_camera.height}")
            return True
        except Exception as e:
            print(f"[DXGI] initialization failed: {e}")
            dxgi_camera = None
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


def handle_dxgi_error(err):
    """Record DXGI failures and back off before retry."""
    global dxgi_failure_count, dxgi_retry_after
    dxgi_failure_count = min(dxgi_failure_count + 1, 8)
    backoff = min(30.0, float(2 ** (dxgi_failure_count - 1)))
    dxgi_retry_after = time.time() + backoff
    print(f"[DXGI Error] {err}, fallback to MSS, retry in {backoff:.0f}s")
    release_dxgi_camera()


def should_try_dxgi():
    if not dxgi_capture_enabled:
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
        monitor = inst.monitors[0]
        mss_local.inst = inst
        mss_local.monitor = monitor
    return inst, monitor


def capture_screen():
    """Cleaned garbled docstring."""
    global dxgi_camera

    # Cleaned garbled comment.
    if should_try_dxgi():
        try:
            # Cleaned garbled comment.
            with dxgi_lock:
                if dxgi_camera is None:
                    if not init_dxgi_camera():
                        raise Exception("DXGI init failed")

                # Cleaned garbled comment.
                frame = dxgi_camera.grab()

            if frame is not None:
                # Cleaned garbled comment.
                img = Image.fromarray(frame)
                return img
            else:
                return None

        except Exception as e:
            handle_dxgi_error(e)

    # Cleaned garbled comment.
    try:
        inst, monitor = get_mss()
        screenshot = inst.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img
    except Exception as e:
        print(f"[Screen Capture Error] {e}")
        # Cleaned garbled comment.
        img = Image.new('RGB', (1920, 1080), color=(20, 20, 30))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40)
        except:
            font = ImageFont.load_default()
        draw.text((100, 100), f"Screen capture error: {e}", fill=(255, 255, 255), font=font)
        return img


def capture_screen_rgb_np():
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
                if frame.ndim == 3 and frame.shape[2] >= 3:
                    rgb = frame[:, :, :3]
                    if rgb.flags["C_CONTIGUOUS"]:
                        return rgb
                    return np.ascontiguousarray(rgb)
            return None
        except Exception as e:
            handle_dxgi_error(e)

    try:
        inst, monitor = get_mss()
        screenshot = inst.grab(monitor)
        bgra = np.frombuffer(screenshot.bgra, dtype=np.uint8)
        bgra = bgra.reshape((screenshot.height, screenshot.width, 4))
        rgb = bgra[:, :, [2, 1, 0]]
        return np.ascontiguousarray(rgb)
    except Exception as e:
        print(f"[Screen Capture Error] {e}")
        return None


class WebRTCFramePump:
    def __init__(self):
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._latest = None
        self._latest_ts = 0.0
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
            inst = getattr(mss_local, "instance", None)
            if inst is not None:
                try:
                    inst.close()
                except Exception:
                    pass
                try:
                    delattr(mss_local, "instance")
                except Exception:
                    pass
        except Exception:
            pass

        self.start()

    def _run(self, generation):
        global webrtc_target_fps, webrtc_scale, webrtc_max_width, webrtc_max_height
        while True:
            with self._state_lock:
                if (not self._running) or (generation != self._generation):
                    break

            t0 = time.time()
            try:
                frame = capture_screen_rgb_np()
            except Exception as e:
                now = time.time()
                if now - self._last_error_log_ts >= 2.0:
                    print(f"[WebRTC] frame capture error: {e}")
                    self._last_error_log_ts = now
                time.sleep(0.05)
                continue

            if frame is None:
                interval = 1.0 / max(1, int(webrtc_target_fps))
                dt = time.time() - t0
                sleep_time = interval - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue

            # Apply requested scale first (supports coarse downsample steps).
            scale = float(webrtc_scale)
            if scale < 0.99:
                step = int(round(1.0 / max(0.25, scale)))
                step = max(1, min(step, 4))
                if step > 1:
                    frame = frame[::step, ::step, :]

            # Hard safety cap for mobile/browser stability.
            h, w = frame.shape[:2]
            step_w = int(np.ceil(float(w) / float(max(1, webrtc_max_width))))
            step_h = int(np.ceil(float(h) / float(max(1, webrtc_max_height))))
            cap_step = max(1, step_w, step_h)
            if cap_step > 1:
                frame = frame[::cap_step, ::cap_step, :]

            frame = np.ascontiguousarray(frame)
            with self._lock:
                self._latest = frame
                self._latest_ts = float(time.time())

            # Prevent backlog at very high resolutions while keeping detail.
            target_fps = max(1, int(webrtc_target_fps))
            if frame is not None:
                h2, w2 = frame.shape[:2]
                if (w2 * h2) >= 3000000 and target_fps > 20:
                    target_fps = 20
            interval = 1.0 / target_fps
            dt = time.time() - t0
            sleep_time = interval - dt
            if sleep_time > 0:
                time.sleep(sleep_time)


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
            self._pts = 0
            self._wall_start = None
            self._closed = False

        def _ensure_capture(self):
            if self._stream is not None:
                return
            if not audio_enabled:
                raise RuntimeError("audio_disabled")
            if not SOUNDDEVICE_AVAILABLE or sd is None:
                raise RuntimeError("sounddevice_unavailable")

            devices = _audio_list_input_devices()
            try:
                candidates = _audio_rank_input_devices(devices)
            except Exception as e:
                _audio_set_error(f"select_input_device_failed: {e}")
                raise

            last_start_error = None
            for selected in candidates:
                selected_channels = min(self._channels, int(selected["max_input_channels"]))
                if selected_channels < 1:
                    continue
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
                    self._stream = sd.InputStream(
                        samplerate=self._sample_rate,
                        blocksize=self._frame_samples,
                        channels=self._channels,
                        dtype="float32",
                        device=int(selected["index"]),
                        callback=_callback,
                    )
                    self._stream.start()
                except Exception as e:
                    last_start_error = e
                    self._stream = None
                    continue

                _audio_set_status(
                    capture_running=True,
                    selected_device=selected["name"],
                    device_index=int(selected["index"]),
                    channels=int(self._channels),
                    sample_rate=int(self._sample_rate),
                    frame_samples=int(self._frame_samples),
                    last_error="",
                )
                print(
                    f"[Audio] capture ready: device={selected['name']}, "
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
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            _audio_set_status(capture_running=False)
            super().stop()

    class ScreenVideoTrack(VideoStreamTrack):
        def __init__(self, pump: WebRTCFramePump):
            super().__init__()
            self._pump = pump
            self._last = None
            self._created_ts = float(time.time())
            self._last_pump_restart_ts = 0.0

        async def recv(self):
            global webrtc_target_fps
            pts, time_base = await self.next_timestamp()

            # If frame pump is stale for too long, restart capture backend.
            frame_age = self._pump.frame_age()
            if frame_age == float("inf") and (time.time() - self._created_ts) < 3.0:
                frame_age = 0.0
            if frame_age > 2.5:
                now = time.time()
                if now - self._last_pump_restart_ts >= 3.0:
                    self._last_pump_restart_ts = now
                    self._pump.restart(f"stalled age={frame_age:.2f}s")

            frame = self._pump.get_latest()
            if frame is None:
                frame = self._last
            if frame is None:
                await asyncio.sleep(0.005)
                frame = self._pump.get_latest()

            if frame is None:
                h, w = 720, 1280
                frame = np.zeros((h, w, 3), dtype=np.uint8)
            self._last = frame

            vf = VideoFrame.from_ndarray(frame, format="rgb24")
            vf.pts = pts
            vf.time_base = time_base
            return vf


def screen_to_bytes(img, quality=60):
    """Encode PIL image to JPEG bytes."""
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    return buffer.getvalue()


def generate_video_stream():
    """Generate optimized MJPEG video stream."""
    global screen_capture_running, quality, fps
    screen_capture_running = True
    last_error_time = 0
    error_count = 0
    last_img = None

    while screen_capture_running:
        try:
            loop_start = time.time()

            # Cleaned garbled comment.
            img = capture_screen()
            if img is None:
                img = last_img
            if img is None:
                img = Image.new('RGB', (1280, 720), color=(0, 0, 0))
            last_img = img

            # Cleaned garbled comment.
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=False, progressive=False)
            frame = buffer.getvalue()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                   b'\r\n' + frame + b'\r\n')

            # Cleaned garbled comment.
            error_count = 0

            # Cleaned garbled comment.
            elapsed = time.time() - loop_start
            target_interval = 1.0 / fps
            sleep_time = target_interval - elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)
            elif sleep_time < -0.05:  # Cleaned garbled comment.
                pass  # Cleaned garbled comment.

        except GeneratorExit:
            # Cleaned garbled comment.
            break
        except Exception as e:
            error_count += 1
            now = time.time()
            if now - last_error_time > 5:  # Cleaned garbled comment.
                print(f"[Video Stream] error ({error_count}): {e}")
                last_error_time = now
                error_count = 0
            time.sleep(0.05)


# Cleaned garbled comment.

@app.route('/')
def index():
    """Render control page."""
    return render_template('index.html')


@app.route('/video')
def video_feed():
    """MJPEG video endpoint."""
    return Response(
        generate_video_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )


@app.route('/api/info')
def server_info():
    """Basic server info endpoint."""
    return {
        'ip': get_local_ip(),
        'port': 5000,
        'clients': connected_clients,
        'screen_size': pyautogui.size(),
        'quality': quality,
        'fps': fps
    }



@app.route('/api/audio_info')
@app.route('/audio_info')
def audio_info():
    devices = _audio_list_input_devices()
    status = _audio_snapshot()
    return {
        'enabled': bool(audio_enabled),
        'webrtc_available': bool(WEBRTC_AVAILABLE),
        'sounddevice_available': bool(SOUNDDEVICE_AVAILABLE),
        'device_name_hint': audio_device_name,
        'sample_rate': int(audio_sample_rate),
        'channels': int(audio_channels),
        'frame_ms': int(audio_frame_ms),
        'frame_samples': int(audio_frame_samples),
        'status': status,
        'devices': devices,
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

    if not dxgi_capture_enabled:
        dxgi_capture_enabled = True
        try:
            if dxgi_camera is None:
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


async def _webrtc_close_peer(sid: str, keep_frame_pump: bool = False):
    global webrtc_frame_pump
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
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await _webrtc_close_peer(sid)

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

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    await _webrtc_wait_ice_complete(pc)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


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
    print(f"[Settings] quality updated: {quality}")
    emit('quality_updated', {'quality': quality})


@socketio.on('set_fps')
def handle_set_fps(data, sid=None):
    """Cleaned garbled docstring."""
    global fps, webrtc_target_fps
    new_fps = max(10, min(60, data.get('fps', 30)))
    fps = new_fps
    webrtc_target_fps = new_fps
    print(f"[Settings] FPS updated: {fps}")
    emit('fps_updated', {'fps': fps, 'webrtc_fps': webrtc_target_fps})


@socketio.on('set_webrtc_scale')
def handle_set_webrtc_scale(data):
    global webrtc_scale
    try:
        scale = float(data.get('scale', webrtc_scale))
    except Exception:
        scale = webrtc_scale

    webrtc_scale = 0.5 if scale < 0.75 else 1.0
    emit('webrtc_scale_updated', {'scale': webrtc_scale})


@socketio.on('set_capture_mode')
def handle_set_capture_mode(data):
    """Cleaned garbled docstring."""
    global dxgi_capture_enabled, dxgi_failure_count, dxgi_retry_after
    mode = data.get('mode', 'auto')

    if mode == 'dxgi':
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
        dxgi_capture_enabled = init_dxgi_camera()
        emit('capture_mode_updated', {'mode': 'dxgi' if dxgi_capture_enabled else 'mss', 'status': 'ok'})


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

    # Cleaned garbled comment.
    if use_dxgi:
        print("[Startup] trying DXGI capture mode...")
        init_dxgi_camera()

    print("=" * 50)
    print("    Remote control server started")
    print("=" * 50)
    print(f"  Host IP: {ip}")
    print(f"  Port: {port}")
    print(f"  Screen size: {pyautogui.size()}")
    print(f"  Capture mode: {'DXGI (hardware)' if dxgi_camera else 'MSS (software)'}")
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
        print("\n[Hint] Use: python server.py --dxgi to enable hardware capture")
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


