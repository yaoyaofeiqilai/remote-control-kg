#!/usr/bin/env python3
"""
测试 UAC 弹窗捕获
需要以管理员身份运行此脚本
"""

import ctypes
import sys
import time

def is_admin():
    """检查是否以管理员身份运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def test_dxgi_capture():
    """测试 DXGI 捕获 UAC"""
    print("="*50)
    print("DXGI UAC 捕获测试")
    print("="*50)

    # 检查管理员权限
    if not is_admin():
        print("\n[错误] 请以管理员身份运行此脚本！")
        print("右键 → 以管理员身份运行")
        input("\n按回车键退出...")
        return False

    print("\n[✓] 管理员权限已确认")

    # 尝试加载 dxcam
    try:
        import warnings
        warnings.filterwarnings('ignore')
        import dxcam
        print("[✓] dxcam 加载成功")
    except Exception as e:
        print(f"[✗] dxcam 加载失败: {e}")
        return False

    # 创建相机
    try:
        camera = dxcam.create()
        print(f"[✓] DXGI 相机创建成功")
        print(f"    分辨率: {camera.width}x{camera.height}")
    except Exception as e:
        print(f"[✗] 相机创建失败: {e}")
        return False

    # 捕获测试帧
    print("\n[测试] 捕获屏幕...")
    time.sleep(1)
    frame = camera.grab()

    if frame is None:
        print("[✗] 捕获失败，返回空帧")
        camera.release()
        return False

    print(f"[✓] 捕获成功，帧尺寸: {frame.shape}")

    # 保存截图
    try:
        from PIL import Image
        img = Image.fromarray(frame)
        filename = "uac_test_before.png"
        img.save(filename)
        print(f"[✓] 截图已保存: {filename}")
    except Exception as e:
        print(f"[!] 保存截图失败: {e}")

    print("\n" + "="*50)
    print("现在请在 10 秒内触发一个 UAC 弹窗")
    print("（例如：Win+R 输入 cmd，按 Ctrl+Shift+Enter）")
    print("="*50)

    # 倒计时并持续捕获
    for i in range(10, 0, -1):
        print(f"\r倒计时: {i} 秒", end="", flush=True)
        time.sleep(1)
        # 尝试捕获
        frame = camera.grab()
        if frame is not None:
            # 检查画面是否有变化（简单判断）
            pass

    print("\n\n[测试] 尝试捕获 UAC 弹窗...")
    time.sleep(0.5)
    frame = camera.grab()

    if frame is not None:
        try:
            from PIL import Image
            img = Image.fromarray(frame)
            filename = "uac_test_after.png"
            img.save(filename)
            print(f"[✓] UAC 弹窗截图已保存: {filename}")
            print("\n请检查图片中是否包含 UAC 弹窗：")
            print("- 如果有 = DXGI 可以捕获 UAC")
            print("- 如果没有 = DXGI 无法捕获 UAC（可能是 Windows 限制）")
        except Exception as e:
            print(f"[!] 保存失败: {e}")

    camera.release()
    print("\n测试完成。按回车键退出...")
    input()
    return True

if __name__ == "__main__":
    try:
        test_dxgi_capture()
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车键退出...")
