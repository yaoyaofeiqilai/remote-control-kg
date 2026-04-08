"""Native desktop shell for the local server console."""

from __future__ import annotations

import csv
import ctypes
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from typing import Any

from flask import Flask, render_template
from werkzeug.serving import make_server

from .runtime_config import (
    CONFIG_FIELDS,
    CONFIG_FIELDS_BY_KEY,
    CONFIG_SECTION_ORDER,
    PROJECT_ROOT,
    RUNTIME_ENV_PATH,
    build_effective_config,
    ensure_runtime_example,
    load_runtime_env,
    normalize_value,
    parse_value,
    save_runtime_env,
)


STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates")
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, os.getenv("RC_ARTIFACTS_DIR", "artifacts"))
LOGS_DIR = os.path.join(ARTIFACTS_DIR, "logs")
SECURITY_FLAG_PATH = os.path.join(ARTIFACTS_DIR, "security_shutdown.flag")
SERVICE_PORT = 5000
SHELL_BUILD = "20260408_desktop_console_cn_fresh2"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOT_CONFIG_KEYS = {
    "RC_QUALITY": "quality",
    "RC_WEBRTC_FPS": "webrtc_fps",
    "RC_WEBRTC_SCALE": "webrtc_scale",
}
LOCAL_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
STREAM_DISPLAY_LABELS = {
    "shell": "壳层",
    "stdout": "输出",
    "stderr": "诊断",
    "access": "访问",
}
ACCESS_LOG_RE = re.compile(
    r'^(?P<addr>\S+) - - \[[^\]]+\] "(?P<method>[A-Z]+) (?P<path>[^ ]+) HTTP/[\d.]+" (?P<status>\d{3})'
)
QUIET_ACCESS_PATHS = {
    "/",
    "/health",
    "/api/info",
    "/api/audio_info",
    "/api/audio_health",
    "/api/video_health",
    "/api/admin/runtime",
    "/static/desktop_console.css",
    "/static/desktop_console.js",
}


def _show_message(title: str, message: str, *, error: bool = False):
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        if error:
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
        root.destroy()
    except Exception:
        pass


