from __future__ import annotations

from statistics import fmean

from .storage import CURRENCY_RATES_TO_USD, to_usd

BASE_MARKET_USD = {
    "Germany": {"junior": 55000, "mid": 80000, "senior": 105000, "lead": 125000},
    "Netherlands": {"junior": 50000, "mid": 76000, "senior": 98000, "lead": 120000},
    "United Kingdom": {"junior": 52000, "mid": 78000, "senior": 102000, "lead": 125000},
    "United States": {"junior": 90000, "mid": 130000, "senior": 165000, "lead": 195000},
    "United Arab Emirates": {"junior": 48000, "mid": 72000, "senior": 98000, "lead": 120000},
    "Turkey": {"junior": 18000, "mid": 26000, "senior": 39000, "lead": 52000},
}


def _seniority(job: dict) -> str:
    s = (job.get("seniority") or "mid").lower()
    return s if s in {"junior", "mid", "senior", "lead"} else "mid"


def _usd_to_currency(usd: float, currency: str) -> float:
    rate = CURRENCY_RATES_TO_USD.get(currency.upper(), 1.0)
    return usd / rate if rate else usd


def estimate_salary(job: dict, jobs_history: list[dict], target_currency: str = "USD") -> dict:
    country = job.get("country", "Germany")
    seniority = _seniority(job)
    market_base = BASE_MARKET_USD.get(country, BASE_MARKET_USD["Germany"])[seniority]

    # role complexity bump
    role = (job.get("position") or "").lower()
    bump = 1.0
    if "head" in role or "director" in role:
        bump = 1.15
    elif "manager" in role:
        bump = 1.08
    elif "scientist" in role or "engineer" in role:
        bump = 1.05

    market_est_usd = market_base * bump

    company_samples = []
    for j in jobs_history:
        if (j.get("company", "").lower() == job.get("company", "").lower()) and (j.get("country", "").lower() == country.lower()):
            company_samples.append(float(j.get("salary_usd", 0)))

    if company_samples:
        company_policy_usd = fmean(company_samples)
        source = "company_history"
    else:
        company_policy_usd = market_est_usd * 0.97
        source = "market_proxy"

    expected_usd = (company_policy_usd * 0.65) + (market_est_usd * 0.35)
    market_low = market_est_usd * 0.88
    market_high = market_est_usd * 1.12
    diff_pct = ((expected_usd - market_est_usd) / market_est_usd) * 100 if market_est_usd else 0

    return {
        "expected_salary_usd": round(expected_usd, 2),
        "expected_salary": round(_usd_to_currency(expected_usd, target_currency), 2),
        "currency": target_currency,
        "market_range_usd": [round(market_low, 2), round(market_high, 2)],
        "market_range": [round(_usd_to_currency(market_low, target_currency), 2), round(_usd_to_currency(market_high, target_currency), 2)],
        "policy_vs_market_pct": round(diff_pct, 2),
        "evidence_source": source,
        "method": "Internal company history + market benchmark heuristic",
    }
