#!/usr/bin/env python3
"""
安装检查脚本 - 检查所有依赖是否正确安装
"""

import sys


def check_python_version():
    """检查 Python 版本"""
    print("[*] 检查 Python 版本...")
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print(f"  ✓ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"  ✗ Python 版本过低: {version.major}.{version.minor}.{version.micro}")
        print("  需要 Python 3.8 或更高版本")
        return False


def check_modules():
    """检查必要的 Python 模块"""
    print("\n[*] 检查 Python 模块...")

    modules = [
        ('flask', 'Flask'),
        ('flask_cors', 'Flask-CORS'),
        ('flask_socketio', 'Flask-SocketIO'),
        ('socketio', 'python-socketio'),
        ('pyautogui', 'PyAutoGUI'),
        ('PIL', 'Pillow'),
        ('mss', 'mss'),
        ('numpy', 'NumPy'),
    ]

    all_ok = True
    for module, name in modules:
        try:
            __import__(module)
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} - 未安装")
            all_ok = False

    return all_ok


def check_network():
    """检查网络配置"""
    print("\n[*] 检查网络配置...")

    import socket
    try:
        # 获取本机 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        print(f"  ✓ 本机 IP: {ip}")
        print(f"  平板访问地址: http://{ip}:5000")
        return True
    except Exception as e:
        print(f"  ✗ 无法获取 IP 地址: {e}")
        return False


def main():
    print("=" * 50)
    print("    远程控制软件 - 安装检查")
    print("=" * 50)

    results = []
    results.append(("Python 版本", check_python_version()))
    results.append(("Python 模块", check_modules()))
    results.append(("网络配置", check_network()))

    print("\n" + "=" * 50)
    print("    检查结果")
    print("=" * 50)

    for name, ok in results:
        status = "✓ 通过" if ok else "✗ 失败"
        print(f"  {name}: {status}")

    all_ok = all(r[1] for r in results)

    print("=" * 50)

    if all_ok:
        print("\n✓ 所有检查通过！可以运行 start.bat 启动服务端")
        return 0
    else:
        print("\n✗ 部分检查未通过，请运行 install.bat 安装依赖")
        return 1


if __name__ == '__main__':
    sys.exit(main())
