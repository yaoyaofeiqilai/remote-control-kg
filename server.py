#!/usr/bin/env python3
"""
远程控制服务端 - Windows电脑端运行
提供屏幕捕获和输入控制服务
"""

import asyncio
import base64
import ctypes
import io
import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime

import mss
import numpy as np

# 尝试导入 DXGI 捕获库（延迟导入，避免启动时崩溃）
DXCAM_AVAILABLE = False
dxcam = None

def load_dxcam():
    """延迟加载 dxcam，避免启动时因 numpy 问题崩溃"""
    global DXCAM_AVAILABLE, dxcam
    try:
        import warnings
        warnings.filterwarnings('ignore')
        import dxcam as dx
        dxcam = dx
        DXCAM_AVAILABLE = True
        return True
    except Exception as e:
        print(f"[DXGI] 加载失败: {e}")
        return False

# 导入 PIL
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"[错误] 无法导入 Pillow: {e}")
    print("请运行: python -m pip install Pillow")
    exit(1)

VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor", "py312")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

from flask import Flask, Response, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pyautogui

# 导入底层输入模块
try:
    from input_sender import get_input_sender, InputSender
    INPUT_SENDER_AVAILABLE = True
    print("[输入] 底层 SendInput API 可用")
except Exception as e:
    print(f"[输入] 底层 SendInput API 加载失败: {e}")
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
    print(f"[手柄] vgamepad 未启用: {e}")

WEBRTC_AVAILABLE = False
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.rtcrtpsender import RTCRtpSender
    from aiortc.mediastreams import VideoStreamTrack
    from av import VideoFrame
    WEBRTC_AVAILABLE = True
except Exception as e:
    print(f"[WebRTC] 依赖加载失败: {e}")

# 配置
app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False)

# 设置 pyautogui 安全模式（防止失控）
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

# 全局状态
connected_clients = 0
screen_capture_running = False
quality = 60  # 图像质量 1-95
fps = 30      # 目标帧率

webrtc_enabled = True
webrtc_target_fps = 60
webrtc_scale = 0.5
webrtc_peers = {}
webrtc_loop = None
webrtc_loop_thread = None
webrtc_frame_pump = None

# DXGI 相机实例
dxgi_camera = None
dxgi_capture_enabled = False  # 默认禁用，通过参数或API启用
dxgi_lock = threading.RLock()
dxgi_failure_count = 0
dxgi_retry_after = 0.0

mss_local = threading.local()

# 输入模式
game_mode = False  # 游戏模式：使用底层 SendInput，禁用鼠标同步
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

def is_running_as_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

if not is_running_as_admin():
    print("[提示] 当前未以管理员权限运行：对管理员权限窗口的鼠标/按键注入可能会失效")
    print("[提示] 请使用 start_admin.bat 以管理员模式启动")

def init_dxgi_camera():
    """初始化 DXGI 相机"""
    global dxgi_camera, dxcam, dxgi_failure_count, dxgi_retry_after

    # 延迟加载 dxcam
    if dxcam is None and not load_dxcam():
        return False

    with dxgi_lock:
        if dxgi_camera is not None:
            return True

        try:
            # 创建 DXGI 相机实例
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
            print(f"[DXGI] 相机初始化成功，输出分辨率: {dxgi_camera.width}x{dxgi_camera.height}")
            return True
        except Exception as e:
            print(f"[DXGI] 初始化失败: {e}")
            dxgi_camera = None
            return False

def release_dxgi_camera():
    """释放 DXGI 相机"""
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
                print("[DXGI] 相机已释放")
            except Exception as e:
                print(f"[DXGI] 释放失败: {e}")
            dxgi_camera = None


def handle_dxgi_error(err):
    """记录 DXGI 错误并进入退避，避免失败后高频重建导致屏闪。"""
    global dxgi_failure_count, dxgi_retry_after
    dxgi_failure_count = min(dxgi_failure_count + 1, 8)
    backoff = min(30.0, float(2 ** (dxgi_failure_count - 1)))
    dxgi_retry_after = time.time() + backoff
    print(f"[DXGI Error] {err}, 回退到 mss，{backoff:.0f}s 后重试")
    release_dxgi_camera()


def should_try_dxgi():
    if not dxgi_capture_enabled:
        return False
    return time.time() >= dxgi_retry_after


