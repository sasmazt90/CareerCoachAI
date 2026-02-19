from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("careercoachai.db")
UPLOAD_DIR = Path("uploads")

CURRENCY_RATES_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "TRY": 0.031,
    "AED": 0.272,
}


def to_usd(amount: float, currency: str) -> int:
    rate = CURRENCY_RATES_TO_USD.get(currency.upper(), 1.0)
    return int(round(amount * rate))


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    UPLOAD_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                countries TEXT NOT NULL,
                target_positions TEXT NOT NULL,
                minimum_salary_usd INTEGER NOT NULL,
                preferred_currency TEXT NOT NULL DEFAULT 'USD',
                career_history TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                openai_api_key TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS cvs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                original_filename TEXT,
                stored_path TEXT
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                position TEXT NOT NULL,
                country TEXT NOT NULL,
                salary_amount REAL NOT NULL DEFAULT 0,
                salary_currency TEXT NOT NULL DEFAULT 'USD',
                salary_usd INTEGER NOT NULL DEFAULT 0,
                description TEXT NOT NULL,
                questions TEXT NOT NULL,
                seniority TEXT NOT NULL,
                source_url TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                cv_id INTEGER NOT NULL,
                tailored_cv TEXT NOT NULL,
                cover_letter TEXT NOT NULL,
                answers TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id),
                FOREIGN KEY(cv_id) REFERENCES cvs(id)
            );

            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                stage INTEGER NOT NULL,
                status TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                score_breakdown TEXT NOT NULL DEFAULT '{}',
                recommendation TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS interview_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(interview_id) REFERENCES interviews(id)
            );
            """
        )
        _add_column_if_missing(conn, "profile", "preferred_currency", "preferred_currency TEXT NOT NULL DEFAULT 'USD'")
        _add_column_if_missing(conn, "jobs", "salary_amount", "salary_amount REAL NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "jobs", "salary_currency", "salary_currency TEXT NOT NULL DEFAULT 'USD'")
        _add_column_if_missing(conn, "jobs", "salary_usd", "salary_usd INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "jobs", "source_url", "source_url TEXT")
        _add_column_if_missing(conn, "applications", "status", "status TEXT NOT NULL DEFAULT 'generated'")
        _add_column_if_missing(conn, "applications", "notes", "notes TEXT NOT NULL DEFAULT ''")


def ensure_setting_row() -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO settings (id, openai_api_key) VALUES (1, '')")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    if UPLOAD_DIR.exists():
        for f in UPLOAD_DIR.iterdir():
            if f.is_file():
                f.unlink()
    init_db()
    ensure_setting_row()


def set_openai_api_key(api_key: str) -> None:
    ensure_setting_row()
    with get_conn() as conn:
        conn.execute("UPDATE settings SET openai_api_key = ? WHERE id = 1", (api_key.strip(),))


def get_openai_api_key() -> str:
    ensure_setting_row()
    with get_conn() as conn:
        row = conn.execute("SELECT openai_api_key FROM settings WHERE id = 1").fetchone()
        return row["openai_api_key"] if row else ""


def upsert_profile(payload: dict) -> None:
    preferred_currency = payload.get("preferred_currency", "USD")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO profile (id, full_name, email, countries, target_positions, minimum_salary_usd, preferred_currency, career_history)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                full_name = excluded.full_name,
                email = excluded.email,
                countries = excluded.countries,
                target_positions = excluded.target_positions,
                minimum_salary_usd = excluded.minimum_salary_usd,
                preferred_currency = excluded.preferred_currency,
                career_history = excluded.career_history
            """,
            (
                payload["full_name"],
                payload["email"],
                json.dumps(payload["countries"]),
                json.dumps(payload["target_positions"]),
                payload["minimum_salary_usd"],
                preferred_currency,
                payload["career_history"],
            ),
        )


def get_profile() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "countries": json.loads(row["countries"]),
            "target_positions": json.loads(row["target_positions"]),
            "minimum_salary_usd": row["minimum_salary_usd"],
            "preferred_currency": row["preferred_currency"],
            "career_history": row["career_history"],
        }


def add_cv(payload: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cvs (title, content, original_filename, stored_path) VALUES (?, ?, ?, ?)",
            (payload["title"], payload["content"], payload.get("original_filename"), payload.get("stored_path")),
        )
        return int(cur.lastrowid)


def list_cvs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cvs ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


def add_job(payload: dict) -> int:
    amount = float(payload.get("salary_amount", payload.get("salary_usd", 0)))
    currency = payload.get("salary_currency", "USD").upper()
    salary_usd = int(payload.get("salary_usd", to_usd(amount, currency)))

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (company, position, country, salary_amount, salary_currency, salary_usd, description, questions, seniority, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload["company"],
                payload["position"],
                payload["country"],
                amount,
                currency,
                salary_usd,
                payload["description"],
                json.dumps(payload.get("questions", [])),
                payload.get("seniority", "mid"),
                payload.get("source_url", ""),
            ),
        )
        return int(cur.lastrowid)


def get_job(job_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["questions"] = json.loads(item["questions"])
        return item


def list_jobs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["questions"] = json.loads(item["questions"])
            output.append(item)
        return output


def add_application(job_id: int, cv_id: int, tailored_cv: str, cover_letter: str, answers: dict[str, str], status: str = "generated", notes: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO applications (job_id, cv_id, tailored_cv, cover_letter, answers, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, cv_id, tailored_cv, cover_letter, json.dumps(answers), status, notes, datetime.now(timezone.utc).isoformat()),
        )
        return int(cur.lastrowid)


def list_applications() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.id, j.company, j.position, j.country, j.salary_amount, j.salary_currency, j.salary_usd,
                   c.title as cv_title, a.tailored_cv, a.cover_letter, a.answers, a.status, a.notes, a.created_at
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            JOIN cvs c ON c.id = a.cv_id
            ORDER BY a.id DESC
            """
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["answers"] = json.loads(item["answers"])
            item["created_at"] = datetime.fromisoformat(item["created_at"])
            result.append(item)
        return result


def create_interview(job_id: int, stage: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO interviews (job_id, stage, status, score, score_breakdown, recommendation, created_at, updated_at) VALUES (?, ?, 'in_progress', 0, '{}', '', ?, ?)",
            (job_id, stage, now, now),
        )
        return int(cur.lastrowid)


def get_interview(interview_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["score_breakdown"] = json.loads(item["score_breakdown"] or "{}")
        return item


def add_interview_message(interview_id: int, role: str, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO interview_messages (interview_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (interview_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        return int(cur.lastrowid)


def list_interview_messages(interview_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM interview_messages WHERE interview_id = ? ORDER BY id", (interview_id,)).fetchall()
        return [dict(r) for r in rows]


def finalize_interview(interview_id: int, status: str, score: float, breakdown: dict, recommendation: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE interviews SET status=?, score=?, score_breakdown=?, recommendation=?, updated_at=? WHERE id=?",
            (status, score, json.dumps(breakdown), recommendation, datetime.now(timezone.utc).isoformat(), interview_id),
        )
