from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

from app.paths import user_data_dir

TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def tessdata_dir() -> Path:
    folder = user_data_dir() / "tessdata"
    folder.mkdir(parents=True, exist_ok=True)
    install = TESSERACT.parent / "tessdata"
    if install.is_dir():
        english = install / "eng.traineddata"
        if english.is_file() and not (folder / "eng.traineddata").is_file():
            shutil.copy2(english, folder / "eng.traineddata")
        for name in ("configs", "tessconfigs"):
            source = install / name
            target = folder / name
            if source.is_dir() and not target.exists():
                shutil.copytree(source, target)
    return folder


def tesseract_cmd() -> str | None:
    env = os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_PATH")
    if env and Path(env).is_file():
        return env
    which = shutil.which("tesseract")
    if which:
        return which
    if TESSERACT.is_file():
        return str(TESSERACT)
    return None


def read_words(path: Path) -> str:
    command = tesseract_cmd()
    if not command:
        raise RuntimeError("Tesseract is not installed")
    languages = tessdata_dir()
    if not (languages / "heb.traineddata").is_file() or not (languages / "eng.traineddata").is_file():
        raise RuntimeError("Hebrew and English OCR languages are not installed")
    with Image.open(path) as image:
        framed = ImageOps.exif_transpose(image).convert("RGB")
        long_edge = max(framed.size)
        if long_edge > 2000:
            scale = 2000 / long_edge
            framed = framed.resize(
                (max(1, int(framed.width * scale)), max(1, int(framed.height * scale))),
                Image.Resampling.LANCZOS,
            )
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        prepared = Path(handle.name)
        handle.close()
        framed.save(prepared, format="PNG")
    try:
        result = subprocess.run(
            [
                command,
                str(prepared),
                "stdout",
                "-l",
                "heb+eng",
                "--tessdata-dir",
                str(languages),
                "--psm",
                "11",
                "tsv",
            ],
            capture_output=True,
            check=False,
        )
    finally:
        prepared.unlink(missing_ok=True)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "Could not read words from the photo")
    words: list[str] = []
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        try:
            confidence = float(parts[10])
        except ValueError:
            continue
        token = parts[11].strip()
        letters = [char for char in token if char.isalpha()]
        if confidence < 40 or len(letters) < 3:
            continue
        words.append(token)
    return " ".join(words)
