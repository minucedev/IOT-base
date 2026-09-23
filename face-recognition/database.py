import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# Múi giờ Việt Nam UTC+7
_VN_TZ = timezone(timedelta(hours=7))


def _now_vn() -> str:
    """Trả về thời gian hiện tại theo giờ VN, định dạng 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(_VN_TZ).strftime("%Y-%m-%d %H:%M:%S")


class FaceDatabase:
    def __init__(self, directory: str = "data") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "faces.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS persons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                dimension INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS recognition_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER,
                person_name TEXT NOT NULL,
                similarity REAL NOT NULL,
                detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_logs_detected_at ON recognition_logs(detected_at DESC);
            CREATE TABLE IF NOT EXISTS registration_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                photo BLOB NOT NULL,
                registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reg_photos_person ON registration_photos(person_id);
            """)

    @staticmethod
    def _blob_to_embedding(blob: bytes, dimension: int) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32, count=dimension).copy()

    def add_person_embeddings(self, name: str, embeddings: list[np.ndarray]) -> int:
        clean = name.strip()
        if not clean or not embeddings:
            raise ValueError("Tên và embedding không được rỗng")
        now = _now_vn()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT id FROM persons WHERE name = ?", (clean,)).fetchone()
            if row:
                person_id = int(row["id"])
                conn.execute("DELETE FROM face_embeddings WHERE person_id = ?", (person_id,))
            else:
                person_id = int(conn.execute(
                    "INSERT INTO persons(name, created_at) VALUES (?, ?)", (clean, now)
                ).lastrowid)
            for emb in embeddings:
                vector = np.asarray(emb, dtype=np.float32).reshape(-1)
                conn.execute(
                    "INSERT INTO face_embeddings(person_id, embedding, dimension, created_at) VALUES (?, ?, ?, ?)",
                    (person_id, vector.tobytes(), int(vector.size), now),
                )
            return person_id

    def get_gallery(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT p.id AS person_id, p.name, e.embedding, e.dimension
                FROM persons p JOIN face_embeddings e ON e.person_id = p.id
                ORDER BY p.id, e.id
            """).fetchall()
        result = []
        for row in rows:
            result.append({
                "person_id": int(row["person_id"]),
                "name": str(row["name"]),
                "embedding": self._blob_to_embedding(row["embedding"], int(row["dimension"])),
            })
        return result

    def list_persons(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT p.id, p.name, p.created_at, COUNT(e.id) AS embedding_count
                FROM persons p LEFT JOIN face_embeddings e ON e.person_id = p.id
                GROUP BY p.id ORDER BY p.id
            """).fetchall()
            return [dict(row) for row in rows]

    def delete_person(self, person_id: int) -> tuple[bool, str]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT name FROM persons WHERE id = ?", (person_id,)).fetchone()
            if not row:
                return False, f"Không tìm thấy người có id={person_id}"
            name = str(row["name"])
            conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
        return True, f"Đã xóa {name}"

    def log_recognition(self, person_id: int | None, name: str, similarity: float) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO recognition_logs(person_id, person_name, similarity, detected_at) VALUES (?, ?, ?, ?)",
                (person_id, name, float(similarity), _now_vn()),
            )

    def recognition_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, person_id, person_name, similarity, detected_at FROM recognition_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def clear_logs(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM recognition_logs")

    # ------------------------------------------------------------------ #
    # Registration photos                                                  #
    # ------------------------------------------------------------------ #

    def save_registration_photo(self, person_id: int, name: str, jpeg: bytes) -> None:
        """Lưu ảnh JPEG đại diện tại thời điểm đăng ký."""
        now = _now_vn()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM registration_photos WHERE person_id = ? ORDER BY id ASC",
                (person_id,),
            ).fetchall()
            if len(rows) >= 3:
                for row in rows[: len(rows) - 2]:
                    conn.execute("DELETE FROM registration_photos WHERE id = ?", (row["id"],))
            conn.execute(
                "INSERT INTO registration_photos(person_id, person_name, photo, registered_at) VALUES (?, ?, ?, ?)",
                (person_id, name, jpeg, now),
            )

    def list_registration_photos(self) -> list[dict[str, Any]]:
        """Danh sách ảnh đăng ký (không kèm blob) để hiển thị UI."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, person_id, person_name, registered_at,
                       length(photo) AS photo_size
                FROM registration_photos
                ORDER BY id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_registration_photo(self, photo_id: int) -> bytes | None:
        """Lấy blob JPEG theo id. Trả về None nếu không tồn tại."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT photo FROM registration_photos WHERE id = ?", (photo_id,)
            ).fetchone()
            return bytes(row["photo"]) if row else None

    def delete_registration_photos_by_person(self, person_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM registration_photos WHERE person_id = ?", (person_id,)
            )
