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

CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts USING fts5(
    filename,
    folder,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
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


def delete_photo(conn: sqlite3.Connection, photo_id: int) -> None:
    conn.execute("DELETE FROM photos_fts WHERE rowid = ?", (photo_id,))
    conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))


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


def search_photos(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    folder: str = "",
    taken_from: str = "",
    taken_to: str = "",
    limit: int = 80,
    offset: int = 0,
) -> dict[str, Any]:
    where = ["1 = 1"]
    params: list[Any] = []
    match = fts_query(query)
    join = ""
    if match:
        join = "JOIN photos_fts ON photos_fts.rowid = photos.id"
        where.append("photos_fts MATCH ?")
        params.append(match)
    if folder:
        where.append("photos.folder = ?")
        params.append(folder)
    if taken_from:
        where.append("photos.taken_at >= ?")
        params.append(taken_from)
    if taken_to:
        where.append("photos.taken_at < ?")
        params.append(taken_to + "T99")
    sql_where = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM photos {join} WHERE {sql_where}",
        params,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""
        SELECT photos.* FROM photos {join}
        WHERE {sql_where}
        ORDER BY photos.taken_at IS NULL, photos.taken_at DESC, photos.filename
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {"total": int(total), "items": [dict(row) for row in rows]}