def get_local_ip():
    """获取本机局域网IP"""
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
    """捕获屏幕 - 优先使用 DXGI，失败时回退到 mss"""
    global dxgi_camera

    # 尝试使用 DXGI 捕获
    if should_try_dxgi():
        try:
            # 延迟初始化相机
            with dxgi_lock:
                if dxgi_camera is None:
                    if not init_dxgi_camera():
                        raise Exception("DXGI 初始化失败")

                # 捕获帧 (返回 numpy 数组)
                frame = dxgi_camera.grab()

            if frame is not None:
                # numpy 数组转 PIL Image
                img = Image.fromarray(frame)
                return img
            else:
                return None

        except Exception as e:
            handle_dxgi_error(e)

    # 回退到 mss 捕获
    try:
        inst, monitor = get_mss()
        screenshot = inst.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img
    except Exception as e:
        print(f"[Screen Capture Error] {e}")
        # 返回错误图像
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
                        raise Exception("DXGI 初始化失败")

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
        self._latest = None
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_latest(self):
        with self._lock:
            return self._latest

    def _run(self):
        global webrtc_target_fps, webrtc_scale
        while self._running:
            t0 = time.time()
            frame = capture_screen_rgb_np()
            if frame is None:
                interval = 1.0 / max(1, int(webrtc_target_fps))
                dt = time.time() - t0
                sleep_time = interval - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue
            if webrtc_scale == 0.5 and frame is not None:
                frame = frame[::2, ::2, :]
                frame = np.ascontiguousarray(frame)
            with self._lock:
                self._latest = frame

            interval = 1.0 / max(1, int(webrtc_target_fps))
            dt = time.time() - t0
            sleep_time = interval - dt
            if sleep_time > 0:
                time.sleep(sleep_time)


if WEBRTC_AVAILABLE:
    class ScreenVideoTrack(VideoStreamTrack):
        def __init__(self, pump: WebRTCFramePump):
            super().__init__()
            self._pump = pump
            self._last = None

        async def recv(self):
            global webrtc_target_fps
            pts, time_base = await self.next_timestamp()
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
    """将图像转换为JPEG字节流"""
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    return buffer.getvalue()


def generate_video_stream():
    """生成 MJPEG 视频流 - 优化版本"""
    global screen_capture_running, quality, fps
    screen_capture_running = True
    last_error_time = 0
    error_count = 0
    last_img = None

    while screen_capture_running:
        try:
            loop_start = time.time()

            # 捕获屏幕
            img = capture_screen()
            if img is None:
                img = last_img
            if img is None:
                img = Image.new('RGB', (1280, 720), color=(0, 0, 0))
            last_img = img

            # 压缩为JPEG - 使用更快的参数
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=False, progressive=False)
            frame = buffer.getvalue()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                   b'\r\n' + frame + b'\r\n')

            # 重置错误计数
            error_count = 0

            # 精确帧率控制
            elapsed = time.time() - loop_start
            target_interval = 1.0 / fps
            sleep_time = target_interval - elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)
            elif sleep_time < -0.05:  # 如果落后超过50ms，跳过一帧调整
                pass  # 继续下一帧，不额外等待

        except GeneratorExit:
            # 客户端断开连接
            break
        except Exception as e:
            error_count += 1
            now = time.time()
            if now - last_error_time > 5:  # 每5秒最多报告一次错误
                print(f"[视频流] 错误 ({error_count}次): {e}")
                last_error_time = now
                error_count = 0
            time.sleep(0.05)


# ============ HTTP 路由 ============

@app.route('/')
def index():
    """主页面 - 控制界面"""
    return render_template('index.html')


@app.route('/video')
def video_feed():
    """视频流接口"""
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
    """服务器信息"""
    return {
        'ip': get_local_ip(),
        'port': 5000,
        'clients': connected_clients,
        'screen_size': pyautogui.size(),
        'quality': quality,
        'fps': fps
    }


# ============ WebSocket 事件 ============

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    global connected_clients
    connected_clients += 1
    print(f"[+] 客户端连接，当前连接数: {connected_clients}")
    emit('connected', {
        'status': 'ok',
        'screen_width': pyautogui.size().width,
        'screen_height': pyautogui.size().height
    })
    emit('xinput_status', {'available': bool(XINPUT_AVAILABLE)})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    global connected_clients
    connected_clients = max(0, connected_clients - 1)
    print(f"[-] 客户端断开，当前连接数: {connected_clients}")

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


async def _webrtc_close_peer(sid: str):
    pc = webrtc_peers.pop(sid, None)
    if pc:
        try:
            await pc.close()
        except Exception:
            pass

    if not webrtc_peers and webrtc_frame_pump is not None:
        try:
            webrtc_frame_pump.stop()
        except Exception:
            pass


