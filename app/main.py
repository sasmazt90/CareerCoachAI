from __future__ import annotations

import cgi
import json
import re
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .services import auto_answer_questions, create_cover_letter, match_job, tailor_cv
from .storage import (
    UPLOAD_DIR,
    add_application,
    add_cv,
    add_job,
    get_openai_api_key,
    get_profile,
    init_db,
    list_applications,
    list_cvs,
    list_jobs,
    set_openai_api_key,
    upsert_profile,
)


def html_layout(title: str, body: str) -> str:
    return f"""
    <html>
      <head>
        <meta charset='utf-8' />
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <title>{title}</title>
        <style>
          body {{ font-family: Inter, Arial, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }}
          .container {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
          .top {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }}
          a {{ color: #93c5fd; text-decoration: none; }}
          .nav a {{ margin-right: 14px; }}
          .card {{ background:#111827; border:1px solid #1f2937; border-radius:12px; padding:16px; margin-top:16px; }}
          input, textarea, select {{ width: 100%; padding:10px; border-radius:8px; border:1px solid #374151; background:#0b1220; color:#e2e8f0; }}
          button {{ background:#2563eb; color:#fff; border:none; border-radius:8px; padding:10px 16px; cursor:pointer; }}
          label {{ display:block; margin:10px 0 6px; color:#cbd5e1; }}
          table {{ width:100%; border-collapse:collapse; }}
          th,td {{ border-bottom:1px solid #243244; text-align:left; vertical-align:top; padding:8px; font-size:14px; }}
          .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; }}
          .pill {{ background:#1e293b; border-radius:999px; padding:4px 10px; font-size:12px; display:inline-block; }}
          pre {{ white-space: pre-wrap; margin: 0; font-size: 12px; color: #d1d5db; }}
        </style>
      </head>
      <body>
        <div class='container'>
          <div class='top'>
            <h2>{title}</h2>
            <div class='nav'>
              <a href='/'>Home</a>
              <a href='/profile-form'>Profile</a>
              <a href='/cvs/upload'>CV Upload</a>
              <a href='/jobs/new'>Jobs</a>
              <a href='/settings'>OpenAI</a>
              <a href='/dashboard'>Dashboard</a>
            </div>
          </div>
          {body}
        </div>
      </body>
    </html>
    """


