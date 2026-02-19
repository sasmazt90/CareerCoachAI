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


def test_init_db_adds_missing_jobs_city_column_for_legacy_db():
    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, position TEXT NOT NULL, country TEXT NOT NULL, salary_amount REAL NOT NULL DEFAULT 0, salary_currency TEXT NOT NULL DEFAULT 'USD', salary_usd INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL, questions TEXT NOT NULL, seniority TEXT NOT NULL, source_url TEXT)"
        )

    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "city" in cols

    if DB_PATH.exists():
        DB_PATH.unlink()
