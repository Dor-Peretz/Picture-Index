from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Picture-Index"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
    else:
        base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def web_dir() -> Path:
    return resource_root() / "web"


def thumb_dir() -> Path:
    path = user_data_dir() / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def face_dir() -> Path:
    path = user_data_dir() / "faces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_dir() -> Path:
    path = user_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path
