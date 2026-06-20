"""Provider-agnostic LLM helper with automatic fallback.

Order: Claude (ANTHROPIC_API_KEY) → Gemini (GEMINI_API_KEY / GOOGLE_API_KEY) → None.
So the product degrades gracefully: Claude if available, Gemini as the backup,
and the deterministic rule paths if neither key is set. Uses httpx (already a dep)
for Gemini's REST API — no heavy SDK.

Env: ANTHROPIC_API_KEY, AGENT_MODEL (claude model), GEMINI_API_KEY (or GOOGLE_API_KEY),
     GEMINI_MODEL (default gemini-2.0-flash).
"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def provider() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return None


def _claude(system: str, prompt: str, max_tokens: int) -> str | None:
    try:
        from anthropic import Anthropic

        msg = Anthropic().messages.create(
            model=os.environ.get("AGENT_MODEL", "claude-opus-4-8"),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    except Exception as exc:
        print(f"[llm] claude failed ({exc}); trying gemini")
        return None


def _gemini(system: str, prompt: str, max_tokens: int) -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None
    try:
        import httpx

        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        r = httpx.post(
            _GEMINI_URL.format(model=model),
            params={"key": key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
            },
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:
        print(f"[llm] gemini failed ({exc})")
        return None


def complete(system: str, prompt: str, max_tokens: int = 400) -> str | None:
    """Return model text from Claude, else Gemini, else None (caller falls back)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        out = _claude(system, prompt, max_tokens)
        if out is not None:
            return out
    return _gemini(system, prompt, max_tokens)