def _is_running_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_self_as_admin() -> bool:
    if os.name != "nt" or _is_running_as_admin():
        return True
    params = subprocess.list2cmdline([os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, PROJECT_ROOT, 1)
    return int(code) > 32


def _resolve_python_executables() -> tuple[str, str]:
    current = os.path.abspath(sys.executable)
    directory, name = os.path.split(current)
    lower = name.lower()
    python_exe = current
    pythonw_exe = current
    if lower == "pythonw.exe":
        sibling = os.path.join(directory, "python.exe")
        if os.path.exists(sibling):
            python_exe = sibling
    else:
        sibling = os.path.join(directory, "pythonw.exe")
        if os.path.exists(sibling):
            pythonw_exe = sibling
    return python_exe, pythonw_exe


def _get_local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ConsoleWebServer:
    def __init__(self):
        self.port = self._pick_port()
        self.app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATE_DIR)
        self.app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
        self._server = None
        self._thread = None
        self._ready = threading.Event()
        self._register_routes()

    def _pick_port(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
        sock.close()
        return int(port)

    def _register_routes(self):
        @self.app.after_request
        def _disable_cache(resp):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp

        @self.app.route("/")
        def index():
            return render_template("desktop_console.html", build=SHELL_BUILD)

        @self.app.route("/health")
        def health():
            return {"ok": True, "build": SHELL_BUILD}

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        def _serve():
            self._server = make_server("127.0.0.1", self.port, self.app, threaded=True)
            self._ready.set()
            self._server.serve_forever()

        self._thread = threading.Thread(target=_serve, name="DesktopConsoleWeb", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def stop(self):
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class ServerManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.process_generation = 0
        self.status = "stopped"
        self.status_message = "服务已停止。"
        self.last_exit_code: int | None = None
        self.security_locked = False
        self.manual_stop_requested = False
        self.server_ready = False
        self.admin_token = secrets.token_urlsafe(24)
        self.local_ip = _get_local_ip()
        self.log_cursor = 0
        self.logs: deque[dict[str, Any]] = deque(maxlen=1200)
        self.python_exe, self.pythonw_exe = _resolve_python_executables()
        os.makedirs(LOGS_DIR, exist_ok=True)
        self.stdout_log_path = os.path.join(LOGS_DIR, "desktop_console_server.out.log")
        self.stderr_log_path = os.path.join(LOGS_DIR, "desktop_console_server.err.log")

    def _append_log(self, stream: str, message: str):
        text = str(message or "").rstrip("\r\n")
        if not text:
            return
        with self.lock:
            self.log_cursor += 1
            self.logs.append(
                {
                    "id": int(self.log_cursor),
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "stream": stream,
                    "text": text,
                }
            )

    def _classify_console_log(self, stream_name: str, line: str) -> tuple[str | None, str]:
        text = str(line or "").rstrip("\r\n")
        if not text:
            return None, ""
        if stream_name == "stderr":
            match = ACCESS_LOG_RE.match(text)
            if match:
                addr = str(match.group("addr") or "")
                path = str(match.group("path") or "").split("?", 1)[0]
                status = int(match.group("status") or 0)
                if addr in {"127.0.0.1", "::1"} and status < 400 and path in QUIET_ACCESS_PATHS:
                    return None, text
                return "access", text
        return stream_name, text

    def _effective_value(self, key: str) -> Any:
        saved = load_runtime_env()
        if key in os.environ:
            raw_value = os.environ[key]
        elif key in saved:
            raw_value = saved[key]
        else:
            raw_value = CONFIG_FIELDS_BY_KEY[key].default
        return parse_value(key, raw_value)

    def _compose_child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        saved = load_runtime_env()
        for key, value in saved.items():
            env.setdefault(key, value)
        env["RC_ADMIN_TOKEN"] = self.admin_token
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    def _server_ready_probe(self) -> bool:
        req = urllib.request.Request(f"http://127.0.0.1:{SERVICE_PORT}/api/info", headers={"Cache-Control": "no-store"})
        try:
            with LOCAL_HTTP_OPENER.open(req, timeout=0.35) as resp:
                return int(getattr(resp, "status", 200)) == 200
        except Exception:
            return False

    def _cleanup_stale_server(self):
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=5,
                check=False,
            )
        except Exception as exc:
            self._append_log("shell", f"跳过清理残留服务进程：{exc}")
            return

        killed: list[str] = []
        for line in result.stdout.splitlines():
            text = " ".join(line.split())
            if "LISTENING" not in text or f":{SERVICE_PORT}" not in text:
                continue
            parts = text.split(" ")
            if len(parts) < 5:
                continue
            pid = parts[-1].strip()
            if not pid.isdigit():
                continue
            try:
                task = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=CREATE_NO_WINDOW,
                    timeout=5,
                    check=False,
                )
                rows = [row for row in csv.reader(task.stdout.splitlines()) if row]
                process_name = (rows[0][0] if rows and rows[0] else "").strip().lower()
            except Exception:
                process_name = ""
            if process_name not in ("python.exe", "pythonw.exe"):
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=CREATE_NO_WINDOW,
                    timeout=5,
                    check=False,
                )
                killed.append(pid)
            except Exception:
                continue
        if killed:
            self._append_log("shell", f"已结束残留服务进程：{' '.join(killed)}")

    def _stream_reader(self, proc: subprocess.Popen[str], pipe, stream_name: str, file_path: str, generation: int):
        display_name = STREAM_DISPLAY_LABELS.get(stream_name, stream_name)
        try:
            with open(file_path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] ---- {display_name}流已打开 ----\n")
                for line in iter(pipe.readline, ""):
                    if generation != self.process_generation:
                        break
                    fh.write(line if line.endswith("\n") else line + "\n")
                    fh.flush()
                    surfaced_stream, surfaced_text = self._classify_console_log(stream_name, line)
                    if surfaced_stream and surfaced_text:
                        self._append_log(surfaced_stream, surfaced_text)
                fh.write(f"[{datetime.now().isoformat(timespec='seconds')}] ---- {display_name}流已关闭 ----\n")
                fh.flush()
        except Exception as exc:
            self._append_log("shell", f"{display_name}日志读取失败：{exc}")
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _watch_process(self, proc: subprocess.Popen[str], generation: int):
        exit_code = proc.wait()
        restart_delay = 0
        should_restart = False
        with self.lock:
            if generation != self.process_generation or proc is not self.process:
                return
            self.process = None
            self.server_ready = False
            self.last_exit_code = int(exit_code)
            security_hit = bool(exit_code == 23 or os.path.exists(SECURITY_FLAG_PATH))
            if security_hit:
                self.security_locked = True
                self.status = "security_locked"
                self.status_message = "已触发安全锁定，需要手动恢复。"
                self.manual_stop_requested = False
                self._append_log("shell", "检测到安全锁定，已禁止自动重启")
                return
            if self.manual_stop_requested:
                self.last_exit_code = 0
                self.status = "stopped"
                self.status_message = "服务已停止。"
                self.manual_stop_requested = False
                self._append_log("shell", f"服务已停止（退出码 {exit_code}）")
                return
            auto_restart = bool(self._effective_value("RC_SERVER_AUTORESTART"))
            restart_delay = int(self._effective_value("RC_SERVER_RESTART_DELAY_SEC"))
            if auto_restart and int(exit_code) not in (0, 23):
                self.status = "restarting"
                self.status_message = f"服务异常退出（退出码 {exit_code}），{restart_delay} 秒后自动重启。"
                should_restart = True
                self._append_log("shell", self.status_message)
            else:
                self.status = "error" if int(exit_code) != 0 else "stopped"
                self.status_message = (
                    f"服务已退出（退出码 {exit_code}）。"
                    if int(exit_code) != 0
                    else "服务已停止。"
                )
                self._append_log("shell", self.status_message)

        if should_restart:
            threading.Thread(
                target=self._delayed_restart,
                args=(generation, restart_delay),
                name="DesktopConsoleRestart",
                daemon=True,
            ).start()

    def _delayed_restart(self, generation: int, delay_seconds: int):
        time.sleep(max(0, int(delay_seconds)))
        with self.lock:
            if self.process is not None:
                return
            if self.process_generation != generation:
                return
            if self.manual_stop_requested or self.security_locked or self.status != "restarting":
                return
        self.start_server(reason="自动重启")

    def start_server(self, reason: str = "手动启动") -> dict[str, Any]:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return self.get_state_snapshot()
            self.manual_stop_requested = False
            self.security_locked = False
            self.server_ready = False
            self.status = "starting"
            self.status_message = "正在启动服务..."
            self.process_generation += 1
            generation = self.process_generation

        if os.path.exists(SECURITY_FLAG_PATH):
            try:
                os.remove(SECURITY_FLAG_PATH)
                self._append_log("shell", "启动前已清除安全停服标记")
            except Exception as exc:
                self._append_log("shell", f"清除安全标记失败：{exc}")

        self._cleanup_stale_server()
        cmd = [self.python_exe, "-X", "utf8", "-u", "server.py", "--dxgi"]
        env = self._compose_child_env()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:
            with self.lock:
                self.process = None
                self.status = "error"
                self.status_message = f"启动服务失败：{exc}"
                self.last_exit_code = None
            self._append_log("shell", self.status_message)
            return self.get_state_snapshot()

        with self.lock:
            self.process = proc
            self.last_exit_code = None
            self.status = "starting"
            self.status_message = "正在启动服务..."
        self._append_log("shell", f"已发起服务启动（{reason}），进程号 PID={proc.pid}")

        threading.Thread(
            target=self._stream_reader,
            args=(proc, proc.stdout, "stdout", self.stdout_log_path, generation),
            name="DesktopConsoleStdout",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._stream_reader,
            args=(proc, proc.stderr, "stderr", self.stderr_log_path, generation),
            name="DesktopConsoleStderr",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._watch_process,
            args=(proc, generation),
            name="DesktopConsoleWatcher",
            daemon=True,
        ).start()
        return self.get_state_snapshot()

    def stop_server(self) -> dict[str, Any]:
        with self.lock:
            proc = self.process
            if proc is None or proc.poll() is not None:
                self.process = None
                self.server_ready = False
                self.status = "stopped"
                self.status_message = "服务当前已停止。"
                return self.get_state_snapshot()
            self.manual_stop_requested = True
            self.status = "stopping"
            self.status_message = "正在停止服务..."

        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
        except Exception as exc:
            self._append_log("shell", f"停止服务失败：{exc}")
        time.sleep(0.2)
        return self.get_state_snapshot()

    def restart_server(self) -> dict[str, Any]:
        self.stop_server()
        return self.start_server(reason="手动重启")

    def open_logs_dir(self) -> dict[str, Any]:
        os.makedirs(LOGS_DIR, exist_ok=True)
        try:
            os.startfile(LOGS_DIR)
            return {"ok": True, "path": LOGS_DIR}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": LOGS_DIR}

    def get_logs(self, cursor: int = 0) -> dict[str, Any]:
        with self.lock:
            entries = [item for item in self.logs if int(item["id"]) > int(cursor or 0)]
            next_cursor = int(self.log_cursor)
        return {"entries": entries, "cursor": next_cursor}

    def get_state_snapshot(self) -> dict[str, Any]:
        with self.lock:
            proc = self.process
            current_status = self.status
            current_message = self.status_message
            last_exit_code = self.last_exit_code
            security_locked = self.security_locked
        ready = False
        pid = None
        if proc is not None and proc.poll() is None:
            pid = int(proc.pid)
            ready = self._server_ready_probe()
            with self.lock:
                if self.process is proc and self.status not in ("stopping", "restarting"):
                    self.server_ready = ready
                    self.status = "running" if ready else "starting"
                    if ready and current_status != "running":
                        self.status_message = "服务运行中。"
                    current_status = self.status
                    current_message = self.status_message
        else:
            with self.lock:
                self.server_ready = False
        return {
            "status": current_status,
            "status_message": current_message,
            "pid": pid,
            "last_exit_code": last_exit_code,
            "server_ready": bool(ready or self.server_ready),
            "security_locked": bool(security_locked),
            "control_url_local": f"http://127.0.0.1:{SERVICE_PORT}",
            "control_url_lan": f"http://{self.local_ip}:{SERVICE_PORT}",
            "api_base_local": f"http://127.0.0.1:{SERVICE_PORT}",
            "api_base_lan": f"http://{self.local_ip}:{SERVICE_PORT}",
            "artifacts_dir": ARTIFACTS_DIR,
            "logs_dir": LOGS_DIR,
            "config_path": RUNTIME_ENV_PATH,
            "auto_restart": bool(self._effective_value("RC_SERVER_AUTORESTART")),
            "restart_delay_sec": int(self._effective_value("RC_SERVER_RESTART_DELAY_SEC")),
            "admin_token_present": True,
        }

    def shutdown(self):
        self.stop_server()


