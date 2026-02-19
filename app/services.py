from __future__ import annotations

from .models import MatchResult


def match_job(profile: dict, job: dict) -> MatchResult:
    if job["country"] not in profile["countries"]:
        return MatchResult(matched=False, reason="Country is outside target list")
    if job["salary_usd"] < profile["minimum_salary_usd"]:
        return MatchResult(matched=False, reason="Salary below threshold")

    target_positions = [p.lower() for p in profile["target_positions"]]
    if job["position"].lower() not in target_positions:
        return MatchResult(matched=False, reason="Position not in target roles")

    return MatchResult(matched=True, reason="All criteria satisfied")


def tailor_cv(cv: str, job: dict, profile: dict) -> str:
    return (
        f"{cv}\n\n"
        f"--- Tailored Section for {job['position']} at {job['company']} ---\n"
        f"Relevant career highlights from {profile['full_name']}:\n"
        f"{profile['career_history']}\n"
        f"Mapped to job needs: {job['description']}\n"
        "Focus: measurable outcomes, ownership, and cross-functional impact."
    )


def create_cover_letter(job: dict, profile: dict) -> str:
    return (
        f"Dear {job['company']} Hiring Team,\n\n"
        f"I am excited to apply for the {job['position']} role in {job['country']}. "
        f"My background includes: {profile['career_history']}\n\n"
        f"Your posting highlights the need for: {job['description']}\n"
        "I bring a track record of delivering measurable business value and collaborating across teams.\n\n"
        f"Best regards,\n{profile['full_name']}\n{profile['email']}"
    )


def auto_answer_questions(questions: list[str], profile: dict, job: dict) -> dict[str, str]:
    answers: dict[str, str] = {}
    for q in questions:
        answers[q] = (
            f"Based on my experience ({profile['career_history']}), I can support "
            f"{job['position']} outcomes by applying relevant project results and data-driven execution."
        )
    return answers
