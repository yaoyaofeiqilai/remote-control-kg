#!/usr/bin/env python3
"""
测试 DXGI 屏幕捕获功能
用于验证是否能捕获 UAC 弹窗
"""

import time
import sys

try:
    import dxcam
    import numpy as np
    from PIL import Image
    print("[✓] dxcam 已导入")
except ImportError as e:
    print(f"[✗] 导入失败: {e}")
    print("请运行: python -m pip install dxcam==0.0.5 numpy")
    sys.exit(1)

def test_dxgi_capture():
    """测试 DXGI 捕获"""
    print("\n" + "="*50)
    print("DXGI Desktop Duplication 测试")
    print("="*50)

    try:
        print("[1/4] 创建 DXGI 相机...")
        camera = dxcam.create()
        print(f"    [✓] 相机创建成功")
        print(f"    分辨率: {camera.width}x{camera.height}")
        print(f"    刷新率: {camera.target_fps} FPS")

        print("\n[2/4] 捕获测试帧...")
        time.sleep(0.5)  # 等待初始化
        frame = camera.grab()

        if frame is None:
            print("    [✗] 捕获失败，返回空帧")
            return False

        print(f"    [✓] 捕获成功，帧尺寸: {frame.shape}")

        # 保存测试截图
        print("\n[3/4] 保存测试截图...")
        img = Image.fromarray(frame)
        filename = "dxgi_test_screenshot.png"
        img.save(filename)
        print(f"    [✓] 截图已保存: {filename}")

        print("\n[4/4] 性能测试...")
        frames = 30
        start = time.time()
        for _ in range(frames):
            camera.grab()
        elapsed = time.time() - start
        avg_fps = frames / elapsed
        print(f"    [✓] 平均捕获帧率: {avg_fps:.1f} FPS")

        # 释放相机
        camera.release()
        print("\n" + "="*50)
        print("[✓] 所有测试通过！")
        print("="*50)
        print("\n提示: 要以管理员身份运行才能捕获 UAC 弹窗")
        return True

    except Exception as e:
        print(f"\n[✗] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_admin():
    """检查是否以管理员身份运行"""
    import ctypes
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if __name__ == "__main__":
    print("DXGI 屏幕捕获测试工具")

    if check_admin():
        print("[状态] 当前以管理员身份运行 ✓")
        print("       可以捕获 UAC 弹窗")
    else:
        print("[状态] 当前未以管理员身份运行")
        print("       无法捕获 UAC 弹窗，但普通捕获可用")

    success = test_dxgi_capture()
    sys.exit(0 if success else 1)
