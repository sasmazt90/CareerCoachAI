from __future__ import annotations

import cgi
import html
import json
import re
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .audio_dsp import analyze_wav_bytes, parse_audio_metrics
from .file_parsers import extract_text
from .salary_intel import estimate_salary
from .services import (
    auto_answer_questions,
    build_cv_knowledge,
    create_cover_letter,
    interview_generate_question,
    interview_score,
    match_job,
    profile_match_score,
    tailor_cv,
)
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

COUNTRIES = [
    "Germany", "Netherlands", "United Kingdom", "United Arab Emirates", "Turkey", "United States", "Canada", "Ireland",
    "Sweden", "Switzerland", "Spain", "Italy", "France", "Portugal", "Belgium", "Austria", "Denmark", "Norway",
    "Finland", "Poland", "Czechia", "Hungary", "Romania", "Bulgaria", "Greece", "Luxembourg",
]

CITIES_BY_COUNTRY = {
    "Germany": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"],
    "Netherlands": ["Amsterdam", "Rotterdam", "Utrecht", "Eindhoven", "The Hague"],
    "United Kingdom": ["London", "Manchester", "Birmingham", "Leeds", "Edinburgh"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman"],
    "Turkey": ["Istanbul", "Ankara", "Izmir", "Bursa", "Antalya"],
    "United States": ["New York", "San Francisco", "Seattle", "Austin", "Chicago"],
    "Canada": ["Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary"],
    "Ireland": ["Dublin", "Cork", "Galway", "Limerick"],
    "Sweden": ["Stockholm", "Gothenburg", "Malmo"],
    "Switzerland": ["Zurich", "Geneva", "Basel", "Bern"],
    "Spain": ["Madrid", "Barcelona", "Valencia", "Seville"],
    "Italy": ["Milan", "Rome", "Turin", "Bologna"],
    "France": ["Paris", "Lyon", "Marseille", "Toulouse"],
    "Portugal": ["Lisbon", "Porto", "Braga"],
    "Belgium": ["Brussels", "Antwerp", "Ghent"],
    "Austria": ["Vienna", "Graz", "Linz"],
    "Denmark": ["Copenhagen", "Aarhus", "Odense"],
    "Norway": ["Oslo", "Bergen", "Trondheim"],
    "Finland": ["Helsinki", "Espoo", "Tampere"],
    "Poland": ["Warsaw", "Krakow", "Wroclaw"],
    "Czechia": ["Prague", "Brno", "Ostrava"],
    "Hungary": ["Budapest", "Debrecen", "Szeged"],
    "Romania": ["Bucharest", "Cluj-Napoca", "Timisoara"],
    "Bulgaria": ["Sofia", "Plovdiv", "Varna"],
    "Greece": ["Athens", "Thessaloniki", "Patras"],
    "Luxembourg": ["Luxembourg City", "Esch-sur-Alzette"],
}



COUNTRY_CURRENCY = {
    "Germany": "EUR", "Netherlands": "EUR", "United Kingdom": "GBP", "United Arab Emirates": "AED", "Turkey": "TRY",
    "United States": "USD", "Canada": "USD", "Ireland": "EUR", "Sweden": "EUR", "Switzerland": "EUR",
    "Spain": "EUR", "Italy": "EUR", "France": "EUR", "Portugal": "EUR", "Belgium": "EUR", "Austria": "EUR",
    "Denmark": "EUR", "Norway": "EUR", "Finland": "EUR", "Poland": "EUR", "Czechia": "EUR", "Hungary": "EUR",
    "Romania": "EUR", "Bulgaria": "EUR", "Greece": "EUR", "Luxembourg": "EUR",
}

DEFAULT_SCREENING_QUESTIONS = [
    "Why are you a fit for this role?",
    "What measurable impact did you deliver in a similar role?",
    "How would you approach the first 90 days?",
]


def infer_job_facts(company: str, position: str, country: str, description: str) -> dict:
    text = f"{position} {description}".lower()
    if any(k in text for k in ["head", "director", "vp", "chief"]):
        seniority = "lead"
    elif any(k in text for k in ["senior", "principal", "staff"]):
        seniority = "senior"
    elif any(k in text for k in ["intern", "junior", "entry"]):
        seniority = "junior"
    else:
        seniority = "mid"

    currency = COUNTRY_CURRENCY.get(country, "USD")

    # quick market heuristic in USD, then convert
    base_usd = {"junior": 55000, "mid": 85000, "senior": 115000, "lead": 140000}[seniority]
    if "manager" in text:
        base_usd *= 1.08
    if "engineer" in text or "scientist" in text:
        base_usd *= 1.05
    if "head" in text or "director" in text:
        base_usd *= 1.12
    salary_usd = int(round(base_usd))
    salary_amount = salary_usd if currency == "USD" else round(salary_usd / CURRENCY_RATES_TO_USD.get(currency, 1.0), 2)

    return {
        "seniority": seniority,
        "salary_currency": currency,
        "salary_usd": salary_usd,
        "salary_amount": salary_amount,
        "questions": DEFAULT_SCREENING_QUESTIONS,
    }

def fmt_num(v: float | int, digits: int = 2) -> str:
    return f"{float(v):,.{digits}f}"


def _escape_pdf_text(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def simple_pdf_from_text(title: str, body: str) -> bytes:
    lines = [title, ""] + body.splitlines()
    y = 790
    text_ops = ["BT", "/F1 11 Tf", "50 815 Td", f"({_escape_pdf_text(title)}) Tj", "ET"]
    for line in lines[1:]:
        y -= 14
        if y < 50:
            break
        text_ops += ["BT", "/F1 10 Tf", f"50 {y} Td", f"({_escape_pdf_text(line[:140])}) Tj", "ET"]
    content = "\n".join(text_ops).encode("latin-1", errors="replace")
    objs = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>endobj\n",
        b"4 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
        f"5 0 obj<< /Length {len(content)} >>stream\n".encode() + content + b"\nendstream endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = [0]
    for o in objs:
        offs.append(len(out)); out.extend(o)
    xref = len(out)
    out.extend(f"xref\n0 {len(offs)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offs[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(f"trailer<< /Size {len(offs)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(out)


def latest_app_by_job(job_id: int) -> dict | None:
    for a in list_applications():
        if int(a.get("job_id", 0)) == int(job_id):
            return a
    return None


def ensure_assets_for_job(job: dict, regenerate: bool = False) -> dict:
    existing = latest_app_by_job(int(job["id"]))
    if existing and not regenerate:
        return existing
    profile, cvs = get_profile() or {}, list_cvs()
    if not profile or not cvs:
        raise RuntimeError("Profile and at least one CV are required")
    key = get_openai_api_key()
    try:
        corpus = build_cv_knowledge(cvs, profile, key)
    except Exception:
        corpus = build_cv_knowledge(cvs, profile, "")
    cv = tailor_cv(cvs[0]["content"], job, profile, corpus, key)
    cl = create_cover_letter(job, profile, corpus, key)
    ans = auto_answer_questions(job.get("questions", []), profile, job, corpus, key)
    add_application(job["id"], cvs[0]["id"], cv, cl, ans, status="ready_to_submit", notes="job_assets")
    return latest_app_by_job(int(job["id"])) or {}


def esc(v: object) -> str:
    return html.escape(str(v))


def page(title: str, body: str) -> str:
    return f"""
    <html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width, initial-scale=1'/><title>{esc(title)}</title>
    <style>
    :root{{--bg:#050816;--bg2:#0a1128;--card:rgba(17,24,39,.88);--txt:#e5e7eb;--muted:#9ca3af;--line:#29334b;--accent:#6366f1;--accent2:#8b5cf6;--ok:#22c55e;--warn:#f59e0b}}
    *{{box-sizing:border-box}}body{{font-family:Inter,Segoe UI,Arial;background:radial-gradient(1200px 500px at 10% -10%,#1d2c5e 0%,var(--bg) 45%),linear-gradient(180deg,var(--bg),var(--bg2));color:var(--txt);margin:0;min-height:100vh}}
    .wrap{{max-width:1240px;margin:0 auto;padding:24px}}
    .top{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}}
    .nav a{{display:inline-block;color:#c7d2fe;text-decoration:none;margin-right:8px;padding:8px 11px;border-radius:10px;border:1px solid transparent}}
    .nav a:hover{{border-color:#3b4a71;background:#111a33}}
    .card{{background:var(--card);backdrop-filter: blur(8px);border:1px solid var(--line);border-radius:16px;padding:18px;margin-top:14px;box-shadow:0 8px 32px rgba(0,0,0,.25)}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
    input,textarea,select{{width:100%;padding:10px;border-radius:10px;border:1px solid #3b4462;background:#0a1428;color:var(--txt)}}
    label{{display:block;margin:10px 0 6px;color:var(--muted)}}
    button{{background:linear-gradient(90deg,var(--accent),var(--accent2));color:#fff;border:0;border-radius:10px;padding:10px 14px;cursor:pointer;font-weight:600}}
    .btn-alt{{background:#1f2937}} table{{width:100%;border-collapse:collapse}} th,td{{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}
    pre{{white-space:pre-wrap;max-height:250px;overflow:auto;margin:0}} .badge{{display:inline-block;padding:3px 8px;border-radius:999px;background:#1e293b;font-size:12px}}
    .hint{{font-size:12px;color:var(--muted)}} .row{{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;align-items:end}}
    .pill{{display:inline-block;padding:6px 10px;border-radius:999px;background:#131d37;border:1px solid #2f3c5b;margin:0 6px 6px 0}}
    </style></head><body><div class='wrap'>
    <div class='top'><h2>{esc(title)}</h2><div class='nav'>
      <a href='/'>Home</a><a href='/profile-form'>Profile</a><a href='/cvs/upload'>CV Upload</a><a href='/jobs/list'>Jobs</a><a href='/salary-intel'>Salary Intel</a>
      <a href='/settings'>OpenAI</a><a href='/dashboard'>Dashboard</a><a href='/cover-letters'>Cover Letters</a><a href='/interview'>Interview</a>
    </div></div>{body}</div></body></html>
    """


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
                f = self._form()
                set_openai_api_key((f.get("openai_api_key") or [""])[0])
                return self._redirect("/settings")

            if p == "/profile-form":
                f = self._form()
                curr = ((f.get("preferred_currency") or ["USD"])[0]).upper()
                raw_locations = (f.get("locations_json") or ["[]"])[0]
                try:
                    locations = json.loads(raw_locations)
                except Exception:
                    locations = []
                if not isinstance(locations, list):
                    locations = []
                clean_locations = []
                for item in locations:
                    if not isinstance(item, dict):
                        continue
                    country = str(item.get("country", "")).strip()
                    city = str(item.get("city", "")).strip()
                    if country and city:
                        clean_locations.append({"country": country, "city": city})
                countries = sorted({x["country"] for x in clean_locations})
                if not countries:
                    countries = f.get("countries") or [x.strip() for x in (f.get("countries_csv") or [""])[0].split(",") if x.strip()]
                    clean_locations = [{"country": c, "city": ""} for c in countries]
                upsert_profile(
                    {
                        "full_name": (f.get("full_name") or [""])[0],
                        "email": (f.get("email") or [""])[0],
                        "countries": countries,
                        "locations": clean_locations,
                        "target_positions": [x.strip() for x in (f.get("target_positions") or [""])[0].split(",") if x.strip()],
                        "minimum_salary_usd": to_usd(float((f.get("minimum_salary_amount") or ["0"])[0] or 0), curr),
                        "preferred_currency": curr,
                        "career_history": (f.get("career_history") or [""])[0],
                    }
                )
                return self._redirect("/dashboard")

            if p == "/jobs/new":
                f = self._form()
                company = (f.get("company") or [""])[0]
                position = (f.get("position") or [""])[0]
                country = (f.get("country") or [""])[0]
                city = (f.get("city") or [""])[0]
                description = (f.get("description") or [""])[0]
                inferred = infer_job_facts(company, position, country, description)
                add_job(
                    {
                        "company": company,
                        "position": position,
                        "country": country,
                        "city": city,
                        "salary_amount": inferred["salary_amount"],
                        "salary_currency": inferred["salary_currency"],
                        "salary_usd": inferred["salary_usd"],
                        "description": description,
                        "questions": inferred["questions"],
                        "seniority": inferred["seniority"],
                        "source_url": (f.get("source_url") or [""])[0],
                    }
                )
                return self._redirect("/jobs/list?msg=job_saved")

            if p == "/cvs/upload":
                fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
                title = fs.getvalue("title", "CV Collection")
                files = fs["cv_files"] if "cv_files" in fs else []
                if not isinstance(files, list):
                    files = [files]
                saved = 0
                for i, fi in enumerate(files, start=1):
                    if fi is None or not getattr(fi, "file", None):
                        continue
                    name = Path(getattr(fi, "filename", "cv.txt") or "cv.txt").name
                    blob = fi.file.read()
                    if not blob:
                        continue
                    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
                    sp = UPLOAD_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{safe}"
                    sp.write_bytes(blob)
                    add_cv({"title": f"{title} #{i}", "content": extract_text(name, blob), "original_filename": name, "stored_path": str(sp)})
                    saved += 1
                if not saved:
                    return self._send(400, {"error": "No CV uploaded"})
                return self._redirect("/dashboard")

            if p == "/auto-apply":
                profile, cvs, jobs = get_profile(), list_cvs(), list_jobs()
                if not profile:
                    if self.headers.get("Content-Type", "").startswith("application/json"):
                        return self._send(400, {"error": "profile missing"})
                    return self._redirect("/dashboard?msg=profile_missing")
                if not cvs:
                    if self.headers.get("Content-Type", "").startswith("application/json"):
                        return self._send(400, {"error": "cv missing"})
                    return self._redirect("/dashboard?msg=cv_missing")
                if not jobs:
                    if self.headers.get("Content-Type", "").startswith("application/json"):
                        return self._send(400, {"error": "job missing"})
                    return self._redirect("/dashboard?msg=job_missing")
                key = get_openai_api_key()
                corpus = build_cv_knowledge(cvs, profile, key)
                created = 0
                for job in jobs:
                    if not match_job(profile, job).matched:
                        continue
                    cv = tailor_cv(cvs[0]["content"], job, profile, corpus, key)
                    cl = create_cover_letter(job, profile, corpus, key)
                    ans = auto_answer_questions(job.get("questions", []), profile, job, corpus, key)
                    add_application(job["id"], cvs[0]["id"], cv, cl, ans, status="ready_to_submit", notes="ATS+facts only")
                    created += 1
                if self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._send(200, {"applications_created": created})
                return self._redirect(f"/dashboard?msg=applications_created:{created}")

            if p == "/interview/start":
                f = self._form(); iid = create_interview(int((f.get("job_id") or ["0"])[0]), int((f.get("stage") or ["1"])[0]))
                return self._redirect(f"/interview/session?id={iid}")

            if p == "/interview/answer":
                iid = 0
                answer = ""
                audio_metrics = None
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("multipart/form-data"):
                    fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype})
                    iid = int((fs.getvalue("interview_id", "0") or "0"))
                    answer = fs.getvalue("answer", "")
                    audio_item = fs["audio_file"] if "audio_file" in fs else None
                    if audio_item is not None and getattr(audio_item, "file", None):
                        blob = audio_item.file.read()
                        if blob:
                            try:
                                audio_metrics = analyze_wav_bytes(blob)
                            except Exception:
                                audio_metrics = {"error": "audio_parse_failed"}
                else:
                    f = self._form(); iid = int((f.get("interview_id") or ["0"])[0]); answer = (f.get("answer") or [""])[0]
                iv = get_interview(iid)
                job = get_job(iv["job_id"]) if iv else None
                if not iv or not job:
                    return self._send(404, {"error": "interview not found"})
                add_interview_message(iid, "candidate", answer)
                if audio_metrics is not None:
                    add_interview_message(iid, "audio_analyst", json.dumps(audio_metrics))
                knowledge = build_cv_knowledge(list_cvs(), get_profile() or {}, "")
                q = interview_generate_question(job, iv["stage"], list_interview_messages(iid), get_profile() or {}, knowledge, get_openai_api_key())
                add_interview_message(iid, "interviewer", q)
                return self._redirect(f"/interview/session?id={iid}")

            if p == "/interview/finish":
                f = self._form(); iid = int((f.get("interview_id") or ["0"])[0]); iv = get_interview(iid)
                if not iv:
                    return self._send(404, {"error": "interview not found"})
                job = get_job(iv["job_id"]) or {}
                msgs = list_interview_messages(iid)
                audio_summary = parse_audio_metrics(msgs)
                scoring = interview_score(job, iv["stage"], msgs, get_profile() or {}, build_cv_knowledge(list_cvs(), get_profile() or {}, get_openai_api_key()), get_openai_api_key(), audio_summary=audio_summary)
                overall = float(scoring.get("overall", 0))
                passed = bool(scoring.get("passed", overall >= 75))
                finalize_interview(iid, "passed" if passed else "failed", overall, scoring, str(scoring.get("recommendation", "")))
                return self._redirect(f"/interview/session?id={iid}")

            if p == "/interview/retry":
                f = self._form(); prev = get_interview(int((f.get("interview_id") or ["0"])[0]))
                if not prev:
                    return self._send(404, {"error": "interview not found"})
                iid = create_interview(prev["job_id"], prev["stage"])
                return self._redirect(f"/interview/session?id={iid}")

            if p == "/profile":
                upsert_profile(self._json()); return self._send(200, {"status": "ok"})
            if p == "/cvs":
                return self._send(200, {"cv_id": add_cv(self._json())})
            if p == "/jobs":
                return self._send(200, {"job_id": add_job(self._json())})

            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def do_GET(self):  # noqa: N802
        p = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)
        try:
            if p == "/":
                apps, jobs, cvs = list_applications(), list_jobs(), list_cvs()
                msg = (q.get('msg') or [''])[0]
                alert = f"<div class='card'><strong>{esc(msg.replace('_', ' '))}</strong></div>" if msg else ''
                body = f"{alert}<div class='grid'><div class='card'><span class='badge'>Applications</span><h3>{len(apps)}</h3></div><div class='card'><span class='badge'>Jobs</span><h3>{len(jobs)}</h3></div><div class='card'><span class='badge'>CV Versions</span><h3>{len(cvs)}</h3></div></div><div class='card'><form method='post' action='/auto-apply'><button>Run Auto Apply</button></form></div>"
                return self._send(200, page("CareerCoachAI Platform", body), "text/html; charset=utf-8")

            if p == "/settings":
                key = get_openai_api_key(); masked = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else "(not set)"
                return self._send(200, page("Settings", f"<div class='card'><p>Current key: <strong>{esc(masked)}</strong></p><form method='post' action='/settings'><label>OPENAI_API_KEY</label><input type='password' name='openai_api_key' required/><br/><br/><button>Save Secret</button></form></div>"), "text/html; charset=utf-8")

            if p == "/profile-form":
                pr = get_profile() or {"full_name": "", "email": "", "countries": [], "locations": [], "target_positions": [], "minimum_salary_usd": 0, "preferred_currency": "USD", "career_history": ""}
                cu = "".join(f"<option value='{esc(c)}' {'selected' if c == pr['preferred_currency'] else ''}>{esc(c)}</option>" for c in CURRENCY_RATES_TO_USD)
                country_opts = "".join(f"<option value='{esc(c)}'>{esc(c)}</option>" for c in COUNTRIES)
                initial_locations = pr.get("locations") or [{"country": c, "city": ""} for c in pr.get("countries", [])]
                body = f"""
                <div class='card'>
                  <form method='post' action='/profile-form'>
                    <label>Full Name</label><input name='full_name' value='{esc(pr['full_name'])}' required/>
                    <label>Email</label><input name='email' value='{esc(pr['email'])}' required/>
                    <label>Target Locations (Country + City)</label>
                    <div class='row'>
                      <div><select id='country-picker'><option value=''>Select country</option>{country_opts}</select></div>
                      <div><select id='city-picker'><option value=''>Select city</option></select></div>
                      <div><button type='button' class='btn-alt' onclick='addLocation()'>Add</button></div>
                    </div>
                    <p class='hint'>Ülke seçtikten sonra şehir seçip Add ile listeye ekleyin. İstediğiniz kadar kombinasyon ekleyebilirsiniz.</p>
                    <div id='locations-list'></div>
                    <input type='hidden' name='locations_json' id='locations_json'/>
                    <label>Target Positions (comma separated)</label><input name='target_positions' value='{esc(', '.join(pr['target_positions']))}'/>
                    <label>Minimum Salary</label><input type='number' name='minimum_salary_amount' value='{esc(pr['minimum_salary_usd'])}'/>
                    <label>Currency</label><select name='preferred_currency'>{cu}</select>
                    <label>Career History</label><textarea name='career_history' rows='6'>{esc(pr['career_history'])}</textarea>
                    <br/><br/><button>Save Profile</button>
                  </form>
                </div>
                <script>
                const cityMap = {json.dumps(CITIES_BY_COUNTRY)};
                let locations = {json.dumps(initial_locations)};
                const countrySel = document.getElementById('country-picker');
                const citySel = document.getElementById('city-picker');
                const listWrap = document.getElementById('locations-list');
                const locInput = document.getElementById('locations_json');
                function refreshCities() {{
                  const country = countrySel.value;
                  const cities = cityMap[country] || [];
                  citySel.innerHTML = "<option value=''>Select city</option>" + cities.map(c => `<option value="${{c}}">${{c}}</option>`).join('');
                }}
                function renderLocations() {{
                  locInput.value = JSON.stringify(locations);
                  listWrap.innerHTML = locations.length
                    ? locations.map((item, idx) => `<span class='pill'>${{item.country}} - ${{item.city}} <a href='#' onclick='removeLocation(${{idx}});return false;'>✕</a></span>`).join('')
                    : "<p class='hint'>Henüz lokasyon eklenmedi.</p>";
                }}
                function addLocation() {{
                  const country = countrySel.value;
                  const city = citySel.value;
                  if (!country || !city) return;
                  if (!locations.some(x => x.country === country && x.city === city)) {{
                    locations.push({{country, city}});
                    renderLocations();
                  }}
                }}
                function removeLocation(i) {{
                  locations.splice(i, 1);
                  renderLocations();
                }}
                countrySel.addEventListener('change', refreshCities);
                refreshCities();
                renderLocations();
                </script>
                """
                return self._send(200, page("Candidate Profile", body), "text/html; charset=utf-8")

            if p == "/cvs/upload":
                rows = "".join(
                    f"<tr><td>{esc(c['title'])}</td><td>{esc(c.get('original_filename', ''))}</td><td>{esc((c.get('content') or '')[:120])}...</td><td><a href='/cvs/preview?id={esc(c['id'])}'>Preview</a></td></tr>"
                    for c in list_cvs()
                )
                empty_cv = "<tr><td colspan='4'>No CV uploaded.</td></tr>"
                body = f"<div class='card'><form method='post' action='/cvs/upload' enctype='multipart/form-data'><label>CV Group Title</label><input name='title' value='My CV Collection'/><label>CV Files (.txt/.pdf/.docx/.doc)</label><input type='file' name='cv_files' multiple required/><br/><br/><button>Upload</button></form></div><div class='card'><table><thead><tr><th>Title</th><th>File</th><th>Excerpt</th><th>Preview</th></tr></thead><tbody>{rows or empty_cv}</tbody></table></div>"
                return self._send(200, page("CV Upload", body), "text/html; charset=utf-8")

            if p == "/cvs/preview":
                cid = int((q.get("id") or ["0"])[0] or 0)
                cv = next((c for c in list_cvs() if int(c.get("id", 0)) == cid), None)
                if not cv:
                    return self._send(404, page("CV Preview", "<div class='card'>CV not found.</div>"), "text/html; charset=utf-8")
                body = f"<div class='card'><h3>{esc(cv.get('title', 'CV'))}</h3><p><strong>File:</strong> {esc(cv.get('original_filename', ''))}</p><pre>{esc(cv.get('content', ''))}</pre></div>"
                return self._send(200, page("CV Preview", body), "text/html; charset=utf-8")

            if p == "/jobs/new":
                co = "".join(f"<option value='{esc(c)}'>{esc(c)}</option>" for c in COUNTRIES)
                body = f"""
                <div class='card'>
                  <form method='post' action='/jobs/new'>
                    <label>Company</label><input name='company' required/>
                    <label>Position</label><input name='position' required/>
                    <label>Country</label><select id='job-country' name='country'>{co}</select>
                    <label>City</label><select id='job-city' name='city'></select>
                    <label>Description</label><textarea name='description' rows='5' required></textarea>
                    <label>Source URL</label><input name='source_url'/>
                    <p class='hint'>Seniority, currency, salary ve screening questions otomatik çıkarılır.</p>
                    <br/><button>Save Job</button>
                  </form>
                </div>
                <script>
                const cityMap = {json.dumps(CITIES_BY_COUNTRY)};
                const countrySel = document.getElementById('job-country');
                const citySel = document.getElementById('job-city');
                function refreshJobCities() {{
                    const country = countrySel.value;
                    const cities = cityMap[country] || [];
                    citySel.innerHTML = cities.map(c => `<option value="${{c}}">${{c}}</option>`).join('');
                }}
                countrySel.addEventListener('change', refreshJobCities);
                refreshJobCities();
                </script>
                """
                return self._send(200, page("Job Intake", body), "text/html; charset=utf-8")

            if p == "/jobs/list":
                jobs = list_jobs()
                rows = []
                for j in jobs:
                    app = latest_app_by_job(int(j["id"]))
                    if app:
                        resume_actions = f"<a href='/jobs/resume/view?job_id={j['id']}'>View Resume</a> | <a href='/jobs/resume/regenerate?job_id={j['id']}'>Regenerate</a>"
                    else:
                        resume_actions = f"<a href='/jobs/resume/generate?job_id={j['id']}'>Generate Resume</a>"
                    actions = " | ".join([
                        f"<a href='/jobs/view?id={j['id']}'>View</a>",
                        f"<a href='/salary-intel?job_id={j['id']}'>Expected Salary</a>",
                        f"<a href='/jobs/cover-letter?job_id={j['id']}'>Cover Letter</a>",
                        resume_actions,
                    ])
                    rows.append(f"<tr><td>{esc(j['company'])}</td><td>{esc(j['position'])}</td><td>{esc(j.get('country',''))} / {esc(j.get('city',''))}</td><td>{fmt_num(j.get('salary_amount',0))} {esc(j.get('salary_currency','USD'))}</td><td>{actions}</td></tr>")
                table_rows = ''.join(rows) or "<tr><td colspan='5'>No jobs yet.</td></tr>"
                body = f"<div class='card'><a class='pill' href='/jobs/new'>Add New</a></div><div class='card'><table><thead><tr><th>Company</th><th>Position</th><th>Country/City</th><th>Expected Salary</th><th>Actions</th></tr></thead><tbody>{table_rows}</tbody></table></div>"
                return self._send(200, page("Jobs", body), "text/html; charset=utf-8")

            if p == "/jobs/view":
                jid = int((q.get("id") or ["0"])[0] or 0)
                job = get_job(jid)
                if not job:
                    return self._send(404, page("Job View", "<div class='card'>Job not found.</div>"), "text/html; charset=utf-8")
                body = f"<div class='card'><h3>{esc(job['company'])} — {esc(job['position'])}</h3><p><strong>Location:</strong> {esc(job.get('country',''))} / {esc(job.get('city',''))}</p><p><strong>Expected Salary:</strong> {fmt_num(job.get('salary_amount',0))} {esc(job.get('salary_currency','USD'))}</p><p><strong>Seniority:</strong> {esc(job.get('seniority',''))}</p><pre>{esc(job.get('description',''))}</pre></div>"
                return self._send(200, page("Job View", body), "text/html; charset=utf-8")

            if p in {"/jobs/cover-letter", "/jobs/resume/generate", "/jobs/resume/regenerate"}:
                jid = int((q.get("job_id") or ["0"])[0] or 0)
                job = get_job(jid)
                if not job:
                    return self._send(404, page("Jobs", "<div class='card'>Job not found.</div>"), "text/html; charset=utf-8")
                try:
                    app = ensure_assets_for_job(job, regenerate=(p == "/jobs/resume/regenerate"))
                except Exception as exc:
                    return self._send(400, page("Jobs", f"<div class='card'>{esc(str(exc))}</div>"), "text/html; charset=utf-8")
                if p == "/jobs/cover-letter":
                    return self._redirect(f"/cover-letter/view?app_id={app.get('id', 0)}")
                return self._redirect(f"/jobs/resume/view?job_id={jid}")

            if p == "/jobs/resume/view":
                jid = int((q.get("job_id") or ["0"])[0] or 0)
                app = latest_app_by_job(jid)
                if not app:
                    return self._send(404, page("Resume", "<div class='card'>Resume not generated for this job.</div>"), "text/html; charset=utf-8")
                body = f"<div class='card'><h3>Generated Resume</h3><pre>{esc(app.get('tailored_cv',''))}</pre><p><a href='/jobs/resume/regenerate?job_id={jid}'>Regenerate</a></p></div>"
                return self._send(200, page("Generated Resume", body), "text/html; charset=utf-8")

            if p == "/cover-letter/view":
                app_id = int((q.get("app_id") or ["0"])[0] or 0)
                app = next((a for a in list_applications() if int(a.get("id", 0)) == app_id), None)
                if not app:
                    return self._send(404, page("Cover Letter", "<div class='card'>Cover letter not found.</div>"), "text/html; charset=utf-8")
                body = f"""
                <div class='card'>
                  <div style='background:#fff;color:#111;padding:36px;border-radius:12px;max-width:900px;margin:auto;font-family:Georgia,serif;line-height:1.6'>
                    <h2 style='margin:0 0 8px 0'>{esc(app.get('company',''))} — Cover Letter</h2>
                    <p style='color:#555;margin-top:0'>{esc(app.get('position',''))}</p>
                    <hr/>
                    <div style='white-space:pre-wrap'>{esc(app.get('cover_letter',''))}</div>
                  </div>
                  <p style='margin-top:14px'><a href='/cover-letter/download?app_id={app_id}'>Download PDF</a></p>
                </div>
                """
                return self._send(200, page("Cover Letter", body), "text/html; charset=utf-8")

            if p == "/cover-letter/download":
                app_id = int((q.get("app_id") or ["0"])[0] or 0)
                app = next((a for a in list_applications() if int(a.get("id", 0)) == app_id), None)
                if not app:
                    return self._send(404, {"error": "cover letter not found"})
                pdf = simple_pdf_from_text(f"Cover Letter - {app.get('company','')}", app.get("cover_letter", ""))
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f"attachment; filename=cover_letter_{app_id}.pdf")
                self.end_headers()
                self.wfile.write(pdf)
                return

            if p == "/salary-intel":
                jobs = list_jobs()
                profile = get_profile() or {"countries": [], "target_positions": [], "minimum_salary_usd": 0}
                pref = (get_profile() or {}).get("preferred_currency", "USD")
                selected = int((q.get("job_id") or [str(jobs[0]["id"] if jobs else 0)])[0] or 0)
                manual_company = (q.get("company") or [""])[0].strip()
                manual_position = (q.get("position") or [""])[0].strip()
                manual_country = (q.get("country") or ["Germany"])[0].strip() or "Germany"
                manual_city = (q.get("city") or [""])[0].strip()
                manual_description = (q.get("description") or [""])[0].strip()

                if manual_company and manual_position:
                    inferred = infer_job_facts(manual_company, manual_position, manual_country, manual_description)
                    job = {"id": 0, "company": manual_company, "position": manual_position, "country": manual_country, "city": manual_city, "description": manual_description, "salary_currency": inferred["salary_currency"], "salary_amount": inferred["salary_amount"], "salary_usd": inferred["salary_usd"], "seniority": inferred["seniority"], "questions": inferred["questions"]}
                elif jobs:
                    job = next((j for j in jobs if int(j["id"]) == selected), jobs[0])
                else:
                    job = {"id": 0, "company": "Sample Company", "position": "Head of Digital", "country": "Germany", "city": "Munich", "description": "Digital transformation and analytics leadership.", "salary_currency": "EUR", "salary_amount": 0, "salary_usd": 0, "seniority": "senior", "questions": []}

                report = estimate_salary(job, jobs, target_currency=pref)
                match = profile_match_score(profile, job)
                options = "".join(f"<option value='{j['id']}' {'selected' if int(j['id'])==int(job.get('id',0)) else ''}>{esc(j['company'])} - {esc(j['position'])}</option>" for j in jobs)
                body = (
                    f"<div class='card'><details><summary><strong>Add New</strong> (Saved Job Analysis)</summary><form method='get' action='/salary-intel'><label>Saved Job</label><select name='job_id'>{options}</select><br/><button>Analyze</button></form></details></div>"
                    f"<div class='card'><details><summary><strong>Add New</strong> (Manual Analysis)</summary><form method='get' action='/salary-intel'><label>Company</label><input name='company' value='{esc(manual_company)}' required/><label>Position</label><input name='position' value='{esc(manual_position)}' required/><label>Country</label><input name='country' value='{esc(manual_country)}'/><label>City</label><input name='city' value='{esc(manual_city)}'/><label>Description</label><textarea name='description' rows='4'>{esc(manual_description)}</textarea><br/><button>Analyze Manual</button></form></details></div>"
                    f"<div class='grid'><div class='card'><span class='badge'>Profile Match</span><h3>{fmt_num(match['match_percent'],0)}%</h3><ul>{''.join(f'<li>{esc(d)}</li>' for d in match['details'])}</ul></div>"
                    f"<div class='card'><span class='badge'>Expected Salary</span><h3>{fmt_num(report['expected_salary'])} {report['currency']}</h3><p>Policy vs Market: {fmt_num(report['policy_vs_market_pct'])}%</p><p>Market Range: {fmt_num(report['market_range'][0])} - {fmt_num(report['market_range'][1])} {report['currency']}</p><p>{esc(report['method'])}</p><p>Evidence: {esc(report['evidence_source'])}</p></div></div>"
                )
                return self._send(200, page("Salary Intelligence", body), "text/html; charset=utf-8")

            if p == "/dashboard":
                rows = "".join(
                    f"<tr><td>{esc(a['company'])}</td><td>{esc(a['position'])}</td><td>{esc(a['country'])} / {esc(a.get('city',''))}</td><td>{fmt_num(a['salary_amount'])} {esc(a['salary_currency'])}</td><td>{esc(a['cv_title'])}</td><td>{esc(a['status'])}</td><td>{esc(a['notes'])}</td><td><a href='/cover-letter/view?app_id={esc(a['id'])}'>Cover Letter</a> | <a href='/salary-intel?job_id={esc(a['job_id'])}'>Salary Intel</a></td><td><pre>{esc(json.dumps(a['answers'], ensure_ascii=False, indent=2))}</pre></td><td>{esc(a['created_at'])}</td></tr>"
                    for a in list_applications()
                )
                empty_app = "<tr><td colspan='10'>No applications yet.</td></tr>"
                msg = (q.get('msg') or [''])[0]
                nice_msg = msg.replace('applications_created:', 'Applications created: ').replace('_', ' ') if msg else ''
                alert = f"<div class='card'><strong>{esc(nice_msg)}</strong></div>" if msg else ''
                body = f"{alert}<div class='card'><form method='post' action='/auto-apply'><button>Generate Applications</button></form></div><div class='card'><table><thead><tr><th>Company</th><th>Position</th><th>Country/City</th><th>Salary</th><th>CV</th><th>Status</th><th>Notes</th><th>Links</th><th>Answers</th><th>Date</th></tr></thead><tbody>{rows or empty_app}</tbody></table></div>"
                return self._send(200, page("Application Dashboard", body), "text/html; charset=utf-8")

            if p == "/cover-letters":
                rows = "".join(
                    f"<tr><td>{esc(a['company'])}</td><td>{esc(a['position'])}</td><td><a href='/cover-letter/view?app_id={a['id']}'>View</a> | <a href='/cover-letter/download?app_id={a['id']}'>Download PDF</a></td></tr>"
                    for a in list_applications()
                )
                empty_cover = "<tr><td colspan='3'>No cover letters yet.</td></tr>"
                body = f"<div class='card'><table><thead><tr><th>Company</th><th>Role</th><th>Actions</th></tr></thead><tbody>{rows or empty_cover}</tbody></table></div>"
                return self._send(200, page("Cover Letters", body), "text/html; charset=utf-8")

            if p == "/interview":
                opts = "".join(f"<option value='{j['id']}'>{esc(j['company'])} - {esc(j['position'])}</option>" for j in list_jobs())
                body = f"<div class='card'><p>Stage 1 HR → Stage 2 Unit Manager</p><form method='post' action='/interview/start'><label>Job</label><select name='job_id'>{opts}</select><label>Stage</label><select name='stage'><option value='1'>1 - HR Manager</option><option value='2'>2 - Unit Manager</option></select><br/><br/><button>Start Interview</button></form></div>"
                return self._send(200, page("Interview", body), "text/html; charset=utf-8")

            if p == "/interview/session":
                iid = int((q.get("id") or ["0"])[0])
                iv = get_interview(iid)
                if not iv:
                    return self._send(404, page("Interview", "<div class='card'>Interview not found.</div>"), "text/html; charset=utf-8")
                msgs = list_interview_messages(iid)
                if not msgs:
                    job = get_job(iv["job_id"]) or {}
                    knowledge = build_cv_knowledge(list_cvs(), get_profile() or {}, "")
                    q1 = interview_generate_question(job, iv["stage"], [], get_profile() or {}, knowledge, get_openai_api_key())
                    add_interview_message(iid, "interviewer", q1)
                    msgs = list_interview_messages(iid)
                rows = "".join(f"<tr><td>{esc(m['role'])}</td><td>{esc(m['content'])}</td></tr>" for m in msgs)
                score = ""
                if iv["status"] in {"passed", "failed"}:
                    s = iv["score_breakdown"]
                    score = f"<div class='card'><h3>Score {esc(iv['score'])}</h3><pre>{esc(json.dumps(s, ensure_ascii=False, indent=2))}</pre><p>{esc(iv['recommendation'])}</p>"
                    if iv["status"] == "passed" and iv["stage"] == 2:
                        score += "<h3>YOU GOT THE JOB 🎉</h3>"
                    elif iv["status"] == "passed":
                        score += f"<form method='post' action='/interview/start'><input type='hidden' name='job_id' value='{esc(iv['job_id'])}'/><input type='hidden' name='stage' value='2'/><button>Go Stage 2</button></form>"
                    else:
                        score += f"<form method='post' action='/interview/retry'><input type='hidden' name='interview_id' value='{esc(iid)}'/><button>Retry</button></form>"
                    score += "</div>"
                body = f"<div class='card'><table><thead><tr><th>Role</th><th>Message</th></tr></thead><tbody>{rows}</tbody></table></div><div class='card'><form method='post' action='/interview/answer' enctype='multipart/form-data'><input type='hidden' name='interview_id' value='{esc(iid)}'/><label>Your answer (text / voice typing)</label><textarea name='answer' rows='5' required></textarea><label>Optional .wav for real-time DSP stress analysis</label><input type='file' name='audio_file' accept='.wav,audio/wav'/><br/><br/><button>Send Answer</button></form><br/><form method='post' action='/interview/finish'><input type='hidden' name='interview_id' value='{esc(iid)}'/><button>Finish & Score</button></form></div>{score}"
                return self._send(200, page("Interview Session", body), "text/html; charset=utf-8")

            if p == "/cvs":
                return self._send(200, list_cvs())
            if p == "/jobs":
                return self._send(200, list_jobs())
            if p == "/applications":
                return self._send(200, list_applications())

            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    init_db()
    ThreadingHTTPServer((host, port), AppHandler).serve_forever()


if __name__ == "__main__":
    run()
