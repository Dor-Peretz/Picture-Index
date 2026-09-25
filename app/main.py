from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db
from app.faces import attach_boxes, merge_clusters, set_avatar
from app.fs import list_folders
from app.images import scan_details
from app.paths import face_dir, thumb_dir, web_dir
from app.scanner import active_job, cancel_job, get_job, pause_job, resume_job, start_scan
from app.settings import load_settings, save_settings

WEB_DIR = web_dir()

app = FastAPI(title="Picture Index", docs_url=None, redoc_url=None)
db.init_db()


class ScanRequest(BaseModel):
    path: str | None = None
    recursive: bool | None = None
    force: bool = False


class SettingsUpdate(BaseModel):
    folder: str | None = None
    scan_subfolders: bool | None = None


class UnindexRequest(BaseModel):
    ids: list[int] = []


class AssignPhotosRequest(BaseModel):
    ids: list[int] = []
    cluster_id: int


class AvatarUpdate(BaseModel):
    photo_id: int
    face_id: int


class FaceAssign(BaseModel):
    cluster_id: int


class ManualFace(BaseModel):
    cluster_id: int | None = None
    label: str = ""
    x: float
    y: float
    w: float
    h: float


class FaceRename(BaseModel):
    label: str = ""


class FaceFavorite(BaseModel):
    favorite: bool = False


class FaceMerge(BaseModel):
    keep_id: int
    drop_id: int


def _open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


@app.get("/api/status")
def status() -> dict:
    conn = db.get_connection()
    try:
        settings = load_settings()
        return {
            "photos": db.photo_count(conn),
            "folder": settings.get("folder") or "",
            "settings": settings,
            "job": active_job(),
        }
    finally:
        conn.close()


@app.get("/api/settings")
def get_settings() -> dict:
    return load_settings()


@app.put("/api/settings")
def put_settings(body: SettingsUpdate) -> dict:
    return save_settings(body.model_dump(exclude_none=True))


@app.get("/api/fs")
def browse(path: str = "") -> dict:
    return list_folders(path)