async def _webrtc_handle_offer(sid: str, offer_sdp: str, offer_type: str):
    await _webrtc_close_peer(sid)

    pc = RTCPeerConnection()
    webrtc_peers[sid] = pc

    @pc.on("connectionstatechange")
    async def _on_connection_state_change():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await _webrtc_close_peer(sid)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type=offer_type))

    if webrtc_frame_pump is not None:
        track = ScreenVideoTrack(webrtc_frame_pump)
        attached = False
        for transceiver in pc.getTransceivers():
            if transceiver.kind == "video":
                try:
                    await transceiver.sender.replaceTrack(track)
                    attached = True
                    break
                except Exception:
                    pass
        if not attached:
            pc.addTrack(track)

    try:
        caps = RTCRtpSender.getCapabilities("video").codecs
        h264 = [c for c in caps if (c.name or "").upper() == "H264"]
        for transceiver in pc.getTransceivers():
            if transceiver.kind == "video" and hasattr(transceiver, "setCodecPreferences") and h264:
                transceiver.setCodecPreferences(h264)
                break
    except Exception:
        pass

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


@socketio.on('set_mode')
def handle_set_mode(data):
    """客户端切换模式"""
    global game_mode
    mode = data.get('mode', 'touch')

    if mode == 'gamepad':
        game_mode = True
        print(f"[模式切换] ==============================")
        print(f"[模式切换] 进入游戏模式 (game_mode=True)")
        print(f"[模式切换] input_sender 可用: {input_sender is not None}")
        print(f"[模式切换] ==============================")
    else:
        game_mode = False
        print(f"[模式切换] 进入{mode}模式 (game_mode=False)")

    emit('mode_changed', {'mode': mode, 'game_mode': game_mode})


@socketio.on('mouse_move')
def handle_mouse_move(data):
    """处理鼠标移动（绝对位置）"""
    try:
        x = data.get('x', 0)
        y = data.get('y', 0)
        # 确保坐标在屏幕范围内
        screen_width, screen_height = pyautogui.size()
        x = max(0, min(x, screen_width))
        y = max(0, min(y, screen_height))

        if game_mode and input_sender:
            input_sender.move_absolute(x, y)
        elif input_sender:
            # 使用底层 SetCursorPos 替代 pyautogui.moveTo
            if not input_sender.set_mouse_pos(x, y):
                # 如果底层设置失败（可能因权限不足），尝试回退到 pyautogui
                pyautogui.moveTo(x, y, duration=0)
        else:
            pyautogui.moveTo(x, y, duration=0)
    except Exception as e:
        print(f"鼠标移动错误: {e}")


@socketio.on('mouse_move_relative')
def handle_mouse_move_relative(data):
    """处理鼠标相对移动（触摸板模式）"""
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
        print(f"鼠标相对移动错误: {e}")
        import traceback
        traceback.print_exc()


@socketio.on('get_mouse_pos')
def handle_get_mouse_pos(sid=None):
    """获取当前鼠标位置"""
    try:
        if input_sender:
            x, y = input_sender.get_mouse_pos()
        else:
            x, y = pyautogui.position()
        emit('mouse_pos', {'x': x, 'y': y})
    except Exception as e:
        print(f"获取鼠标位置错误: {e}")


@socketio.on('mouse_click')
def handle_mouse_click(data):
    """处理鼠标点击"""
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
        print(f"鼠标点击错误: {e}")


@socketio.on('mouse_scroll')
def handle_mouse_scroll(data):
    """处理鼠标滚轮"""
    try:
        dx = data.get('dx', 0)
        dy = data.get('dy', 0)

        if game_mode and input_sender:
            input_sender.scroll(dy, dx)
        else:
            # 垂直滚动
            if dy != 0:
                pyautogui.scroll(int(dy))
            # 水平滚动 (Windows支持)
            if dx != 0:
                pyautogui.hscroll(int(dx))
    except Exception as e:
        print(f"鼠标滚轮错误: {e}")


@socketio.on('key_event')
def handle_key_event(data):
    """处理键盘事件"""
    try:
        key = data.get('key', '')
        action = data.get('action', 'down')

        # 映射特殊键
        key_map = {
            'Enter': 'return',
            'Return': 'return',
            'Space': 'space',
            'Tab': 'tab',
            'Backspace': 'backspace',
            'Delete': 'delete',
            'Escape': 'esc',
            'ArrowUp': 'up',
            'ArrowDown': 'down',
            'ArrowLeft': 'left',
            'ArrowRight': 'right',
            'Control': 'ctrl',
            'Alt': 'alt',
            'Shift': 'shift',
            'Meta': 'win',
            'Windows': 'win',
        }

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
        print(f"键盘事件错误: {e}")


# 存储 WASD 当前状态
wasd_state = {'w': False, 'a': False, 's': False, 'd': False}

def send_key(key, down):
    """统一按键发送函数"""
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
                    print(f"[手柄] xinput_state 已应用: {xinput_apply_count}/s, 非零: {xinput_apply_nonzero}/s")
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
                print(f"[手柄] 创建虚拟手柄失败: {e}")
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
            # 仅移交控制权，不重建虚拟手柄，避免游戏端丢失设备绑定
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
        print(f"[手柄] 设置摇杆/扳机失败: {e}")
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
        print(f"[手柄] 提交手柄状态失败: {e}")
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
        print(f"[手柄] xinput_state 收包速率: {xinput_state_count}/s, owner={xinput_owner_sid == sid}")
        xinput_state_last_log = now
        xinput_state_count = 0
    with xinput_lock:
        xinput_state_queue.append((sid, data or {}))
    xinput_state_event.set()

