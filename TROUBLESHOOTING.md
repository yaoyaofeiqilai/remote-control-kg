# 故障排除指南

## 安装问题

### Pillow 安装失败（编译错误）

**错误信息：**
```
KeyError: '__version__'
Failed to build 'Pillow'
```

**解决方案：**

#### 方法 1：使用预编译版本（推荐）
```bash
python -m pip install Pillow==10.4.0 --only-binary :all:
```
或者安装最新版：
```bash
python -m pip install Pillow
```

#### 方法 2：安装 Visual Studio Build Tools
1. 下载：https://aka.ms/vs/17/release/vs_BuildTools.exe
2. 运行并选择 **"使用 C++ 的桌面开发"**
3. 等待安装完成后，重新运行 `install.bat`

#### 方法 3：使用预编译的 wheel 文件
```bash
# 访问 https://www.lfd.uci.edu/~gohlke/pythonlibs/#pillow
# 下载对应 Python 版本的 Pillow wheel 文件（如 Pillow‑10.4.0‑cp312‑cp312‑win_amd64.whl）
# 然后安装：
python -m pip install 下载的文件路径.whl
```

#### 方法 4：使用 conda（如果你有 Anaconda）
```bash
conda install pillow
```

---

### pip 超时或网络错误

**解决方案：**
使用国内镜像源：
```bash
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

或者在用户目录创建 `pip/pip.ini` 文件：
```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
```

---

### Python 版本问题

**要求：** Python 3.8 或更高版本

**检查版本：**
```bash
python --version
```

**如果安装了多个 Python 版本，尝试：**
```bash
py -3.11 -m pip install -r requirements.txt
py -3.11 server.py
```

---

## 运行时问题

### 模块未找到错误 (ModuleNotFoundError)

```bash
# 重新安装依赖
python -m pip install --force-reinstall -r requirements.txt
```

### 端口被占用

**错误：** `Address already in use`

**解决方案：**
1. 修改 `server.py` 中的端口号（如改为 5001）
2. 或者查找并结束占用 5000 端口的进程

### 防火墙阻止

**症状：** 服务端启动正常，但平板无法连接

**解决方案：**
1. 打开 Windows 安全中心
2. 点击 **"防火墙和网络保护"**
3. 点击 **"允许应用通过防火墙"**
4. 点击 **"更改设置"** → **"允许其他应用"**
5. 添加 Python 的可执行文件路径
6. 勾选 **"专用"** 和 **"公用"**

或者临时关闭防火墙（仅测试）：
```powershell
# 以管理员身份运行 PowerShell
netsh advfirewall set allprofiles state off
```

测试完成后记得重新开启：
```powershell
netsh advfirewall set allprofiles state on
```

---

## 连接问题

### 平板无法访问服务端

**检查清单：**

1. **同一网络**：确保平板和电脑连接同一个 WiFi/热点
   - 电脑开启热点 → 平板连接该热点（推荐，延迟最低）
   - 或者两者连接同一个路由器

2. **检查 IP 地址**：
   ```bash
   # 在电脑运行
   ipconfig
   ```
   找到无线网卡的 IPv4 地址，确保使用的是正确的 IP

3. **测试连接**：
   - 在电脑浏览器访问 `http://127.0.0.1:5000` 测试服务端
   - 如果本地能访问，说明服务端正常，问题在网络

4. **路由器/AP 隔离**：
   - 某些路由器开启 "AP 隔离" 会阻止设备间通信
   - 关闭路由器设置中的 "AP 隔离" 或 "客户端隔离"

---

## 性能问题

### 画面卡顿

**优化建议：**
1. 降低画质（设置 → 画质：30-50）
2. 降低帧率（设置 → 帧率：15-20）
3. 确保 WiFi 信号良好
4. 关闭电脑上不必要的程序

### 输入延迟高

**优化建议：**
1. 使用 5GHz WiFi 频段（而非 2.4GHz）
2. 电脑开启热点，平板直接连接（减少路由跳数）
3. 降低屏幕分辨率（游戏时调低分辨率）

---

## 其他问题

### pyautogui 安全问题

首次运行时 Windows 可能会提示是否允许 Python 控制鼠标和键盘：
- 点击 **"是"** 或 **"允许"**
- 如果点击了 **"否"**，需要重新运行程序

### 屏幕捕获黑屏

某些游戏或应用可能阻止屏幕捕获：
- 尝试窗口模式而非全屏
- 关闭游戏的反作弊软件（如 Easy Anti-Cheat）
- 使用窗口化无边框模式

---

## 仍然无法解决？

1. 运行诊断脚本：
   ```bash
   python check_install.py
   ```

2. 查看完整错误信息：
   ```bash
   python server.py 2>&1 | tee error.log
   ```

3. 收集以下信息寻求帮助：
   - Python 版本：`python --version`
   - pip 版本：`python -m pip --version`
   - Windows 版本：Win+R 输入 `winver`
   - 完整的错误日志
