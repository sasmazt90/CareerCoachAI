from __future__ import annotations

import cgi
import html
import json
import re
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .file_parsers import extract_text
from .services import auto_answer_questions, build_cv_knowledge, create_cover_letter, interview_generate_question, interview_score, match_job, tailor_cv
from .storage import (
    CURRENCY_RATES_TO_USD,
    UPLOAD_DIR,
    add_application,
    add_cv,
    add_interview_message,
    add_job,
    create_interview,
    finalize_interview,
    get_interview,
    get_job,
    get_openai_api_key,
    get_profile,
    init_db,
    list_applications,
    list_cvs,
    list_interview_messages,
    list_jobs,
    set_openai_api_key,
    to_usd,
    upsert_profile,
)

COUNTRIES = ["Germany", "Netherlands", "United Kingdom", "United Arab Emirates", "Turkey", "United States", "Canada", "Ireland", "Sweden", "Switzerland"]


def esc(v: object) -> str:
    return html.escape(str(v))


def page(title: str, body: str) -> str:
    return f"""<html><head><meta charset='utf-8'/><title>{esc(title)}</title><style>
body{{font-family:Arial;background:#0f172a;color:#e2e8f0;margin:0}}.c{{max-width:1180px;margin:0 auto;padding:24px}}a{{color:#93c5fd}}
.card{{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:16px;margin-top:16px}}input,textarea,select{{width:100%;padding:10px;background:#0b1220;color:#e2e8f0;border:1px solid #374151;border-radius:8px}}
button{{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:10px 16px}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #243244;padding:8px;vertical-align:top}}pre{{white-space:pre-wrap;max-height:220px;overflow:auto}}
</style></head><body><div class='c'><div><a href='/'>Home</a> | <a href='/profile-form'>Profile</a> | <a href='/cvs/upload'>CV Upload</a> | <a href='/jobs/new'>Jobs</a> | <a href='/settings'>OpenAI</a> | <a href='/dashboard'>Dashboard</a> | <a href='/cover-letters'>Cover Letters</a> | <a href='/interview'>Interview</a></div><h2>{esc(title)}</h2>{body}</div></body></html>"""


class AppHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict | list | str, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if content_type.startswith("application/json"):
            self.wfile.write(json.dumps(payload, default=str).encode())
        else:
            self.wfile.write(str(payload).encode())

    def _redirect(self, to: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", to)
        self.end_headers()

    def _form(self) -> dict[str, list[str]]:
        ln = int(self.headers.get("Content-Length", "0"))
        return parse_qs(self.rfile.read(ln).decode())

    def _json(self) -> dict:
        ln = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(ln).decode()
        return json.loads(raw) if raw else {}

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def do_POST(self):  # noqa: N802
        p = urlparse(self.path).path
        try:
            if p == "/settings":
                f = self._form(); set_openai_api_key((f.get("openai_api_key") or [""])[0]); return self._redirect("/settings")
            if p == "/profile-form":
                f = self._form()
                countries = f.get("countries") or [x.strip() for x in (f.get("countries_csv") or [""])[0].split(",") if x.strip()]
                curr = ((f.get("preferred_currency") or ["USD"])[0]).upper()
                upsert_profile({
                    "full_name": (f.get("full_name") or [""])[0],
                    "email": (f.get("email") or [""])[0],
                    "countries": countries,
                    "target_positions": [x.strip() for x in (f.get("target_positions") or [""])[0].split(",") if x.strip()],
                    "minimum_salary_usd": to_usd(float((f.get("minimum_salary_amount") or ["0"])[0] or 0), curr),
                    "preferred_currency": curr,
                    "career_history": (f.get("career_history") or [""])[0],
                })
                return self._redirect("/dashboard")
            if p == "/jobs/new":
                f = self._form(); amount = float((f.get("salary_amount") or ["0"])[0] or 0); curr = ((f.get("salary_currency") or ["USD"])[0]).upper()
                add_job({"company": (f.get("company") or [""])[0], "position": (f.get("position") or [""])[0], "country": (f.get("country") or [""])[0], "salary_amount": amount, "salary_currency": curr, "salary_usd": to_usd(amount, curr), "description": (f.get("description") or [""])[0], "questions": [x.strip() for x in (f.get("questions") or [""])[0].split("\n") if x.strip()], "seniority": (f.get("seniority") or ["mid"])[0], "source_url": (f.get("source_url") or [""])[0]})
                return self._redirect("/dashboard")
            if p == "/cvs/upload":
                fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
                title = fs.getvalue("title", "CV Collection")
                files = fs["cv_files"] if "cv_files" in fs else []
                if not isinstance(files, list): files = [files]
                saved = 0
                for i, fi in enumerate(files, start=1):
                    if not fi or not getattr(fi, "file", None): continue
                    name = Path(getattr(fi, "filename", "cv.txt") or "cv.txt").name
                    blob = fi.file.read()
                    if not blob: continue
                    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
                    sp = UPLOAD_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe}"
                    sp.write_bytes(blob)
                    add_cv({"title": f"{title} #{i}", "content": extract_text(name, blob), "original_filename": name, "stored_path": str(sp)})
                    saved += 1
                if not saved: return self._send(400, {"error": "No CV uploaded"})
                return self._redirect("/dashboard")
            if p == "/auto-apply":
                profile, cvs, jobs = get_profile(), list_cvs(), list_jobs()
                if not profile: return self._send(400, {"error": "profile missing"})
                if not cvs: return self._send(400, {"error": "cv missing"})
                key = get_openai_api_key(); corpus = build_cv_knowledge(cvs, profile, key); created = 0
                for job in jobs:
                    if not match_job(profile, job).matched: continue
                    cv = tailor_cv(cvs[0]["content"], job, profile, corpus, key)
                    cl = create_cover_letter(job, profile, corpus, key)
                    ans = auto_answer_questions(job["questions"], profile, job, corpus, key)
                    add_application(job["id"], cvs[0]["id"], cv, cl, ans, status="ready_to_submit", notes="ATS+facts only")
                    created += 1
                if self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._send(200, {"applications_created": created})
                return self._redirect("/dashboard")
            if p == "/interview/start":
                f = self._form(); iid = create_interview(int((f.get("job_id") or ["0"])[0]), int((f.get("stage") or ["1"])[0])); return self._redirect(f"/interview/session?id={iid}")
            if p == "/interview/answer":
                f = self._form(); iid = int((f.get("interview_id") or ["0"])[0]); answer = (f.get("answer") or [""])[0]
                iv = get_interview(iid); job = get_job(iv["job_id"]) if iv else None
                if not iv or not job: return self._send(404, {"error": "interview not found"})
                add_interview_message(iid, "candidate", answer)
                q = interview_generate_question(job, iv["stage"], list_interview_messages(iid), get_profile() or {}, build_cv_knowledge(list_cvs(), get_profile() or {}, get_openai_api_key()), get_openai_api_key())
                add_interview_message(iid, "interviewer", q)
                return self._redirect(f"/interview/session?id={iid}")
            if p == "/interview/finish":
                f = self._form(); iid = int((f.get("interview_id") or ["0"])[0]); iv = get_interview(iid)
                if not iv: return self._send(404, {"error": "interview not found"})
                job = get_job(iv["job_id"]) or {}
                scoring = interview_score(job, iv["stage"], list_interview_messages(iid), get_profile() or {}, build_cv_knowledge(list_cvs(), get_profile() or {}, get_openai_api_key()), get_openai_api_key())
                overall = float(scoring.get("overall", 0)); passed = bool(scoring.get("passed", overall >= 75))
                finalize_interview(iid, "passed" if passed else "failed", overall, scoring, str(scoring.get("recommendation", "")))
                return self._redirect(f"/interview/session?id={iid}")
            if p == "/interview/retry":
                f = self._form(); prev = get_interview(int((f.get("interview_id") or ["0"])[0]))
                if not prev: return self._send(404, {"error": "interview not found"})
                iid = create_interview(prev["job_id"], prev["stage"]); return self._redirect(f"/interview/session?id={iid}")

            if p == "/profile": return self._send(200, {"status": "ok"}) if not upsert_profile(self._json()) else self._send(200, {"status": "ok"})
            if p == "/cvs": return self._send(200, {"cv_id": add_cv(self._json())})
            if p == "/jobs": return self._send(200, {"job_id": add_job(self._json())})
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def do_GET(self):  # noqa: N802
        p = urlparse(self.path).path; q = parse_qs(urlparse(self.path).query)
        try:
            if p == "/":
                apps, jobs, cvs = list_applications(), list_jobs(), list_cvs()
                body = f"<div class='card'>Applications: {len(apps)} | Jobs: {len(jobs)} | CV Versions: {len(cvs)}</div><div class='card'><form method='post' action='/auto-apply'><button type='submit'>Run Auto Apply</button></form></div>"
                return self._send(200, page("CareerCoachAI Platform", body), "text/html; charset=utf-8")
            if p == "/settings":
                key = get_openai_api_key(); masked = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else "(not set)"
                return self._send(200, page("Settings", f"<div class='card'><p>Current key: <strong>{esc(masked)}</strong></p><form method='post' action='/settings'><input type='password' name='openai_api_key' required/><br/><br/><button>Save Secret</button></form></div>"), "text/html; charset=utf-8")
            if p == "/profile-form":
                pr = get_profile() or {"full_name":"","email":"","countries":[],"target_positions":[],"minimum_salary_usd":0,"preferred_currency":"USD","career_history":""}
                co = "".join(f"<option value='{esc(c)}' {'selected' if c in pr['countries'] else ''}>{esc(c)}</option>" for c in COUNTRIES)
                cu = "".join(f"<option value='{esc(c)}' {'selected' if c==pr['preferred_currency'] else ''}>{esc(c)}</option>" for c in CURRENCY_RATES_TO_USD)
                body = f"<div class='card'><form method='post' action='/profile-form'><label>Full Name</label><input name='full_name' value='{esc(pr['full_name'])}' required/><label>Email</label><input name='email' value='{esc(pr['email'])}' required/><label>Target Countries</label><select name='countries' multiple size='8'>{co}</select><label>Target Positions (comma separated)</label><input name='target_positions' value='{esc(', '.join(pr['target_positions']))}'/><label>Minimum Salary</label><input type='number' name='minimum_salary_amount' value='{esc(pr['minimum_salary_usd'])}'/><label>Currency</label><select name='preferred_currency'>{cu}</select><label>Career History</label><textarea name='career_history' rows='6'>{esc(pr['career_history'])}</textarea><br/><br/><button>Save Profile</button></form></div>"
                return self._send(200, page("Candidate Profile", body), "text/html; charset=utf-8")
            if p == "/cvs/upload":
                rows = "".join(f"<tr><td>{esc(c['title'])}</td><td>{esc(c.get('original_filename',''))}</td><td>{esc((c.get('content') or '')[:120])}...</td></tr>" for c in list_cvs())
                empty_cv = "<tr><td colspan='3'>No CV uploaded.</td></tr>"
                body = f"<div class='card'><form method='post' action='/cvs/upload' enctype='multipart/form-data'><label>CV Group Title</label><input name='title' value='My CV Collection'/><label>CV Files (.txt/.pdf/.docx/.doc)</label><input type='file' name='cv_files' multiple required/><br/><br/><button>Upload</button></form></div><div class='card'><table><thead><tr><th>Title</th><th>File</th><th>Preview</th></tr></thead><tbody>{rows or empty_cv}</tbody></table></div>"
                return self._send(200, page("CV Upload", body), "text/html; charset=utf-8")
            if p == "/jobs/new":
                co = "".join(f"<option>{esc(c)}</option>" for c in COUNTRIES); cu = "".join(f"<option>{esc(c)}</option>" for c in CURRENCY_RATES_TO_USD)
                body = f"<div class='card'><form method='post' action='/jobs/new'><label>Company</label><input name='company' required/><label>Position</label><input name='position' required/><label>Country</label><select name='country'>{co}</select><label>Salary Amount</label><input type='number' name='salary_amount' value='100000'/><label>Salary Currency</label><select name='salary_currency'>{cu}</select><label>Description</label><textarea name='description' rows='5'></textarea><label>Questions (one per line)</label><textarea name='questions' rows='4'></textarea><label>Seniority</label><select name='seniority'><option>junior</option><option selected>mid</option><option>senior</option><option>lead</option></select><label>Source URL</label><input name='source_url'/><br/><br/><button>Save Job</button></form></div>"
                return self._send(200, page("Job Intake", body), "text/html; charset=utf-8")
            if p == "/dashboard":
                rows = "".join(f"<tr><td>{esc(a['company'])}</td><td>{esc(a['position'])}</td><td>{esc(a['country'])}</td><td>{esc(a['salary_amount'])} {esc(a['salary_currency'])}</td><td>{esc(a['cv_title'])}</td><td>{esc(a['status'])}</td><td>{esc(a['notes'])}</td><td><a href='/cover-letters'>Open</a></td><td><pre>{esc(json.dumps(a['answers'], ensure_ascii=False, indent=2))}</pre></td><td>{esc(a['created_at'])}</td></tr>" for a in list_applications())
                empty_app = "<tr><td colspan='10'>No applications yet.</td></tr>"
                body = f"<div class='card'><form method='post' action='/auto-apply'><button>Generate Applications</button></form></div><div class='card'><table><thead><tr><th>Company</th><th>Position</th><th>Country</th><th>Salary</th><th>CV</th><th>Status</th><th>Notes</th><th>Cover Letter</th><th>Answers</th><th>Date</th></tr></thead><tbody>{rows or empty_app}</tbody></table></div>"
                return self._send(200, page("Application Dashboard", body), "text/html; charset=utf-8")
            if p == "/cover-letters":
                rows = "".join(f"<tr><td>{esc(a['company'])}</td><td>{esc(a['position'])}</td><td><pre>{esc(a['cover_letter'])}</pre></td></tr>" for a in list_applications())
                empty_cover = "<tr><td colspan='3'>No cover letters yet.</td></tr>"
                body = f"<div class='card'><table><thead><tr><th>Company</th><th>Role</th><th>Cover Letter</th></tr></thead><tbody>{rows or empty_cover}</tbody></table></div>"
                return self._send(200, page("Cover Letters", body), "text/html; charset=utf-8")
            if p == "/interview":
                opts = "".join(f"<option value='{j['id']}'>{esc(j['company'])} - {esc(j['position'])}</option>" for j in list_jobs())
                body = f"<div class='card'><p>Stage 1 HR -> Stage 2 Unit Manager</p><form method='post' action='/interview/start'><label>Job</label><select name='job_id'>{opts}</select><label>Stage</label><select name='stage'><option value='1'>1 - HR Manager</option><option value='2'>2 - Unit Manager</option></select><br/><br/><button>Start Interview</button></form></div>"
                return self._send(200, page("Interview", body), "text/html; charset=utf-8")
            if p == "/interview/session":
                iid = int((q.get("id") or ["0"])[0]); iv = get_interview(iid)
                if not iv: return self._send(404, page("Interview", "<div class='card'>Interview not found.</div>"), "text/html; charset=utf-8")
                msgs = list_interview_messages(iid)
                if not msgs:
                    job = get_job(iv["job_id"]) or {}
                    q1 = interview_generate_question(job, iv["stage"], [], get_profile() or {}, build_cv_knowledge(list_cvs(), get_profile() or {}, get_openai_api_key()), get_openai_api_key())
                    add_interview_message(iid, "interviewer", q1)
                    msgs = list_interview_messages(iid)
                rows = "".join(f"<tr><td>{esc(m['role'])}</td><td>{esc(m['content'])}</td></tr>" for m in msgs)
                score = ""
                if iv["status"] in {"passed", "failed"}:
                    s = iv["score_breakdown"]
                    score = f"<div class='card'><h3>Score {esc(iv['score'])}</h3><pre>{esc(json.dumps(s, ensure_ascii=False, indent=2))}</pre><p>{esc(iv['recommendation'])}</p>"
                    if iv["status"] == "passed" and iv["stage"] == 2: score += "<h3>YOU GOT THE JOB 🎉</h3>"
                    elif iv["status"] == "passed": score += f"<form method='post' action='/interview/start'><input type='hidden' name='job_id' value='{esc(iv['job_id'])}'/><input type='hidden' name='stage' value='2'/><button>Go Stage 2</button></form>"
                    else: score += f"<form method='post' action='/interview/retry'><input type='hidden' name='interview_id' value='{esc(iid)}'/><button>Retry</button></form>"
                    score += "</div>"
                body = f"<div class='card'><table><thead><tr><th>Role</th><th>Message</th></tr></thead><tbody>{rows}</tbody></table></div><div class='card'><form method='post' action='/interview/answer'><input type='hidden' name='interview_id' value='{esc(iid)}'/><textarea name='answer' rows='5' required></textarea><br/><br/><button>Send Answer</button></form><br/><form method='post' action='/interview/finish'><input type='hidden' name='interview_id' value='{esc(iid)}'/><button>Finish & Score</button></form></div>{score}"
                return self._send(200, page("Interview Session", body), "text/html; charset=utf-8")
            if p == "/cvs": return self._send(200, list_cvs())
            if p == "/jobs": return self._send(200, list_jobs())
            if p == "/applications": return self._send(200, list_applications())
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    init_db()
    ThreadingHTTPServer((host, port), AppHandler).serve_forever()


if __name__ == "__main__":
    run()
