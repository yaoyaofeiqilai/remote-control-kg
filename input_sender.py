"""Backward-compatible input sender import bridge."""

import os
import sys


def _ensure_src_on_path():
    root = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(root, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)


_ensure_src_on_path()

from remote_control.input_sender import *  # noqa: F401,F403,E402
