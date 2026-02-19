from __future__ import annotations

import json
import re

from .models import MatchResult
from .openai_client import generate_text


SYSTEM_PROMPT = (
    "You are an expert job application assistant. Never invent experience. "
    "Use only facts present in candidate profile and uploaded CV corpus. "
    "If a fact is missing, explicitly state 'not provided'."
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _expand_position_terms(text: str) -> set[str]:
    norm = _normalize(text)
    parts = re.split(r"\s*(?:,|/|\|| and |&)\s*", norm)
    out = {p for p in parts if p}
    out.add(norm)
    return out


def extract_keywords(job: dict) -> list[str]:
    source = f"{job.get('position','')} {job.get('description','')} {' '.join(job.get('questions', []))}"
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#-]{2,}", source)
    stop = {"the", "and", "for", "with", "this", "that", "you", "your", "from", "role", "team", "job"}
    uniq: list[str] = []
    for tok in tokens:
        t = tok.lower()
        if t in stop:
            continue
        if t not in [u.lower() for u in uniq]:
            uniq.append(tok)
        if len(uniq) >= 20:
            break
    return uniq


def match_job(profile: dict, job: dict) -> MatchResult:
    if _normalize(job["country"]) not in {_normalize(c) for c in profile["countries"]}:
        return MatchResult(matched=False, reason="Country is outside target list")

    if int(job["salary_usd"]) < int(profile["minimum_salary_usd"]):
        return MatchResult(matched=False, reason="Salary below threshold")

    job_terms = _expand_position_terms(job["position"])
    target_terms: set[str] = set()
    for t in profile["target_positions"]:
        target_terms |= _expand_position_terms(t)

    if not any((jt in target_terms) or (tt in jt) or (jt in tt) for jt in job_terms for tt in target_terms):
        return MatchResult(matched=False, reason="Position not in target roles")

    return MatchResult(matched=True, reason="All criteria satisfied")


def build_cv_knowledge(cvs: list[dict], profile: dict, api_key: str = "") -> str:
    cv_corpus = "\n\n".join(f"[{cv['title']}]\n{cv['content']}" for cv in cvs)
    if api_key:
        prompt = (
            f"Profile facts:\n{profile}\n\n"
            f"Multiple CV corpus:\n{cv_corpus}\n\n"
            "Create a consolidated factual candidate knowledge base. "
            "Do NOT infer unknown achievements. Return concise bullets."
        )
        return generate_text(api_key, SYSTEM_PROMPT, prompt)
    return f"Profile:\n{profile}\n\nCV Corpus:\n{cv_corpus}"


def tailor_cv(base_cv: str, job: dict, profile: dict, cv_knowledge: str, api_key: str = "") -> str:
    keywords = extract_keywords(job)
    if api_key:
        prompt = (
            f"Candidate profile: {profile}\n\n"
            f"Candidate factual knowledge:\n{cv_knowledge}\n\n"
            f"Base CV:\n{base_cv}\n\n"
            f"Job posting:\n{job}\n\n"
            f"ATS keywords to include naturally: {keywords}\n\n"
            "Rewrite CV for this role using ATS-friendly sections and bullets. "
            "Return Markdown with premium clean structure. Facts only."
        )
        return generate_text(api_key, SYSTEM_PROMPT, prompt)

    return (
        f"# {profile['full_name']}\n\n"
        f"## Target Role\n{job['position']}\n\n"
        f"## ATS Keywords\n{', '.join(keywords)}\n\n"
        f"## Experience Highlights\n{profile['career_history']}\n\n"
        f"## Role Alignment\n{job['description']}\n"
    )


def create_cover_letter(job: dict, profile: dict, cv_knowledge: str, api_key: str = "") -> str:
    keywords = extract_keywords(job)
    if api_key:
        prompt = (
            f"Candidate profile: {profile}\n"
            f"Candidate factual knowledge: {cv_knowledge}\n"
            f"Job posting: {job}\n"
            f"ATS keywords: {keywords}\n"
            "Write a cover letter that is NOT a CV repeat. "
            "Map each major requirement to concrete factual evidence from provided data. Facts only."
        )
        return generate_text(api_key, SYSTEM_PROMPT, prompt)

    return (
        f"Dear {job['company']} Hiring Team,\n\n"
        f"I am applying for {job['position']}. Based on my documented background, I can support: {job['description']}\n\n"
        f"ATS focus: {', '.join(keywords)}\n\n"
        f"Best regards,\n{profile['full_name']}"
    )


def auto_answer_questions(questions: list[str], profile: dict, job: dict, cv_knowledge: str, api_key: str = "") -> dict[str, str]:
    answers: dict[str, str] = {}
    for q in questions:
        if api_key:
            prompt = (
                f"Candidate profile: {profile}\n"
                f"Candidate factual knowledge: {cv_knowledge}\n"
                f"Job posting: {job}\n"
                f"Question: {q}\n"
                "Write concise tailored answer (max 120 words), factual only."
            )
            answers[q] = generate_text(api_key, SYSTEM_PROMPT, prompt)
        else:
            answers[q] = (
                f"Based on documented experience ({profile['career_history']}), I can support "
                f"{job['position']} outcomes with relevant project results."
            )
    return answers


def interview_generate_question(job: dict, stage: int, history: list[dict], profile: dict, cv_knowledge: str, api_key: str = "") -> str:
    interviewer = "HR Manager" if stage == 1 else "Unit Manager"
    base = (
        f"You are {interviewer}. Ask one realistic interview question for role {job['position']} at seniority {job.get('seniority','mid')}. "
        "Return only the question sentence."
    )
    if api_key:
        prompt = (
            f"Job: {job}\nProfile: {profile}\nKnowledge: {cv_knowledge}\n"
            f"Previous interview messages: {history}\n{base}"
        )
        return generate_text(api_key, SYSTEM_PROMPT, prompt)
    return "Can you walk me through a project where you delivered measurable impact relevant to this role?"


def interview_score(job: dict, stage: int, history: list[dict], profile: dict, cv_knowledge: str, api_key: str = "") -> dict:
    if api_key:
        prompt = (
            "Evaluate the candidate interview from transcript. Return strict JSON with keys: "
            "position_fit, seniority_fit, culture_fit, english, communication_confidence, overall, recommendation, passed. "
            "Scores should be 0-100. passed true if overall >= 75.\n"
            f"Job:{job}\nProfile:{profile}\nKnowledge:{cv_knowledge}\nHistory:{history}"
        )
        raw = generate_text(api_key, SYSTEM_PROMPT, prompt)
        try:
            j = json.loads(raw)
            return j
        except Exception:
            pass

    return {
        "position_fit": 72,
        "seniority_fit": 70,
        "culture_fit": 68,
        "english": 70,
        "communication_confidence": 65,
        "overall": 69,
        "recommendation": "Improve clarity, add quantified outcomes.",
        "passed": False,
    }
