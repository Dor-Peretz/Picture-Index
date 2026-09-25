from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import db
from app.images import is_image, open_error, read_image
from app.paths import thumb_dir
from app.settings import load_settings, save_settings

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_scan_lock = threading.Lock()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **changes: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(changes)


def _job_flag(job_id: str, name: str) -> bool:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return bool(job and job.get(name))


def cancel_job(job_id: str) -> None:
    _update_job(job_id, cancelled=True)


def pause_job(job_id: str) -> None:
    _update_job(job_id, paused=True, status="paused", stage="Paused")


def resume_job(job_id: str) -> None:
    _update_job(job_id, paused=False)


def _wait_if_paused(job_id: str) -> None:
    while _job_flag(job_id, "paused") and not _job_flag(job_id, "cancelled"):
        time.sleep(0.25)


def walk_images(root: Path, recursive: bool) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.glob("*")
    found: list[Path] = []
    for path in iterator:
        try:
            if is_image(path):
                found.append(path)
        except OSError:
            continue
    return sorted(found, key=lambda item: str(item).lower())


def _unchanged(existing: Any, size: int, mtime: float) -> bool:
    if existing is None or existing["error"]:
        return False
    if int(existing["size"] or -1) != size:
        return False
    return abs(float(existing["mtime"] or 0) - mtime) < 1


def _index_file(conn: Any, path: Path, *, force: bool) -> str:
    stat = path.stat()
    existing = db.find_by_path(conn, str(path))
    if not force and _unchanged(existing, stat.st_size, stat.st_mtime):
        return "skipped"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {
        "path": str(path),
        "filename": path.name,
        "folder": str(path.parent),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "width": None,
        "height": None,
        "taken_at": None,
        "error": None,
        "indexed_at": now,
    }
    photo_id = existing["id"] if existing else None
    try:
        placeholder_id = photo_id
        if placeholder_id is None:
            record["error"] = None
            placeholder_id = db.upsert_photo(conn, record)
            conn.commit()
        thumb = thumb_dir() / f"{placeholder_id}.jpg"
        meta = read_image(path, thumb)
        record["width"] = meta["width"]
        record["height"] = meta["height"]
        record["taken_at"] = meta["taken_at"]
        record["error"] = None
    except Exception as exc:
        record["error"] = open_error(exc)
    db.upsert_photo(conn, record)
    conn.commit()
    return "error" if record["error"] else "indexed"


def _prune(conn: Any, root: Path, seen: set[str]) -> int:
    removed = 0
    for row in db.paths_under(conn, str(root)):
        if row["path"] in seen:
            continue
        if not Path(row["path"]).exists():
            thumb = thumb_dir() / f"{row['id']}.jpg"
            thumb.unlink(missing_ok=True)
            db.delete_photo(conn, int(row["id"]))
            removed += 1
    conn.commit()
    return removed


def _run(job_id: str, root: Path, recursive: bool, force: bool) -> None:
    try:
        _update_job(job_id, status="running", stage="Finding photos")
        files = walk_images(root, recursive)
        _update_job(job_id, total=len(files), stage=f"0 / {len(files)}")
        conn = db.get_connection()
        seen: set[str] = set()
        try:
            for index, path in enumerate(files, start=1):
                _wait_if_paused(job_id)
                if _job_flag(job_id, "cancelled"):
                    _update_job(job_id, status="cancelled", stage="Cancelled")
                    return
                _update_job(job_id, stage=path.name, done=index - 1)
                seen.add(str(path))
                try:
                    outcome = _index_file(conn, path, force=force)
                except Exception as exc:
                    outcome = "error"
                    _update_job(job_id, errors=(_job_errors(job_id) + [{"path": str(path), "error": str(exc)}])[-20:])
                job = get_job(job_id) or {}
                _update_job(
                    job_id,
                    done=index,
                    indexed=int(job.get("indexed") or 0) + (1 if outcome == "indexed" else 0),
                    skipped=int(job.get("skipped") or 0) + (1 if outcome == "skipped" else 0),
                    failed=int(job.get("failed") or 0) + (1 if outcome == "error" else 0),
                )
            if not _job_flag(job_id, "cancelled"):
                removed = _prune(conn, root, seen)
                _update_job(job_id, removed=removed, status="done", stage="Done", done=len(files))
        finally:
            conn.close()
    except Exception as exc:
        _update_job(job_id, status="error", stage=str(exc))


def _job_errors(job_id: str) -> list:
    job = get_job(job_id) or {}
    return list(job.get("errors") or [])


def start_scan(folder: str | None = None, *, recursive: bool | None = None, force: bool = False) -> dict[str, Any]:
    if not _scan_lock.acquire(blocking=False):
        raise RuntimeError("A scan is already running")
    settings = load_settings()
    folder_path = (folder or settings.get("folder") or "").strip()
    root = Path(folder_path).expanduser()
    if not folder_path or not root.is_dir():
        _scan_lock.release()
        raise FileNotFoundError("Choose a folder that exists")
    save_settings({"folder": str(root), "scan_subfolders": settings.get("scan_subfolders", True) if recursive is None else recursive})
    recursive_flag = settings.get("scan_subfolders", True) if recursive is None else recursive
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "stage": "Queued",
        "total": 0,
        "done": 0,
        "indexed": 0,
        "skipped": 0,
        "failed": 0,
        "removed": 0,
        "errors": [],
        "paused": False,
        "cancelled": False,
        "folder": str(root),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    def runner() -> None:
        try:
            _run(job_id, root, bool(recursive_flag), force)
        finally:
            _scan_lock.release()

    threading.Thread(target=runner, daemon=True).start()
    return dict(job)
