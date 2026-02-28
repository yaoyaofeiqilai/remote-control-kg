"""
底层输入模拟模块 - 使用 Windows SendInput API
比 pyautogui 更底层，能更好地支持游戏窗口
"""

import ctypes
import os
from ctypes import wintypes
import time

DEBUG_LOG_ENABLED = os.getenv("RC_DEBUG", "0") == "1"


def debug_log(message):
    if DEBUG_LOG_ENABLED:
        print(message)

# Windows API 常量
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# 鼠标事件标志
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

# 键盘事件标志
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# 虚拟键码映射
VK_MAP = {
    'return': 0x0D,
    'space': 0x20,
    'tab': 0x09,
    'backspace': 0x08,
    'delete': 0x2E,
    'esc': 0x1B,
    'up': 0x26,
    'down': 0x28,
    'left': 0x25,
    'right': 0x27,
    'ctrl': 0x11,
    'alt': 0x12,
    'shift': 0x10,
    'win': 0x5B,
    'w': 0x57,
    'a': 0x41,
    's': 0x53,
    'd': 0x44,
    'e': 0x45,
    'r': 0x52,
    'q': 0x51,
    'f': 0x46,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
        ]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


# 加载 SendInput 函数
user32 = ctypes.windll.user32
SendInput = user32.SendInput
SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), wintypes.INT]
SendInput.restype = wintypes.UINT

GetCursorPos = user32.GetCursorPos
# 直接使用 ctypes.byref 传递，不需要严格的 POINTER(POINT) 类型检查
# 这样可以避免 "expected LP_POINT instance instead of pointer to POINT" 错误
# GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
GetCursorPos.restype = wintypes.BOOL

SetCursorPos = user32.SetCursorPos
SetCursorPos.argtypes = [wintypes.INT, wintypes.INT]
SetCursorPos.restype = wintypes.BOOL

MapVirtualKey = user32.MapVirtualKeyW
MapVirtualKey.argtypes = [wintypes.UINT, wintypes.UINT]
MapVirtualKey.restype = wintypes.UINT


def send_mouse_input(dx, dy, flags, data=0):
    """发送鼠标输入"""
    extra = ctypes.pointer(wintypes.ULONG(0))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = data
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = extra

    result = SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))
    if result != 1:
        print(f"[SendInput] 失败: {ctypes.get_last_error()}")
    return result == 1


def send_keyboard_input(vk, flags=0, use_scancode=False):
    """发送键盘输入"""
    extra = ctypes.pointer(wintypes.ULONG(0))
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    if use_scancode:
        inp.ki.wVk = 0
        inp.ki.wScan = MapVirtualKey(vk, 0)
        inp.ki.dwFlags = flags | KEYEVENTF_SCANCODE
    else:
        inp.ki.wVk = vk
        inp.ki.wScan = 0
        inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = extra

    result = SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))
    return result == 1


