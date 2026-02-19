from __future__ import annotations

import json
import urllib.error
import urllib.request

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def generate_text(api_key: str, system_prompt: str, user_prompt: str, model: str = "gpt-4o-mini") -> str:
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI HTTP error: {exc.code} {detail}") from exc
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"OpenAI request failed: {exc}") from exc
