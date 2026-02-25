"""
底层输入模拟模块 - 使用 Windows SendInput API
比 pyautogui 更底层，能更好地支持游戏窗口
"""

import ctypes
from ctypes import wintypes
import time

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


# 加载 SendInput 函数
user32 = ctypes.windll.user32
SendInput = user32.SendInput
SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), wintypes.INT]
SendInput.restype = wintypes.UINT


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


def send_keyboard_input(vk, flags=0):
    """发送键盘输入"""
    extra = ctypes.pointer(wintypes.ULONG(0))
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
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
        self.screen_width = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_height = ctypes.windll.user32.GetSystemMetrics(1)

    def get_screen_size(self):
        """获取屏幕尺寸"""
        self.screen_width = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_height = ctypes.windll.user32.GetSystemMetrics(1)
        return (self.screen_width, self.screen_height)

    def move_relative(self, dx, dy):
        """相对移动鼠标（游戏推荐）"""
        return send_mouse_input(dx, dy, MOUSEEVENTF_MOVE)

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
        vk = VK_MAP.get(key.lower(), ord(key.upper()) if len(key) == 1 else 0)
        if vk:
            return send_keyboard_input(vk, 0)
        return False

    def key_up(self, key):
        """按键抬起"""
        vk = VK_MAP.get(key.lower(), ord(key.upper()) if len(key) == 1 else 0)
        if vk:
            return send_keyboard_input(vk, KEYEVENTF_KEYUP)
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