class InputSender:
    """底层输入发送器"""

    def __init__(self):
        # 0 = SM_CXSCREEN, 1 = SM_CYSCREEN
        self.screen_width = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_height = ctypes.windll.user32.GetSystemMetrics(1)
        
        # 处理 DPI 缩放
        # 设置 DPI 感知，确保 GetCursorPos 和 SetCursorPos 使用物理坐标
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1) # PROCESS_SYSTEM_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
                
        # 重新获取物理分辨率
        self.screen_width = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_height = ctypes.windll.user32.GetSystemMetrics(1)

    def get_screen_size(self):
        """获取屏幕尺寸"""
        self.screen_width = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_height = ctypes.windll.user32.GetSystemMetrics(1)
        return (self.screen_width, self.screen_height)

    def get_mouse_pos(self):
        """获取当前鼠标位置 (底层 API)"""
        pt = POINT()
        # 使用 ctypes.byref 传递 POINT 实例的引用，这与 GetCursorPos.argtypes = [ctypes.POINTER(POINT)] 匹配
        if GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
        return 0, 0

    def set_mouse_pos(self, x, y):
        """设置鼠标位置 (底层 API)"""
        # SetCursorPos 使用物理坐标，但可能受 DPI 缩放影响
        # 如果我们已经开启了 DPI 感知，这里的坐标应该是准确的物理像素
        return SetCursorPos(int(x), int(y))

    def move_relative(self, dx, dy, raw_input=False):
        """相对移动鼠标

        Args:
            dx, dy: 移动的像素数（可以是浮点数）
            raw_input: 如果为 True，使用原始输入模式（适合FPS游戏视角控制）
                      如果为 False，移动鼠标指针位置（适合普通桌面操作）
        """
        # 累积值取整，保留小数部分用于下次
        dx_int = int(round(dx))
        dy_int = int(round(dy))

        if dx_int == 0 and dy_int == 0:
            return True  # 移动为0，直接返回成功

        if raw_input:
            # 原始输入模式：发送原始鼠标移动事件
            # FPS游戏捕获鼠标后会读取这些移动数据来控制视角
            debug_log(f"[SendInput] relative move dx={dx_int}, dy={dy_int}")
            return send_mouse_input(dx_int, dy_int, MOUSEEVENTF_MOVE)
        else:
            # 普通模式：移动鼠标指针位置
            current_x, current_y = self.get_mouse_pos()
            new_x = current_x + dx_int
            new_y = current_y + dy_int

            # 限制在屏幕范围内
            new_x = max(0, min(new_x, self.screen_width))
            new_y = max(0, min(new_y, self.screen_height))

            # 优先使用 SetCursorPos，因为它更可靠
            if self.set_mouse_pos(new_x, new_y):
                return True

            # 如果 SetCursorPos 失败，回退到 SendInput
            return send_mouse_input(dx_int, dy_int, MOUSEEVENTF_MOVE)

    def move_camera(self, dx, dy):
        """专门用于FPS游戏的视角控制

        使用 SendInput 发送鼠标移动，但立即将鼠标重置到屏幕中心
        这样FPS游戏可以读取到移动增量，但鼠标不会真的移动到边缘
        """
        # 发送相对移动
        result = send_mouse_input(int(dx), int(dy), MOUSEEVENTF_MOVE)

        # 将鼠标重置到屏幕中心（游戏通常会自己隐藏鼠标，这只是辅助）
        # 注意：不在此处重置，因为这会和游戏的鼠标捕获冲突
        # 重置鼠标的逻辑应该在游戏循环中处理

        return result

    def move_absolute(self, x, y):
        """绝对位置移动鼠标（坐标映射到 0-65535）"""
        # 转换为 Windows 虚拟屏幕坐标 (0-65535)
        x_scaled = int(x * 65535 / self.screen_width)
        y_scaled = int(y * 65535 / self.screen_height)
        return send_mouse_input(x_scaled, y_scaled, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)

    def left_down(self):
        """左键按下"""
        return send_mouse_input(0, 0, MOUSEEVENTF_LEFTDOWN)

    def left_up(self):
        """左键抬起"""
        return send_mouse_input(0, 0, MOUSEEVENTF_LEFTUP)

    def right_down(self):
        """右键按下"""
        return send_mouse_input(0, 0, MOUSEEVENTF_RIGHTDOWN)

    def right_up(self):
        """右键抬起"""
        return send_mouse_input(0, 0, MOUSEEVENTF_RIGHTUP)

    def middle_down(self):
        """中键按下"""
        return send_mouse_input(0, 0, MOUSEEVENTF_MIDDLEDOWN)

    def middle_up(self):
        """中键抬起"""
        return send_mouse_input(0, 0, MOUSEEVENTF_MIDDLEUP)

    def scroll(self, dy, dx=0):
        """滚轮滚动"""
        result = True
        if dy != 0:
            # WHEEL_DELTA = 120
            result &= send_mouse_input(0, 0, MOUSEEVENTF_WHEEL, int(dy * 120))
        if dx != 0:
            result &= send_mouse_input(0, 0, MOUSEEVENTF_HWHEEL, int(dx * 120))
        return result

    def key_down(self, key):
        """按键按下"""
        key_lower = key.lower()
        vk = VK_MAP.get(key_lower, ord(key.upper()) if len(key) == 1 else 0)
        if vk:
            use_scancode = key_lower in ('shift', 'ctrl', 'alt')
            return send_keyboard_input(vk, 0, use_scancode=use_scancode)
        return False

    def key_up(self, key):
        """按键抬起"""
        key_lower = key.lower()
        vk = VK_MAP.get(key_lower, ord(key.upper()) if len(key) == 1 else 0)
        if vk:
            use_scancode = key_lower in ('shift', 'ctrl', 'alt')
            return send_keyboard_input(vk, KEYEVENTF_KEYUP, use_scancode=use_scancode)
        return False


# 全局实例
_input_sender = None

def get_input_sender():
    """获取全局 InputSender 实例"""
    global _input_sender
    if _input_sender is None:
        _input_sender = InputSender()
    return _input_sender


if __name__ == "__main__":
    # 测试
    sender = InputSender()
    print(f"屏幕尺寸: {sender.get_screen_size()}")

    print("3秒后测试鼠标移动...")
    time.sleep(3)

    # 测试相对移动
    print("向右下移动 50 像素")
    sender.move_relative(50, 50)
    time.sleep(0.5)

    # 测试点击
    print("左键点击")
    sender.left_down()
    time.sleep(0.05)
    sender.left_up()
    time.sleep(0.5)

    print("测试完成")