class AppHandler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw)
        return {k: v[0] for k, v in parsed.items()}

    def _send(self, status: int, payload: dict | list | str, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if content_type.startswith("application/json"):
            self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))
        else:
            self.wfile.write(str(payload).encode("utf-8"))

    def _redirect(self, to: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", to)
        self.end_headers()

    def do_HEAD(self):  # noqa: N802
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/profile":
                upsert_profile(self._read_json())
                return self._send(HTTPStatus.OK, {"status": "ok"})
            if path == "/cvs":
                cv_id = add_cv(self._read_json())
                return self._send(HTTPStatus.OK, {"cv_id": cv_id})
            if path == "/jobs":
                job_id = add_job(self._read_json())
                return self._send(HTTPStatus.OK, {"job_id": job_id})
            if path == "/settings":
                form = self._read_form()
                set_openai_api_key(form.get("openai_api_key", ""))
                return self._redirect("/settings")
            if path == "/profile-form":
                form = self._read_form()
                upsert_profile(
                    {
                        "full_name": form.get("full_name", ""),
                        "email": form.get("email", ""),
                        "countries": [x.strip() for x in form.get("countries", "").split(",") if x.strip()],
                        "target_positions": [x.strip() for x in form.get("target_positions", "").split(",") if x.strip()],
                        "minimum_salary_usd": int(form.get("minimum_salary_usd", "0") or 0),
                        "career_history": form.get("career_history", ""),
                    }
                )
                return self._redirect("/dashboard")
            if path == "/jobs/new":
                form = self._read_form()
                add_job(
                    {
                        "company": form.get("company", ""),
                        "position": form.get("position", ""),
                        "country": form.get("country", ""),
                        "salary_usd": int(form.get("salary_usd", "0") or 0),
                        "description": form.get("description", ""),
                        "questions": [x.strip() for x in form.get("questions", "").split("\n") if x.strip()],
                        "seniority": form.get("seniority", "mid"),
                        "source_url": form.get("source_url", ""),
                    }
                )
                return self._redirect("/dashboard")
            if path == "/cvs/upload":
                fs = cgi.FieldStorage(  # noqa: UP009
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    },
                )
                title = fs.getvalue("title", "Uploaded CV")
                file_item = fs["cv_file"] if "cv_file" in fs else None
                if not file_item or not getattr(file_item, "file", None):
                    return self._send(HTTPStatus.BAD_REQUEST, "CV file is required", "text/plain; charset=utf-8")

                filename = Path(getattr(file_item, "filename", "cv.txt") or "cv.txt").name
                safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
                blob = file_item.file.read()
                saved_path = UPLOAD_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_name}"
                saved_path.write_bytes(blob)
                try:
                    text = blob.decode("utf-8")
                except UnicodeDecodeError:
                    text = blob.decode("latin-1", errors="ignore")
                add_cv(
                    {
                        "title": title,
                        "content": text,
                        "original_filename": filename,
                        "stored_path": str(saved_path),
                    }
                )
                return self._redirect("/dashboard")
            if path == "/auto-apply":
                profile = get_profile()
                if not profile:
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": "profile missing"})
                cvs = list_cvs()
                jobs = list_jobs()
                if not cvs:
                    return self._send(HTTPStatus.BAD_REQUEST, {"error": "cv missing"})
                cv = cvs[0]
                created = 0
                api_key = get_openai_api_key()
                for job in jobs:
                    matched = match_job(profile, job)
                    if not matched.matched:
                        continue
                    tailored = tailor_cv(cv["content"], job, profile, api_key=api_key)
                    letter = create_cover_letter(job, profile, api_key=api_key)
                    answers = auto_answer_questions(job["questions"], profile, job, api_key=api_key)
                    notes = "Auto-generated with OpenAI" if api_key else "Auto-generated with fallback templates"
                    add_application(job["id"], cv["id"], tailored, letter, answers, status="ready_to_submit", notes=notes)
                    created += 1
                if self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._send(HTTPStatus.OK, {"applications_created": created})
                return self._redirect("/dashboard")
        except Exception as exc:  # pragma: no cover
            return self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            apps = list_applications()
            jobs = list_jobs()
            cvs = list_cvs()
            body = f"""
                <div class='grid'>
                  <div class='card'><div class='pill'>Applications</div><h3>{len(apps)}</h3></div>
                  <div class='card'><div class='pill'>Jobs</div><h3>{len(jobs)}</h3></div>
                  <div class='card'><div class='pill'>CVs</div><h3>{len(cvs)}</h3></div>
                </div>
                <div class='card'>
                  <p>AIApply benzeri akış: profil, OpenAI key, CV upload, job ekleme, auto-apply, dashboard takip.</p>
                  <form method='post' action='/auto-apply'><button type='submit'>Run Auto Apply</button></form>
                </div>
            """
            return self._send(HTTPStatus.OK, html_layout("CareerCoachAI Platform", body), "text/html; charset=utf-8")
        if path == "/settings":
            key = get_openai_api_key()
            masked = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else "(not set)"
            body = f"""
                <div class='card'>
                  <h3>OpenAI API Secret</h3>
                  <p>Current key: <strong>{masked}</strong></p>
                  <form method='post' action='/settings'>
                    <label>OPENAI_API_KEY</label>
                    <input type='password' name='openai_api_key' placeholder='sk-...' required />
                    <br/><br/>
                    <button type='submit'>Save Secret</button>
                  </form>
                </div>
            """
            return self._send(HTTPStatus.OK, html_layout("Settings", body), "text/html; charset=utf-8")
        if path == "/profile-form":
            profile = get_profile() or {
                "full_name": "",
                "email": "",
                "countries": [],
                "target_positions": [],
                "minimum_salary_usd": 0,
                "career_history": "",
            }
            body = f"""
                <div class='card'>
                  <form method='post' action='/profile-form'>
                    <label>Full Name</label><input name='full_name' value='{profile['full_name']}' required />
                    <label>Email</label><input name='email' value='{profile['email']}' required />
                    <label>Target Countries (comma separated)</label><input name='countries' value='{", ".join(profile['countries'])}' />
                    <label>Target Positions (comma separated)</label><input name='target_positions' value='{", ".join(profile['target_positions'])}' />
                    <label>Minimum Salary USD</label><input type='number' name='minimum_salary_usd' value='{profile['minimum_salary_usd']}' />
                    <label>Career History</label><textarea name='career_history' rows='6'>{profile['career_history']}</textarea>
                    <br/><br/><button type='submit'>Save Profile</button>
                  </form>
                </div>
            """
            return self._send(HTTPStatus.OK, html_layout("Candidate Profile", body), "text/html; charset=utf-8")
        if path == "/cvs/upload":
            body = """
                <div class='card'>
                  <h3>Upload CV</h3>
                  <form method='post' action='/cvs/upload' enctype='multipart/form-data'>
                    <label>CV Title</label><input name='title' value='Primary CV' />
                    <label>CV File (.txt recommended)</label><input type='file' name='cv_file' required />
                    <br/><br/><button type='submit'>Upload CV</button>
                  </form>
                </div>
            """
            return self._send(HTTPStatus.OK, html_layout("CV Upload", body), "text/html; charset=utf-8")
        if path == "/jobs/new":
            body = """
                <div class='card'>
                  <h3>Add Job Posting</h3>
                  <form method='post' action='/jobs/new'>
                    <label>Company</label><input name='company' required />
                    <label>Position</label><input name='position' required />
                    <label>Country</label><input name='country' required />
                    <label>Salary (USD)</label><input type='number' name='salary_usd' value='100000' />
                    <label>Description</label><textarea name='description' rows='5'></textarea>
                    <label>Application Questions (one per line)</label><textarea name='questions' rows='4'></textarea>
                    <label>Seniority</label><select name='seniority'><option>junior</option><option selected>mid</option><option>senior</option><option>lead</option></select>
                    <label>Source URL</label><input name='source_url' placeholder='https://...' />
                    <br/><br/><button type='submit'>Save Job</button>
                  </form>
                </div>
            """
            return self._send(HTTPStatus.OK, html_layout("Job Intake", body), "text/html; charset=utf-8")

        if path == "/cvs":
            return self._send(HTTPStatus.OK, list_cvs())
        if path == "/jobs":
            return self._send(HTTPStatus.OK, list_jobs())
        if path == "/applications":
            return self._send(HTTPStatus.OK, list_applications())
        if path == "/dashboard":
            apps = list_applications()
            rows = "".join(
                f"<tr><td>{a['company']}</td><td>{a['position']}</td><td>{a['country']}</td><td>{a['salary_usd']}</td>"
                f"<td>{a['cv_title']}</td><td>{a['status']}</td><td>{a['notes']}</td><td><pre>{a['cover_letter']}</pre></td>"
                f"<td><pre>{json.dumps(a['answers'], ensure_ascii=False, indent=2)}</pre></td><td>{a['created_at']}</td></tr>"
                for a in apps
            )
            body = f"""
                <div class='card'>
                  <form method='post' action='/auto-apply'><button type='submit'>Generate Applications</button></form>
                </div>
                <div class='card'>
                  <table>
                    <thead><tr><th>Company</th><th>Position</th><th>Country</th><th>Salary</th><th>CV</th><th>Status</th><th>Notes</th><th>Cover Letter</th><th>Answers</th><th>Date</th></tr></thead>
                    <tbody>{rows or '<tr><td colspan="10">No applications yet.</td></tr>'}</tbody>
                  </table>
                </div>
            """
            return self._send(HTTPStatus.OK, html_layout("Application Dashboard", body), "text/html; charset=utf-8")
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), AppHandler)
    server.serve_forever()


if __name__ == "__main__":
    run()
