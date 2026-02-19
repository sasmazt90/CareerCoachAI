import sqlite3
from pathlib import Path

from app.storage import DB_PATH, add_cv, init_db


def test_init_db_adds_missing_cvs_columns_for_legacy_db():
    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE cvs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL)")

    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(cvs)").fetchall()}
    assert "original_filename" in cols
    assert "stored_path" in cols

    cv_id = add_cv({"title": "Legacy CV", "content": "data", "original_filename": "cv.txt", "stored_path": "uploads/x"})
    assert isinstance(cv_id, int)

    if DB_PATH.exists():
        DB_PATH.unlink()
    uploads = Path("uploads")
    if uploads.exists():
        for f in uploads.iterdir():
            if f.is_file():
                f.unlink()
