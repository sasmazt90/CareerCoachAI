import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.main import run
from app.storage import reset_db

BASE = "http://127.0.0.1:8010"


def api_post(path: str, payload: dict):
    req = Request(f"{BASE}{path}", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_post_form(path: str, payload: dict):
    req = Request(f"{BASE}{path}", data=urlencode(payload, doseq=True).encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def api_get_text(path: str):
    with urlopen(f"{BASE}{path}") as resp:
        return resp.status, resp.read().decode("utf-8")


def api_get_json(path: str):
    with urlopen(f"{BASE}{path}") as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_full_flow_and_interview_pages():
    reset_db()
    thread = threading.Thread(target=run, kwargs={"host": "127.0.0.1", "port": 8010}, daemon=True)
    thread.start()
    time.sleep(0.3)

    s, _ = api_post_form(
        "/profile-form",
        {
            "full_name": "Ada Lovelace",
            "email": "ada@example.com",
            "countries": ["Germany", "Netherlands"],
            "target_positions": "Head of Digital and CRM, Data Scientist",
            "minimum_salary_amount": "90000",
            "preferred_currency": "USD",
            "career_history": "Built predictive models that increased conversion by 23%.",
        },
    )
    assert s == 200

    s, _ = api_post("/cvs", {"title": "General CV", "content": "Python ML CRM Leadership"})
    assert s == 200

    s, _ = api_post(
        "/jobs",
        {
            "company": "Acme AI",
            "position": "Head of CRM",
            "country": "Germany",
            "salary_amount": 100000,
            "salary_currency": "EUR",
            "salary_usd": 108000,
            "description": "Own CRM strategy and lifecycle campaigns.",
            "questions": ["Why this role?"],
            "seniority": "senior",
        },
    )
    assert s == 200

    s, r = api_post("/auto-apply", {})
    assert s == 200
    assert r["applications_created"] == 1

    s, apps = api_get_json("/applications")
    assert s == 200 and len(apps) == 1

    for page in ["/", "/dashboard", "/cover-letters", "/interview", "/settings", "/profile-form", "/jobs/new", "/cvs/upload"]:
        s, t = api_get_text(page)
        assert s == 200
        assert "<html" in t
