"""Provider-agnostic LLM client (plain HTTP, no vendor SDKs).

The LLM is used for exactly three jobs, each a separate, narrow call:
  1. compile_rules     (ingest time)  -> turn policy text into structured rules (JSON)
  2. extract_facts     (question time)-> pull the asker's facts into a typed schema (JSON)
  3. generate_answer   (question time)-> write the grounded natural-language answer
Everything that *decides* (question type, relevance, policy choice, eligibility,
score) is done by System-1 models in app/system1, not here.
"""
import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("llm")

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-5-5",
}


class LLMError(Exception):
    """Raised when the LLM is unavailable or returns something unusable."""


class LLMBusy(LLMError):
    """Provider temporarily overloaded (HTTP 503 / 500) — worth one quick retry."""


# Test hook: when set, fn(system, user, json_mode) -> str replaces real HTTP calls.
_override = None


def set_override(fn) -> None:
    global _override
    _override = fn


def is_enabled() -> bool:
    return _override is not None or settings.llm_enabled


def provider_label() -> str:
    if not is_enabled():
        return "offline (no LLM configured)"
    return f"{settings.LLM_PROVIDER}:{settings.LLM_MODEL or DEFAULT_MODELS.get(settings.LLM_PROVIDER, '?')}"


def complete(system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200) -> str:
    if _override is not None:
        return _override(system, user, json_mode)
    if not is_enabled():
        raise LLMError("No LLM configured.")
    for attempt in range(2):
        try:
            return _call(system, user, json_mode, max_tokens)
        except LLMBusy:
            if attempt == 1:
                raise
            time.sleep(2)  # providers' "high demand" errors usually clear within seconds
    raise LLMError("unreachable")


def _call(system: str, user: str, json_mode: bool, max_tokens: int) -> str:
    provider = settings.LLM_PROVIDER
    model = settings.LLM_MODEL or DEFAULT_MODELS.get(provider, "")
    try:
        with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            if provider == "gemini":
                return _gemini(client, model, system, user, json_mode, max_tokens)
            if provider == "openai":
                return _openai(client, model, system, user, json_mode, max_tokens)
            if provider == "anthropic":
                return _anthropic(client, model, system, user, max_tokens)
    except LLMError:
        raise
    except httpx.TimeoutException as exc:
        raise LLMError("LLM request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'.")


def complete_json(system: str, user: str, max_tokens: int = 1500) -> Any:
    raw = complete(system, user, json_mode=True, max_tokens=max_tokens)
    return parse_json(raw)


def parse_json(raw: str) -> Any:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    raise LLMError("LLM returned invalid JSON.")


# ---------------- providers ----------------
def _check(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        log.warning("LLM HTTP %s: %s", resp.status_code, resp.text[:300])
        if resp.status_code in (401, 403):
            raise LLMError("LLM API key was rejected.")
        if resp.status_code == 429:
            raise LLMError("LLM rate limit or free-tier quota reached.")
        if resp.status_code in (500, 502, 503, 504):
            raise LLMBusy(f"LLM provider is temporarily overloaded (HTTP {resp.status_code}).")
        raise LLMError(f"LLM API returned HTTP {resp.status_code}.")
    return resp.json()


def _gemini(client, model, system, user, json_mode, max_tokens) -> str:
    base = settings.LLM_BASE_URL or "https://generativelanguage.googleapis.com/v1beta"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        # Newer Gemini models "think" before answering and those tokens count against the output
        # budget, so leave generous headroom or the visible answer can come back empty.
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": max(max_tokens, 4096)},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    data = _check(
        client.post(
            f"{base}/models/{model}:generateContent",
            headers={"x-goog-api-key": settings.LLM_API_KEY},
            json=body,
        )
    )
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as exc:
        raise LLMError("LLM returned an empty response (possibly blocked by safety filters).") from exc


def _openai(client, model, system, user, json_mode, max_tokens) -> str:
    base = (settings.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"} if settings.LLM_API_KEY else {}
    data = _check(client.post(f"{base}/chat/completions", headers=headers, json=body))
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        raise LLMError("LLM returned an empty response.") from exc


def _anthropic(client, model, system, user, max_tokens) -> str:
    base = (settings.LLM_BASE_URL or "https://api.anthropic.com").rstrip("/")
    data = _check(
        client.post(
            f"{base}/v1/messages",
            headers={"x-api-key": settings.LLM_API_KEY, "anthropic-version": "2023-06-01"},
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
    )
    return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
