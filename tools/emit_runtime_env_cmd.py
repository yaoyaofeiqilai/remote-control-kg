#!/usr/bin/env python3
"""Emit batch-safe commands for config/runtime.env."""

from __future__ import annotations

import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from remote_control.runtime_config import CONFIG_FIELDS, load_runtime_env  # noqa: E402


def main() -> int:
    values = load_runtime_env()
    if not values:
        return 0
    for field in CONFIG_FIELDS:
        value = values.get(field.key)
        if value is None:
            continue
        safe_value = str(value).replace('"', "")
        print(f'if not defined {field.key} set "{field.key}={safe_value}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
