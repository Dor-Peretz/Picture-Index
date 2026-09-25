from __future__ import annotations

import re
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
_WHATSAPP_STAMP = re.compile(
    r"WhatsApp Image (\d{4})-(\d{2})-(\d{2}) at (\d{2})\.(\d{2})\.(\d{2})",
    re.IGNORECASE,
)
_WHATSAPP_DAY = re.compile(r"(?:IMG|STK)-(\d{4})(\d{2})(\d{2})-WA\d+", re.IGNORECASE)


def _valid_when(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> str | None:
    if year < 1990 or year > datetime.now().year + 1:
        return None
    try:
        return datetime(year, month, day, hour, minute, second).isoformat(timespec="seconds")
    except ValueError:
        return None


def date_from_name(filename: str) -> str | None:
    """WhatsApp puts the send date in the filename when the photo has no camera date."""
    stamped = _WHATSAPP_STAMP.search(filename)
    if stamped:
        year, month, day, hour, minute, second = (int(part) for part in stamped.groups())
        return _valid_when(year, month, day, hour, minute, second)
    day_only = _WHATSAPP_DAY.search(filename)
    if day_only:
        year, month, day = (int(part) for part in day_only.groups())
        return _valid_when(year, month, day)
    return None


def is_image(path: Path) -> bool:
    # Android keeps deleted camera photos as ".trashed-<id>-<name>.jpg".
    return path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()


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


def read_location(path: Path) -> tuple[float, float] | None:
    with Image.open(path) as image:
        image.seek(0)
        try:
            exif = image.getexif()
        except Exception:
            return None
        text = _gps_degrees(exif) if exif else None
    if not text:
        return None
    latitude, longitude = text.split(",")
    return float(latitude), float(longitude.strip())


def read_image(path: Path, thumb_path: Path) -> dict:
    with Image.open(path) as image:
        image.seek(0)
        taken_at = _exif_datetime(image) or date_from_name(path.name)
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


def _number(value) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2 and value[1]:
            return float(value[0]) / float(value[1])
        if hasattr(value, "numerator") and hasattr(value, "denominator") and value.denominator:
            return float(value.numerator) / float(value.denominator)
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).replace("\x00", "").strip()
    return text


def _gps_degrees(exif) -> str | None:
    try:
        gps = exif.get_ifd(34853)
    except Exception:
        return None
    lat = gps.get(2)
    lng = gps.get(4)
    if not lat or not lng:
        return None
    def pack(parts, ref: str) -> float | None:
        degrees, minutes, seconds = (_number(parts[0]), _number(parts[1]), _number(parts[2]))
        if degrees is None or minutes is None or seconds is None:
            return None
        sign = -1 if ref in {"S", "W"} else 1
        return sign * (degrees + minutes / 60 + seconds / 3600)
    latitude = pack(lat, _text(gps.get(1)))
    longitude = pack(lng, _text(gps.get(3)))
    if latitude is None or longitude is None:
        return None
    return f"{latitude:.5f}, {longitude:.5f}"


def scan_details(path: Path) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    with Image.open(path) as image:
        image.seek(0)
        if image.format:
            details.append({"label": "Format", "value": image.format})
        try:
            exif = image.getexif()
        except Exception:
            exif = {}
        wanted = (
            (271, "Camera make"),
            (272, "Camera model"),
            (42036, "Lens"),
            (305, "Software"),
            (33437, "Aperture"),
            (33434, "Exposure"),
            (34855, "ISO"),
            (37386, "Focal length"),
        )
        for tag, label in wanted:
            raw = exif.get(tag) if exif else None
            if raw in (None, ""):
                continue
            number = _number(raw)
            if label == "Aperture" and number is not None:
                value = f"f/{number:.1f}"
            elif label == "Exposure" and number is not None and number > 0:
                value = f"1/{round(1 / number)}" if number < 1 else f"{number:.2f} s"
            elif label == "Focal length" and number is not None:
                value = f"{number:.1f} mm"
            elif label == "ISO" and number is not None:
                value = str(int(number))
            else:
                value = _text(raw)
            if value:
                details.append({"label": label, "value": value})
        location = _gps_degrees(exif) if exif else None
        if location:
            details.append({"label": "Location", "value": location})
    return details


def open_error(exc: Exception) -> str:
    if isinstance(exc, UnidentifiedImageError):
        return "Unrecognized image"
    return str(exc) or exc.__class__.__name__