class DesktopBridge:
    def __init__(self, manager: ServerManager):
        self.manager = manager

    def get_bootstrap(self):
        ensure_runtime_example()
        return {
            "build": SHELL_BUILD,
            "server_port": SERVICE_PORT,
            "server_base_local": f"http://127.0.0.1:{SERVICE_PORT}",
            "server_base_lan": f"http://{self.manager.local_ip}:{SERVICE_PORT}",
            "admin_token": self.manager.admin_token,
            "config_sections": list(CONFIG_SECTION_ORDER),
            "config_items": build_effective_config(environ=os.environ),
            "shell_state": self.manager.get_state_snapshot(),
        }

    def get_shell_state(self):
        return self.manager.get_state_snapshot()

    def get_recent_logs(self, cursor: int = 0):
        return self.manager.get_logs(cursor)

    def get_config(self):
        ensure_runtime_example()
        return {
            "items": build_effective_config(environ=os.environ),
            "config_path": RUNTIME_ENV_PATH,
        }

    def save_config(self, payload: dict[str, Any]):
        if not isinstance(payload, dict):
            return {"ok": False, "error": "无效的配置数据"}
        values = {}
        for field in CONFIG_FIELDS:
            values[field.key] = payload.get(field.key, self.manager._effective_value(field.key))
        normalized = save_runtime_env(values)
        hot_applied: list[str] = []
        hot_failed: list[str] = []
        if self.manager.get_state_snapshot().get("server_ready"):
            for key, api_name in HOT_CONFIG_KEYS.items():
                try:
                    typed_value = parse_value(key, normalized[key])
                    self._post_admin_runtime({api_name: typed_value})
                    hot_applied.append(key)
                except Exception:
                    hot_failed.append(key)
        return {
            "ok": True,
            "items": build_effective_config(environ=os.environ, stored=normalized),
            "hot_applied": hot_applied,
            "hot_failed": hot_failed,
            "config_path": RUNTIME_ENV_PATH,
        }

    def _post_admin_runtime(self, payload: dict[str, Any]):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{SERVICE_PORT}/api/admin/runtime",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Admin-Token": self.manager.admin_token,
            },
            method="POST",
        )
        with LOCAL_HTTP_OPENER.open(req, timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def start_server(self):
        return self.manager.start_server()

    def stop_server(self):
        return self.manager.stop_server()

    def restart_server(self):
        return self.manager.restart_server()

    def open_logs_dir(self):
        return self.manager.open_logs_dir()


def main() -> int:
    ensure_runtime_example()
    if not _is_running_as_admin():
        if not _relaunch_self_as_admin():
            _show_message("远程控制服务端控制台", "启动桌面控制台需要管理员权限。", error=True)
            return 1
        return 0

    try:
        import webview
    except Exception as exc:
        _show_message("远程控制服务端控制台", f"缺少运行依赖：{exc}\n\n请先运行安装脚本 install.bat。", error=True)
        return 1

    manager = ServerManager()
    bridge = DesktopBridge(manager)
    web_server = ConsoleWebServer()
    web_server.start()

    try:
        webview.create_window(
            "远程控制服务端控制台",
            web_server.url,
            js_api=bridge,
            width=1480,
            height=980,
            min_size=(1180, 760),
            background_color="#f1fbff",
            text_select=False,
        )
        webview.start(debug=False)
    finally:
        web_server.stop()
        manager.shutdown()
    return 0
