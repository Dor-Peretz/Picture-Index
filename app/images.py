from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"}
THUMB_EDGE = 960


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES and path.is_file() and not path.name.startswith(".")


def _exif_datetime(image: Image.Image) -> str | None:
    try:
        exif = image.getexif()
    except Exception:
        return None
    raw = exif.get(36867) or exif.get(306)
    if not isinstance(raw, str):
        return None
    text = raw.replace("\x00", "").strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def read_image(path: Path, thumb_path: Path) -> dict:
    with Image.open(path) as image:
        image.seek(0)
        taken_at = _exif_datetime(image)
        framed = ImageOps.exif_transpose(image)
        if framed.mode not in ("RGB", "L"):
            framed = framed.convert("RGB")
        elif framed.mode == "L":
            framed = framed.convert("RGB")
        width, height = framed.size
        framed.thumbnail((THUMB_EDGE, THUMB_EDGE))
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        framed.save(thumb_path, format="JPEG", quality=82, optimize=True)
    return {"width": width, "height": height, "taken_at": taken_at}


def open_error(exc: Exception) -> str:
    if isinstance(exc, UnidentifiedImageError):
        return "Unrecognized image"
    return str(exc) or exc.__class__.__name__
