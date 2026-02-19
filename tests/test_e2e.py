import json
import threading
import time
from urllib.request import Request, urlopen

from app.main import run
from app.storage import reset_db


BASE = "http://127.0.0.1:8010"


def api_post(path: str, payload: dict):
    req = Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_get_json(path: str):
    with urlopen(f"{BASE}{path}") as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_get_text(path: str):
    with urlopen(f"{BASE}{path}") as resp:
        return resp.status, resp.read().decode("utf-8")


def test_full_auto_apply_flow():
    reset_db()
    thread = threading.Thread(target=run, kwargs={"host": "127.0.0.1", "port": 8010}, daemon=True)
    thread.start()
    time.sleep(0.2)

    status, _ = api_post(
        "/profile",
        {
            "full_name": "Ada Lovelace",
            "email": "ada@example.com",
            "countries": ["Germany", "Netherlands"],
            "target_positions": ["Data Scientist", "ML Engineer"],
            "minimum_salary_usd": 90000,
            "career_history": "Built predictive models that increased conversion by 23% and reduced churn by 17%.",
        },
    )
    assert status == 200

    status, _ = api_post(
        "/cvs",
        {
            "title": "General DS CV",
            "content": "Experience in Python, ML, experimentation, analytics, and stakeholder management.",
        },
    )
    assert status == 200

    status, _ = api_post(
        "/jobs",
        {
            "company": "Acme AI",
            "position": "Data Scientist",
            "country": "Germany",
            "salary_usd": 120000,
            "description": "Build recommender systems, define KPIs, and run A/B tests.",
            "questions": ["Why do you want this role?", "Describe your model deployment experience."],
            "seniority": "senior",
        },
    )
    assert status == 200

    status, _ = api_post(
        "/jobs",
        {
            "company": "LowPay Corp",
            "position": "Data Scientist",
            "country": "Germany",
            "salary_usd": 40000,
            "description": "Entry level data support role.",
            "questions": ["Are you okay with low salary?"],
            "seniority": "junior",
        },
    )
    assert status == 200

    status, auto_res = api_post("/auto-apply", {})
    assert status == 200
    assert auto_res["applications_created"] == 1

    status, apps = api_get_json("/applications")
    assert status == 200
    assert len(apps) == 1
    assert apps[0]["company"] == "Acme AI"
    assert "Dear Acme AI Hiring Team" in apps[0]["cover_letter"]

    status, home = api_get_text("/")
    assert status == 200
    assert "CareerCoachAI Hazır" in home

    status, dashboard = api_get_text("/dashboard")
    assert status == 200
    assert "Başvuru Dashboard" in dashboard
    assert "Acme AI" in dashboard
