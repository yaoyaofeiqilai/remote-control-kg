#!/usr/bin/env python3
"""Backward-compatible entry point for the remote control server."""

import os
import sys


def _ensure_src_on_path():
    root = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(root, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)


_ensure_src_on_path()

from remote_control.server_app import main  # noqa: E402


if __name__ == "__main__":
    main()
