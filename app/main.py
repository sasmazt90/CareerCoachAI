from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .services import auto_answer_questions, create_cover_letter, match_job, tailor_cv
from .storage import (
    add_application,
    add_cv,
    add_job,
    get_profile,
    init_db,
    list_applications,
    list_cvs,
    list_jobs,
    upsert_profile,
)


class AppHandler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _send(self, status: int, payload: dict | list | str, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if content_type == "application/json":
            self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))
        else:
            self.wfile.write(str(payload).encode("utf-8"))

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
                for job in jobs:
                    matched = match_job(profile, job)
                    if not matched.matched:
                        continue
                    tailored = tailor_cv(cv["content"], job, profile)
                    letter = create_cover_letter(job, profile)
                    answers = auto_answer_questions(job["questions"], profile, job)
                    add_application(job["id"], cv["id"], tailored, letter, answers)
                    created += 1
                return self._send(HTTPStatus.OK, {"applications_created": created})
        except Exception as exc:  # pragma: no cover
            return self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            html = (
                "<html><head><title>CareerCoachAI</title></head><body>"
                "<h1>CareerCoachAI Hazır</h1>"
                "<p>Preview ekranında Not Found görmemek için bu sayfa eklendi.</p>"
                "<ul>"
                "<li>Dashboard: <a href='/dashboard'>/dashboard</a></li>"
                "<li>CV listesi: <a href='/cvs'>/cvs</a></li>"
                "<li>İlan listesi: <a href='/jobs'>/jobs</a></li>"
                "<li>Başvurular: <a href='/applications'>/applications</a></li>"
                "</ul>"
                "<p>Detaylı kullanım adımları için README.md dosyasına bakın.</p>"
                "</body></html>"
            )
            return self._send(HTTPStatus.OK, html, content_type="text/html; charset=utf-8")
        if path == "/cvs":
            return self._send(HTTPStatus.OK, list_cvs())
        if path == "/jobs":
            return self._send(HTTPStatus.OK, list_jobs())
        if path == "/applications":
            return self._send(HTTPStatus.OK, list_applications())
        if path == "/dashboard":
            apps = list_applications()
            rows = "".join(
                f"<tr><td>{a['company']}</td><td>{a['position']}</td><td>{a['country']}</td>"
                f"<td>{a['salary_usd']}</td><td>{a['cv_title']}</td><td><pre>{a['cover_letter']}</pre></td>"
                f"<td><pre>{json.dumps(a['answers'], ensure_ascii=False, indent=2)}</pre></td><td>{a['created_at']}</td></tr>"
                for a in apps
            )
            html = (
                "<html><head><title>Dashboard</title></head><body>"
                "<h1>Başvuru Dashboard</h1>"
                "<table border='1'><tr><th>Firma</th><th>Pozisyon</th><th>Ülke</th><th>Maaş</th><th>CV</th><th>Cover Letter</th><th>Q&A</th><th>Tarih</th></tr>"
                f"{rows or '<tr><td colspan=8>Henüz başvuru yok.</td></tr>'}</table></body></html>"
            )
            return self._send(HTTPStatus.OK, html, content_type="text/html; charset=utf-8")
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), AppHandler)
    server.serve_forever()


if __name__ == "__main__":
    run()