@socketio.on('gamepad_input')
def handle_gamepad(data):
    """处理游戏手柄/虚拟手柄输入"""
    global wasd_state
    try:
        # WASD 移动
        if data.get('type') == 'movement':
            x = data.get('x', 0)  # -1 到 1
            y = data.get('y', 0)  # -1 到 1

            # 根据摇杆方向发送按键
            deadzone = 0.3

            new_w = y < -deadzone
            new_s = y > deadzone
            new_a = x < -deadzone
            new_d = x > deadzone

            # 只在状态变化时发送按键
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

        # 动作按钮
        elif data.get('type') == 'action':
            button = data.get('button')
            pressed = data.get('pressed', False)

            key = None
            if button == 'A':
                key = 'space'  # 跳跃/确认
            elif button == 'B':
                key = 'esc'    # 取消/返回
            elif button == 'X':
                key = 'e'      # 交互
            elif button == 'Y':
                key = 'r'      # 换弹/技能

            if key:
                send_key(key, pressed)

    except Exception as e:
        print(f"手柄输入错误: {e}")


@socketio.on('set_quality')
def handle_set_quality(data, sid=None):
    """设置图像质量"""
    global quality
    new_quality = max(10, min(95, data.get('quality', 60)))
    quality = new_quality
    print(f"[设置] 画质调整为: {quality}")
    emit('quality_updated', {'quality': quality})


@socketio.on('set_fps')
def handle_set_fps(data, sid=None):
    """设置帧率"""
    global fps
    new_fps = max(10, min(60, data.get('fps', 30)))
    fps = new_fps
    print(f"[设置] 帧率调整为: {fps}")
    emit('fps_updated', {'fps': fps})


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
    """切换屏幕捕获模式 (dxgi/mss)"""
    global dxgi_capture_enabled, dxgi_failure_count, dxgi_retry_after
    mode = data.get('mode', 'auto')

    if mode == 'dxgi':
        dxgi_retry_after = 0.0
        dxgi_failure_count = 0
        dxgi_capture_enabled = init_dxgi_camera()
        if dxgi_capture_enabled:
            emit('capture_mode_updated', {'mode': 'dxgi', 'status': 'ok'})
        else:
            emit('capture_mode_updated', {'mode': 'mss', 'status': 'error', 'message': 'DXGI 初始化失败'})
    elif mode == 'mss':
        dxgi_capture_enabled = False
        release_dxgi_camera()
        emit('capture_mode_updated', {'mode': 'mss', 'status': 'ok'})
    else:  # auto
        dxgi_capture_enabled = init_dxgi_camera()
        emit('capture_mode_updated', {'mode': 'dxgi' if dxgi_capture_enabled else 'mss', 'status': 'ok'})


@socketio.on('get_capture_info')
def handle_get_capture_info():
    """获取当前捕获模式信息"""
    emit('capture_info', {
        'mode': 'dxgi' if dxgi_camera else 'mss',
        'dxgi_available': dxcam is not None,
        'dxgi_active': dxgi_camera is not None
    })


# ============ 启动 ============

def main():
    ip = get_local_ip()
    port = 5000

    # 检查命令行参数
    use_dxgi = '--dxgi' in sys.argv

    # 如果指定了 --dxgi，尝试初始化
    if use_dxgi:
        print("[启动] 尝试启用 DXGI 捕获...")
        init_dxgi_camera()

    print("=" * 50)
    print("    远程控制服务端已启动")
    print("=" * 50)
    print(f"  本机IP: {ip}")
    print(f"  端口: {port}")
    print(f"  屏幕分辨率: {pyautogui.size()}")
    print(f"  捕获模式: {'DXGI (硬件加速)' if dxgi_camera else 'MSS (软件捕获)'}")
    print("-" * 50)
    print(f"  控制界面: http://{ip}:{port}")
    print("=" * 50)
    print("\n请确保平板和电脑连接同一个热点/WiFi")
    print("在平板上用浏览器访问上述地址即可控制")
    if dxgi_camera:
        print("\n[提示] DXGI 模式已启用，管理员运行可捕获 UAC 弹窗")
    else:
        print("\n[提示] 使用: python server.py --dxgi 启用硬件加速捕获")
    print()

    try:
        # 启动服务
        socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False)
    finally:
        # 清理资源
        release_dxgi_camera()


if __name__ == '__main__':
    main()