@app.post("/api/scan")
def scan(body: ScanRequest) -> dict:
    try:
        return start_scan(body.path, recursive=body.recursive, force=body.force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    found = get_job(job_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return found


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str) -> dict:
    cancel_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/pause")
def pause(job_id: str) -> dict:
    pause_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/resume")
def resume(job_id: str) -> dict:
    resume_job(job_id)
    return {"ok": True}


@app.get("/api/folders")
def folders() -> dict:
    conn = db.get_connection()
    try:
        return {"folders": db.list_folders(conn)}
    finally:
        conn.close()


@app.get("/api/locations")
def locations(
    q: str = "",
    folder: str = "",
    taken_from: str = "",
    taken_to: str = "",
    face: int | None = None,
) -> dict:
    conn = db.get_connection()
    try:
        return {
            "items": db.list_locations(
                conn,
                query=q,
                folder=folder,
                taken_from=taken_from,
                taken_to=taken_to,
                face=face,
            )
        }
    finally:
        conn.close()


@app.get("/api/photos")
def photos(
    q: str = "",
    folder: str = "",
    taken_from: str = "",
    taken_to: str = "",
    face: int | None = None,
    limit: int = Query(default=80, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    conn = db.get_connection()
    try:
        return db.search_photos(
            conn,
            query=q,
            folder=folder,
            taken_from=taken_from,
            taken_to=taken_to,
            face=face,
            limit=limit,
            offset=offset,
        )
    finally:
        conn.close()


@app.get("/api/photos/{photo_id}")
def photo(photo_id: int) -> dict:
    conn = db.get_connection()
    try:
        row = db.get_photo(conn, photo_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        item = dict(row)
        try:
            attach_boxes(conn, photo_id, thumb_dir() / f"{photo_id}.jpg")
        except Exception:
            pass
        item["faces"] = db.faces_for_photo(conn, photo_id)
    finally:
        conn.close()
    try:
        item["details"] = scan_details(Path(item["path"]))
    except Exception as exc:
        item["details"] = []
        item["detail_error"] = str(exc) or exc.__class__.__name__
    return item


@app.get("/api/faces")
def faces() -> dict:
    conn = db.get_connection()
    try:
        return {"faces": db.list_face_clusters(conn)}
    finally:
        conn.close()


@app.put("/api/faces/{cluster_id}/favorite")
def favorite_face(cluster_id: int, body: FaceFavorite) -> dict:
    conn = db.get_connection()
    try:
        try:
            db.set_favorite(conn, cluster_id, body.favorite)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        conn.commit()
    finally:
        conn.close()
    return {"id": cluster_id, "favorite": body.favorite}


@app.put("/api/faces/{cluster_id}")
def rename_face(cluster_id: int, body: FaceRename) -> dict:
    conn = db.get_connection()
    try:
        db.rename_face(conn, cluster_id, body.label)
        conn.commit()
    finally:
        conn.close()
    return {"id": cluster_id, "label": body.label.strip()}


@app.post("/api/faces/merge")
def merge_faces(body: FaceMerge) -> dict:
    conn = db.get_connection()
    try:
        try:
            keep_id = merge_clusters(conn, body.keep_id, body.drop_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"id": keep_id}


@app.delete("/api/faces/{cluster_id}")
def remove_face(cluster_id: int) -> dict:
    conn = db.get_connection()
    try:
        if not db.delete_face_cluster(conn, cluster_id):
            raise HTTPException(status_code=404, detail="Face not found")
        conn.commit()
    finally:
        conn.close()
    (face_dir() / f"{cluster_id}.jpg").unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/faces/{cluster_id}/avatar")
def face_avatar(cluster_id: int, body: AvatarUpdate) -> dict:
    conn = db.get_connection()
    try:
        cluster = conn.execute("SELECT id FROM face_clusters WHERE id = ?", (cluster_id,)).fetchone()
        row = conn.execute(
            "SELECT x, y, w, h FROM faces WHERE id = ? AND photo_id = ? AND cluster_id = ?",
            (body.face_id, body.photo_id, cluster_id),
        ).fetchone()
        if cluster is None or row is None or row["x"] is None:
            raise HTTPException(status_code=404, detail="Face not found")
        box = (float(row["x"]), float(row["y"]), float(row["w"]), float(row["h"]))
    finally:
        conn.close()
    thumb = thumb_dir() / f"{body.photo_id}.jpg"
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    set_avatar(cluster_id, thumb, box)
    return {"ok": True}


@app.get("/api/faces/{cluster_id}/thumb")
def face_thumb(cluster_id: int) -> FileResponse:
    path = face_dir() / f"{cluster_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Face not found")
    return FileResponse(path, media_type="image/jpeg")


@app.delete("/api/photos/{photo_id}")
def remove_photo(photo_id: int) -> dict:
    conn = db.get_connection()
    try:
        row = db.get_photo(conn, photo_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        db.exclude_path(conn, row["path"])
        removed_clusters = db.delete_photo(conn, photo_id)
        conn.commit()
    finally:
        conn.close()
    (thumb_dir() / f"{photo_id}.jpg").unlink(missing_ok=True)
    for cluster_id in removed_clusters:
        (face_dir() / f"{cluster_id}.jpg").unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/photos/assign")
def assign_photos(body: AssignPhotosRequest) -> dict:
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        return {"ok": True, "assigned": 0}
    conn = db.get_connection()
    try:
        try:
            assigned, removed_clusters = db.assign_photos(conn, ids, body.cluster_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        conn.commit()
    finally:
        conn.close()
    for cluster_id in removed_clusters:
        (face_dir() / f"{cluster_id}.jpg").unlink(missing_ok=True)
    return {"ok": True, "assigned": assigned}


@app.post("/api/photos/unindex")
def unindex_photos(body: UnindexRequest) -> dict:
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        return {"ok": True, "removed": 0}
    conn = db.get_connection()
    try:
        removed_clusters = db.unindex_photos(conn, ids)
        conn.commit()
    finally:
        conn.close()
    for photo_id in ids:
        (thumb_dir() / f"{photo_id}.jpg").unlink(missing_ok=True)
    for cluster_id in removed_clusters:
        (face_dir() / f"{cluster_id}.jpg").unlink(missing_ok=True)
    return {"ok": True, "removed": len(ids)}


@app.post("/api/photos/{photo_id}/faces")
def add_photo_face(photo_id: int, body: ManualFace) -> dict:
    conn = db.get_connection()
    try:
        try:
            face_id, cluster_id, created = db.add_manual_face(
                conn,
                photo_id,
                body.x,
                body.y,
                body.w,
                body.h,
                body.cluster_id,
                body.label,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    finally:
        conn.close()
    if created:
        thumb = thumb_dir() / f"{photo_id}.jpg"
        if thumb.is_file():
            try:
                set_avatar(cluster_id, thumb, (body.x, body.y, body.w, body.h))
            except Exception:
                pass
    return {"ok": True, "id": face_id, "cluster_id": cluster_id}


@app.delete("/api/photos/{photo_id}/faces/{face_id}")
def remove_photo_face(photo_id: int, face_id: int) -> dict:
    conn = db.get_connection()
    try:
        try:
            removed = db.remove_face_detection(conn, photo_id, face_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        conn.commit()
    finally:
        conn.close()
    if removed:
        (face_dir() / f"{removed}.jpg").unlink(missing_ok=True)
    return {"ok": True}


@app.put("/api/photos/{photo_id}/faces/{face_id}")
def reassign_photo_face(photo_id: int, face_id: int, body: FaceAssign) -> dict:
    conn = db.get_connection()
    try:
        try:
            removed = db.reassign_face_detection(conn, photo_id, face_id, body.cluster_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        conn.commit()
    finally:
        conn.close()
    if removed:
        (face_dir() / f"{removed}.jpg").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/photos/{photo_id}/thumb")
def thumb(photo_id: int) -> FileResponse:
    path = thumb_dir() / f"{photo_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/photos/{photo_id}/open")
def open_photo(photo_id: int) -> dict:
    conn = db.get_connection()
    try:
        row = db.get_photo(conn, photo_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    target = Path(row["path"])
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File is no longer on disk")
    _open_path(str(target))
    return {"ok": True}


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
