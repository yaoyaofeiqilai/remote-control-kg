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
import sys
import threading
import time
from datetime import datetime

import mss

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

from flask import Flask, Response, render_template
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

# DXGI 相机实例
dxgi_camera = None
dxgi_capture_enabled = False  # 默认禁用，通过参数或API启用

# 输入模式
game_mode = False  # 游戏模式：使用底层 SendInput，禁用鼠标同步
input_sender = None
if INPUT_SENDER_AVAILABLE:
    input_sender = get_input_sender()

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
    global dxgi_camera, dxcam

    # 延迟加载 dxcam
    if dxcam is None and not load_dxcam():
        return False

    if dxgi_camera is not None:
        return False

    try:
        # 创建 DXGI 相机实例
        dxgi_camera = dxcam.create()
        print(f"[DXGI] 相机初始化成功，输出分辨率: {dxgi_camera.width}x{dxgi_camera.height}")
        return True
    except Exception as e:
        print(f"[DXGI] 初始化失败: {e}")
        dxgi_camera = None
        return False

def release_dxgi_camera():
    """释放 DXGI 相机"""
    global dxgi_camera
    if dxgi_camera:
        try:
            dxgi_camera.release()
            print("[DXGI] 相机已释放")
        except Exception as e:
            print(f"[DXGI] 释放失败: {e}")
        dxgi_camera = None


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


def capture_screen():
    """捕获屏幕 - 优先使用 DXGI，失败时回退到 mss"""
    global dxgi_camera

    # 尝试使用 DXGI 捕获
    if dxgi_capture_enabled:
        try:
            # 延迟初始化相机
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
                # 帧为空，可能屏幕没有变化或捕获失败
                # 返回上一帧或继续尝试
                pass

        except Exception as e:
            print(f"[DXGI Error] {e}, 回退到 mss")
            # 释放失败的 DXGI 相机
            release_dxgi_camera()

    # 回退到 mss 捕获
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            screenshot = sct.grab(monitor)
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

    while screen_capture_running:
        try:
            loop_start = time.time()

            # 捕获屏幕
            img = capture_screen()

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


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    global connected_clients
    connected_clients = max(0, connected_clients - 1)
    print(f"[-] 客户端断开，当前连接数: {connected_clients}")


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


@socketio.on('set_capture_mode')
def handle_set_capture_mode(data):
    """切换屏幕捕获模式 (dxgi/mss)"""
    global dxgi_capture_enabled
    mode = data.get('mode', 'auto')

    if mode == 'dxgi':
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
