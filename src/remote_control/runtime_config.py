"""Shared runtime configuration helpers for launcher, shell, and server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
RUNTIME_ENV_PATH = os.path.join(CONFIG_DIR, "runtime.env")
RUNTIME_ENV_EXAMPLE_PATH = os.path.join(CONFIG_DIR, "runtime.env.example")


@dataclass(frozen=True)
class ConfigField:
    key: str
    section: str
    label: str
    kind: str
    default: str
    description: str
    restart_required: bool
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    placeholder: str = ""


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(
        key="RC_PAIR_ENABLED",
        section="安全",
        label="启用配对码验证",
        kind="bool",
        default="1",
        description="远控连接前必须先输入 6 位配对码。",
        restart_required=True,
    ),
    ConfigField(
        key="RC_PAIR_CODE",
        section="安全",
        label="配对码",
        kind="string",
        default="041013",
        description="用于首次信任校验的 6 位数字。",
        restart_required=True,
        placeholder="041013",
    ),
    ConfigField(
        key="RC_PAIR_MAX_ATTEMPTS",
        section="安全",
        label="最大失败次数",
        kind="int",
        default="3",
        description="全局输错达到该次数后，服务立即停服。",
        restart_required=True,
        minimum=1,
        maximum=10,
        step=1,
    ),
    ConfigField(
        key="RC_CAPTURE_BACKEND",
        section="画面",
        label="默认采集方式",
        kind="choice",
        default="auto",
        description="服务启动时优先使用的画面采集模式。",
        restart_required=True,
        choices=("auto", "dxgi", "mss"),
    ),
    ConfigField(
        key="RC_QUALITY",
        section="画面",
        label="默认画质",
        kind="int",
        default="95",
        description="远程画面的默认压缩画质。",
        restart_required=False,
        minimum=10,
        maximum=95,
        step=1,
    ),
    ConfigField(
        key="RC_WEBRTC_FPS",
        section="画面",
        label="默认帧率",
        kind="int",
        default="45",
        description="远程画面的默认目标帧率。",
        restart_required=False,
        minimum=15,
        maximum=120,
        step=1,
    ),
    ConfigField(
        key="RC_WEBRTC_SCALE",
        section="画面",
        label="默认画面倍率",
        kind="float",
        default="1.0",
        description="远程画面的默认缩放倍率。",
        restart_required=False,
        minimum=0.25,
        maximum=1.0,
        step=0.05,
    ),
    ConfigField(
        key="RC_AUDIO_ENABLED",
        section="声音",
        label="启用声音采集",
        kind="bool",
        default="1",
        description="服务启动后默认允许采集系统声音。",
        restart_required=True,
    ),
    ConfigField(
        key="RC_AUDIO_DEVICE_NAME",
        section="声音",
        label="优先声音设备",
        kind="string",
        default="CABLE Output",
        description="系统声音采集优先匹配的设备名提示。",
        restart_required=True,
        placeholder="CABLE Output",
    ),
    ConfigField(
        key="RC_AUDIO_TRANSPORT_DEFAULT_ENABLED",
        section="声音",
        label="默认开启声音传输",
        kind="bool",
        default="1",
        description="新连接默认是否直接开启声音传输。",
        restart_required=True,
    ),
    ConfigField(
        key="RC_SERVER_AUTORESTART",
        section="启动",
        label="异常后自动重启",
        kind="bool",
        default="1",
        description="服务异常退出后是否自动拉起。",
        restart_required=True,
    ),
    ConfigField(
        key="RC_SERVER_RESTART_DELAY_SEC",
        section="启动",
        label="重启等待秒数",
        kind="int",
        default="2",
        description="异常退出后再次启动前的等待时间。",
        restart_required=True,
        minimum=0,
        maximum=30,
        step=1,
    ),
)

CONFIG_FIELDS_BY_KEY = {field.key: field for field in CONFIG_FIELDS}
CONFIG_SECTION_ORDER = ("安全", "画面", "声音", "启动")


def _strip_optional_quotes(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _bool_from_raw(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("", "0", "false", "off", "no"):
        return False
    return True


def _format_value(field: ConfigField, value: Any) -> str:
    if field.kind == "bool":
        return "1" if _bool_from_raw(value) else "0"
    if field.kind == "int":
        num = int(float(value))
        if field.minimum is not None:
            num = max(int(field.minimum), num)
        if field.maximum is not None:
            num = min(int(field.maximum), num)
        return str(num)
    if field.kind == "float":
        num = float(value)
        if field.minimum is not None:
            num = max(float(field.minimum), num)
        if field.maximum is not None:
            num = min(float(field.maximum), num)
        return f"{num:.2f}".rstrip("0").rstrip(".")
    if field.kind == "choice":
        text = str(value or field.default).strip().lower()
        if text not in field.choices:
            text = field.default
        return text
    text = _strip_optional_quotes(str(value if value is not None else field.default))
    if field.key == "RC_PAIR_CODE":
        if len(text) != 6 or not text.isdigit():
            text = field.default
    return text


def normalize_value(key: str, value: Any) -> str:
    field = CONFIG_FIELDS_BY_KEY[key]
    return _format_value(field, value)


def parse_value(key: str, value: Any) -> Any:
    field = CONFIG_FIELDS_BY_KEY[key]
    text = normalize_value(key, value)
    if field.kind == "bool":
        return text == "1"
    if field.kind == "int":
        return int(text)
    if field.kind == "float":
        return float(text)
    return text


def default_config_map() -> dict[str, str]:
    return {field.key: field.default for field in CONFIG_FIELDS}


def load_runtime_env(path: str = RUNTIME_ENV_PATH) -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    values: dict[str, str] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if key not in CONFIG_FIELDS_BY_KEY:
                continue
            values[key] = normalize_value(key, _strip_optional_quotes(raw_value))
    return values


def apply_runtime_env_to_os_environ(
    *,
    overwrite: bool = False,
    environ: dict[str, str] | None = None,
    path: str = RUNTIME_ENV_PATH,
) -> dict[str, str]:
    env = environ if environ is not None else os.environ
    loaded = load_runtime_env(path)
    for key, value in loaded.items():
        if overwrite or key not in env:
            env[key] = value
    return loaded


def build_effective_config(
    environ: dict[str, str] | None = None,
    stored: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    env = environ if environ is not None else os.environ
    saved = stored if stored is not None else load_runtime_env()
    items: list[dict[str, Any]] = []
    for field in CONFIG_FIELDS:
        if field.key in env:
            raw_value = env[field.key]
            source = "environment"
        elif field.key in saved:
            raw_value = saved[field.key]
            source = "file"
        else:
            raw_value = field.default
            source = "default"
        items.append(
            {
                "key": field.key,
                "section": field.section,
                "label": field.label,
                "kind": field.kind,
                "description": field.description,
                "restart_required": bool(field.restart_required),
                "default": parse_value(field.key, field.default),
                "value": parse_value(field.key, raw_value),
                "source": source,
                "minimum": field.minimum,
                "maximum": field.maximum,
                "step": field.step,
                "choices": list(field.choices),
                "placeholder": field.placeholder,
            }
        )
    return items


def render_runtime_env(values: dict[str, Any] | None = None) -> str:
    source = values or default_config_map()
    lines = [
        "# 远程控制运行配置",
        "# 可以直接手动编辑；这里的值会覆盖代码内置默认值。",
        "",
    ]
    for section in CONFIG_SECTION_ORDER:
        lines.append(f"# {section}")
        for field in CONFIG_FIELDS:
            if field.section != section:
                continue
            value = normalize_value(field.key, source.get(field.key, field.default))
            lines.append(f"{field.key}={value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def ensure_runtime_example(path: str = RUNTIME_ENV_EXAMPLE_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_runtime_env(default_config_map()))
    return path


def save_runtime_env(values: dict[str, Any], path: str = RUNTIME_ENV_PATH) -> dict[str, str]:
    normalized = {field.key: normalize_value(field.key, values.get(field.key, field.default)) for field in CONFIG_FIELDS}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_runtime_env(normalized))
    return normalized
