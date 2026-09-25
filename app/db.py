from __future__ import annotations

import sqlite3
from typing import Any

from app.paths import user_data_dir

DATA_DIR = user_data_dir()
DB_PATH = DATA_DIR / "catalog.db"

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    folder TEXT NOT NULL,
    size INTEGER,
    mtime REAL,
    width INTEGER,
    height INTEGER,
    taken_at TEXT,
    error TEXT,
    indexed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder);
CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at);

CREATE TABLE IF NOT EXISTS face_clusters (
    id INTEGER PRIMARY KEY,
    centroid BLOB NOT NULL,
    count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES face_clusters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);

CREATE TABLE IF NOT EXISTS excluded (
    path TEXT PRIMARY KEY
);

CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts USING fts5(
    filename,
    folder,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
        if "faces_done" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN faces_done INTEGER NOT NULL DEFAULT 0")
        cluster_columns = {row[1] for row in conn.execute("PRAGMA table_info(face_clusters)").fetchall()}
        if cluster_columns and "label" not in cluster_columns:
            conn.execute("ALTER TABLE face_clusters ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        if cluster_columns and "favorite" not in cluster_columns:
            conn.execute("ALTER TABLE face_clusters ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        if "objects" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN objects TEXT")
        if "latitude" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN latitude REAL")
        if "longitude" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN longitude REAL")
        if "gps_done" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN gps_done INTEGER NOT NULL DEFAULT 0")
        if "text" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN text TEXT")
        if "text_done" not in columns:
            conn.execute("ALTER TABLE photos ADD COLUMN text_done INTEGER NOT NULL DEFAULT 0")
        face_columns = {row[1] for row in conn.execute("PRAGMA table_info(faces)").fetchall()}
        for column in ("x", "y", "w", "h"):
            if column not in face_columns:
                conn.execute(f"ALTER TABLE faces ADD COLUMN {column} REAL")
        conn.commit()
    finally:
        conn.close()


def photo_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM photos").fetchone()
    return int(row["n"])


def find_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM photos WHERE path = ?", (path,)).fetchone()


def get_photo(conn: sqlite3.Connection, photo_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()


def list_folders(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT folder FROM photos ORDER BY folder").fetchall()
    return [row["folder"] for row in rows]


def delete_photo(conn: sqlite3.Connection, photo_id: int) -> list[int]:
    clusters = [
        int(row["cluster_id"])
        for row in conn.execute("SELECT DISTINCT cluster_id FROM faces WHERE photo_id = ?", (photo_id,))
    ]
    conn.execute("DELETE FROM photos_fts WHERE rowid = ?", (photo_id,))
    conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    removed: list[int] = []
    for cluster_id in clusters:
        left = conn.execute("SELECT COUNT(*) AS n FROM faces WHERE cluster_id = ?", (cluster_id,)).fetchone()["n"]
        if int(left) == 0:
            conn.execute("DELETE FROM face_clusters WHERE id = ?", (cluster_id,))
            removed.append(cluster_id)
        else:
            conn.execute("UPDATE face_clusters SET count = ? WHERE id = ?", (int(left), cluster_id))
    return removed


def unindex_photos(conn: sqlite3.Connection, photo_ids: list[int]) -> list[int]:
    removed: list[int] = []
    unique = list(dict.fromkeys(int(photo_id) for photo_id in photo_ids))
    for start in range(0, len(unique), 400):
        chunk = unique[start : start + 400]
        marks = ",".join("?" * len(chunk))
        paths = conn.execute(f"SELECT path FROM photos WHERE id IN ({marks})", chunk).fetchall()
        conn.executemany("INSERT OR IGNORE INTO excluded(path) VALUES (?)", [(row["path"],) for row in paths])
        clusters = [
            int(row["cluster_id"])
            for row in conn.execute(f"SELECT DISTINCT cluster_id FROM faces WHERE photo_id IN ({marks})", chunk)
        ]
        conn.execute(f"DELETE FROM photos_fts WHERE rowid IN ({marks})", chunk)
        conn.execute(f"DELETE FROM photos WHERE id IN ({marks})", chunk)
        for cluster_id in clusters:
            left = conn.execute("SELECT COUNT(*) AS n FROM faces WHERE cluster_id = ?", (cluster_id,)).fetchone()["n"]
            if int(left) == 0:
                conn.execute("DELETE FROM face_clusters WHERE id = ?", (cluster_id,))
                removed.append(cluster_id)
            else:
                conn.execute("UPDATE face_clusters SET count = ? WHERE id = ?", (int(left), cluster_id))
    return removed


def exclude_path(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("INSERT OR IGNORE INTO excluded(path) VALUES (?)", (path,))


def is_excluded(conn: sqlite3.Connection, path: str) -> bool:
    row = conn.execute("SELECT 1 FROM excluded WHERE path = ?", (path,)).fetchone()
    return row is not None


def clear_faces(conn: sqlite3.Connection, photo_id: int) -> None:
    clusters = [
        int(row["cluster_id"])
        for row in conn.execute("SELECT DISTINCT cluster_id FROM faces WHERE photo_id = ?", (photo_id,))
    ]
    conn.execute("DELETE FROM faces WHERE photo_id = ?", (photo_id,))
    for cluster_id in clusters:
        left = conn.execute(
            "SELECT COUNT(*) AS n FROM faces WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchone()["n"]
        if int(left) == 0:
            conn.execute("DELETE FROM face_clusters WHERE id = ?", (cluster_id,))
        else:
            conn.execute("UPDATE face_clusters SET count = ? WHERE id = ?", (int(left), cluster_id))
    conn.execute("UPDATE photos SET faces_done = 0 WHERE id = ?", (photo_id,))


def faces_for_photo(conn: sqlite3.Connection, photo_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT faces.id, faces.cluster_id, faces.x, faces.y, faces.w, faces.h, face_clusters.label
        FROM faces
        JOIN face_clusters ON face_clusters.id = faces.cluster_id
        WHERE faces.photo_id = ?
        ORDER BY face_clusters.favorite DESC, CASE WHEN TRIM(face_clusters.label) = '' THEN 1 ELSE 0 END, faces.id
        """,
        (photo_id,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "cluster_id": int(row["cluster_id"]),
            "label": row["label"] or "",
            "x": row["x"],
            "y": row["y"],
            "w": row["w"],
            "h": row["h"],
        }
        for row in rows
    ]


def _cluster_count(conn: sqlite3.Connection, cluster_id: int) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM faces WHERE cluster_id = ?", (cluster_id,)).fetchone()
    return int(row["n"])


def _drop_cluster_if_empty(conn: sqlite3.Connection, cluster_id: int) -> int | None:
    left = _cluster_count(conn, cluster_id)
    if left == 0:
        conn.execute("DELETE FROM face_clusters WHERE id = ?", (cluster_id,))
        return cluster_id
    conn.execute("UPDATE face_clusters SET count = ? WHERE id = ?", (left, cluster_id))
    return None


def add_manual_face(
    conn: sqlite3.Connection,
    photo_id: int,
    x: float,
    y: float,
    w: float,
    h: float,
    cluster_id: int | None = None,
    label: str = "",
) -> tuple[int, int, bool]:
    photo = conn.execute("SELECT id FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if photo is None:
        raise KeyError("Photo not found")
    width = min(max(float(w), 0.04), 1.0)
    height = min(max(float(h), 0.04), 1.0)
    left = min(max(float(x), 0.0), 1.0 - width)
    top = min(max(float(y), 0.0), 1.0 - height)
    created = False
    name = label.strip()
    if name:
        existing = conn.execute(
            "SELECT id FROM face_clusters WHERE LOWER(label) = LOWER(?) AND TRIM(label) != ''",
            (name,),
        ).fetchone()
        if existing:
            cluster_id = int(existing["id"])
        else:
            cur = conn.execute(
                "INSERT INTO face_clusters (centroid, count, label) VALUES (?, 0, ?)",
                (b"\x00" * 512, name),
            )
            cluster_id = int(cur.lastrowid)
            created = True
    elif cluster_id is None:
        raise ValueError("Choose a person")
    else:
        target = conn.execute("SELECT id FROM face_clusters WHERE id = ?", (cluster_id,)).fetchone()
        if target is None:
            raise KeyError("Face not found")
    blank = conn.execute(
        "SELECT id FROM faces WHERE photo_id = ? AND cluster_id = ? AND x IS NULL LIMIT 1",
        (photo_id, cluster_id),
    ).fetchone()
    if blank:
        face_id = int(blank["id"])
        conn.execute(
            "UPDATE faces SET x = ?, y = ?, w = ?, h = ? WHERE id = ?",
            (left, top, width, height, face_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO faces (photo_id, cluster_id, x, y, w, h) VALUES (?, ?, ?, ?, ?, ?)",
            (photo_id, cluster_id, left, top, width, height),
        )
        face_id = int(cur.lastrowid)
    _drop_cluster_if_empty(conn, int(cluster_id))
    conn.execute("UPDATE photos SET faces_done = 1 WHERE id = ?", (photo_id,))
    return face_id, int(cluster_id), created


def remove_face_detection(conn: sqlite3.Connection, photo_id: int, face_id: int) -> int | None:
    row = conn.execute(
        "SELECT cluster_id FROM faces WHERE id = ? AND photo_id = ?",
        (face_id, photo_id),
    ).fetchone()
    if row is None:
        raise KeyError("Face not found")
    cluster_id = int(row["cluster_id"])
    conn.execute("DELETE FROM faces WHERE id = ?", (face_id,))
    return _drop_cluster_if_empty(conn, cluster_id)


def assign_photos(conn: sqlite3.Connection, photo_ids: list[int], cluster_id: int) -> tuple[int, list[int]]:
    target = conn.execute("SELECT id FROM face_clusters WHERE id = ?", (cluster_id,)).fetchone()
    if target is None:
        raise KeyError("Face not found")
    unique = list(dict.fromkeys(int(photo_id) for photo_id in photo_ids))
    assigned = 0
    touched = {cluster_id}
    for start in range(0, len(unique), 400):
        chunk = unique[start : start + 400]
        marks = ",".join("?" * len(chunk))
        existing = [int(row["id"]) for row in conn.execute(f"SELECT id FROM photos WHERE id IN ({marks})", chunk)]
        if not existing:
            continue
        marks = ",".join("?" * len(existing))
        already = {
            int(row["photo_id"])
            for row in conn.execute(
                f"SELECT photo_id FROM faces WHERE cluster_id = ? AND photo_id IN ({marks})",
                [cluster_id, *existing],
            )
        }
        pending = [photo_id for photo_id in existing if photo_id not in already]
        if not pending:
            continue
        marks = ",".join("?" * len(pending))
        counts = {
            int(row["photo_id"]): int(row["n"])
            for row in conn.execute(
                f"SELECT photo_id, COUNT(*) AS n FROM faces WHERE photo_id IN ({marks}) GROUP BY photo_id",
                pending,
            )
        }
        singles = [photo_id for photo_id in pending if counts.get(photo_id) == 1]
        extras = [photo_id for photo_id in pending if counts.get(photo_id, 0) != 1]
        if singles:
            single_marks = ",".join("?" * len(singles))
            for row in conn.execute(
                f"SELECT DISTINCT cluster_id FROM faces WHERE photo_id IN ({single_marks})",
                singles,
            ):
                touched.add(int(row["cluster_id"]))
            conn.execute(
                f"UPDATE faces SET cluster_id = ? WHERE photo_id IN ({single_marks})",
                [cluster_id, *singles],
            )
        if extras:
            conn.executemany(
                "INSERT INTO faces (photo_id, cluster_id) VALUES (?, ?)",
                [(photo_id, cluster_id) for photo_id in extras],
            )
        conn.execute(f"UPDATE photos SET faces_done = 1 WHERE id IN ({marks})", pending)
        assigned += len(pending)
    removed: list[int] = []
    for cluster in touched:
        dropped = _drop_cluster_if_empty(conn, cluster)
        if dropped:
            removed.append(dropped)
    return assigned, removed


def reassign_face_detection(conn: sqlite3.Connection, photo_id: int, face_id: int, cluster_id: int) -> int | None:
    row = conn.execute(
        "SELECT cluster_id FROM faces WHERE id = ? AND photo_id = ?",
        (face_id, photo_id),
    ).fetchone()
    target = conn.execute("SELECT id FROM face_clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None or target is None:
        raise KeyError("Face not found")
    previous = int(row["cluster_id"])
    if previous == cluster_id:
        return None
    conn.execute("UPDATE faces SET cluster_id = ? WHERE id = ?", (cluster_id, face_id))
    _drop_cluster_if_empty(conn, cluster_id)
    return _drop_cluster_if_empty(conn, previous)


def delete_face_cluster(conn: sqlite3.Connection, cluster_id: int) -> bool:
    row = conn.execute("SELECT id FROM face_clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM face_clusters WHERE id = ?", (cluster_id,))
    return True


def rename_face(conn: sqlite3.Connection, cluster_id: int, label: str) -> None:
    conn.execute("UPDATE face_clusters SET label = ? WHERE id = ?", (label.strip(), cluster_id))


def set_favorite(conn: sqlite3.Connection, cluster_id: int, favorite: bool) -> None:
    row = conn.execute("SELECT id FROM face_clusters WHERE id = ?", (cluster_id,)).fetchone()
    if row is None:
        raise KeyError("Face not found")
    conn.execute(
        "UPDATE face_clusters SET favorite = ? WHERE id = ?",
        (1 if favorite else 0, cluster_id),
    )


def set_text(conn: sqlite3.Connection, photo_id: int, text: str) -> None:
    conn.execute(
        "UPDATE photos SET text = ?, text_done = 1 WHERE id = ?",
        (text, photo_id),
    )


def set_location(conn: sqlite3.Connection, photo_id: int, latitude: float | None, longitude: float | None) -> None:
    conn.execute(
        "UPDATE photos SET latitude = ?, longitude = ?, gps_done = 1 WHERE id = ?",
        (latitude, longitude, photo_id),
    )


def set_objects(conn: sqlite3.Connection, photo_id: int, objects: str) -> None:
    conn.execute("UPDATE photos SET objects = ? WHERE id = ?", (objects, photo_id))


def mark_faces_done(conn: sqlite3.Connection, photo_id: int) -> None:
    conn.execute("UPDATE photos SET faces_done = 1 WHERE id = ?", (photo_id,))


def list_face_clusters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT face_clusters.id, face_clusters.label, face_clusters.favorite, COUNT(DISTINCT faces.photo_id) AS count
        FROM face_clusters
        JOIN faces ON faces.cluster_id = face_clusters.id
        GROUP BY face_clusters.id
        HAVING count > 0
        ORDER BY face_clusters.favorite DESC, CASE WHEN TRIM(face_clusters.label) = '' THEN 1 ELSE 0 END, count DESC, face_clusters.id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "label": row["label"] or "",
            "count": int(row["count"]),
            "favorite": bool(row["favorite"]),
        }
        for row in rows
    ]


def paths_under(conn: sqlite3.Connection, root: str) -> list[sqlite3.Row]:
    prefix = root.rstrip("\\/") 
    like = prefix + "\\%"
    like_fwd = prefix + "/%"
    return conn.execute(
        "SELECT id, path FROM photos WHERE path = ? OR path LIKE ? OR path LIKE ?",
        (prefix, like, like_fwd),
    ).fetchall()


def upsert_photo(conn: sqlite3.Connection, record: dict[str, Any]) -> int:
    existing = find_by_path(conn, record["path"])
    if existing:
        photo_id = int(existing["id"])
        conn.execute(
            """
            UPDATE photos SET
                filename = ?, folder = ?, size = ?, mtime = ?, width = ?, height = ?,
                taken_at = ?, error = ?, indexed_at = ?
            WHERE id = ?
            """,
            (
                record["filename"],
                record["folder"],
                record["size"],
                record["mtime"],
                record["width"],
                record["height"],
                record["taken_at"],
                record["error"],
                record["indexed_at"],
                photo_id,
            ),
        )
        conn.execute("DELETE FROM photos_fts WHERE rowid = ?", (photo_id,))
    else:
        cur = conn.execute(
            """
            INSERT INTO photos (
                path, filename, folder, size, mtime, width, height, taken_at, error, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["path"],
                record["filename"],
                record["folder"],
                record["size"],
                record["mtime"],
                record["width"],
                record["height"],
                record["taken_at"],
                record["error"],
                record["indexed_at"],
            ),
        )
        photo_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO photos_fts(rowid, filename, folder) VALUES (?, ?, ?)",
        (photo_id, record["filename"], record["folder"]),
    )
    return photo_id


def fts_query(text: str) -> str | None:
    parts: list[str] = []
    for raw in text.split():
        token = "".join(ch for ch in raw if ch.isalnum() or ch in "-_'")
        if token:
            parts.append(f'"{token}"*')
    if not parts:
        return None
    return " AND ".join(parts)


def photo_filters(
    *,
    query: str = "",
    folder: str = "",
    taken_from: str = "",
    taken_to: str = "",
    face: int | None = None,
) -> tuple[str, list[Any]]:
    where = ["1 = 1"]
    params: list[Any] = []
    match = fts_query(query)
    if match:
        object_likes = []
        object_params: list[Any] = []
        for raw in query.split():
            token = "".join(ch for ch in raw if ch.isalnum() or ch in "-_'")
            if token:
                object_likes.append("(LOWER(photos.objects) LIKE ? OR LOWER(photos.text) LIKE ?)")
                object_params.append(f"%{token.lower()}%")
                object_params.append(f"%{token.lower()}%")
        object_sql = " OR ".join(object_likes) if object_likes else "0"
        where.append(
            f"(photos.id IN (SELECT rowid FROM photos_fts WHERE photos_fts MATCH ?) OR {object_sql})"
        )
        params.append(match)
        params.extend(object_params)
    if folder:
        where.append("photos.folder = ?")
        params.append(folder)
    if taken_from:
        where.append("photos.taken_at >= ?")
        params.append(taken_from)
    if taken_to:
        where.append("photos.taken_at < ?")
        params.append(taken_to + "T99")
    if face:
        where.append("photos.id IN (SELECT photo_id FROM faces WHERE cluster_id = ?)")
        params.append(face)
    return " AND ".join(where), params


def search_photos(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    folder: str = "",
    taken_from: str = "",
    taken_to: str = "",
    face: int | None = None,
    limit: int = 80,
    offset: int = 0,
) -> dict[str, Any]:
    sql_where, params = photo_filters(
        query=query, folder=folder, taken_from=taken_from, taken_to=taken_to, face=face
    )
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM photos WHERE {sql_where}",
        params,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""
        SELECT photos.* FROM photos
        WHERE {sql_where}
        ORDER BY photos.taken_at IS NULL, photos.taken_at DESC, photos.filename
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {"total": int(total), "items": [dict(row) for row in rows]}


def list_locations(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    folder: str = "",
    taken_from: str = "",
    taken_to: str = "",
    face: int | None = None,
) -> list[dict[str, Any]]:
    sql_where, params = photo_filters(
        query=query, folder=folder, taken_from=taken_from, taken_to=taken_to, face=face
    )
    rows = conn.execute(
        f"""
        SELECT id, filename, taken_at, latitude, longitude
        FROM photos
        WHERE {sql_where}
        ORDER BY taken_at IS NULL, taken_at DESC, filename
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
