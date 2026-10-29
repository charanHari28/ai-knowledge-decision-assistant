"""Public (visitor) API. Authenticated only by the assistant token, validated server-side."""
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.security import resolve_assistant_token
from app.services import pipeline

router = APIRouter(prefix="/api", tags=["public"])
log = logging.getLogger("ask")


class AskIn(BaseModel):
    question: str = ""
    token: Optional[str] = None  # may also be sent as X-Assistant-Token header


# --- very small in-memory sliding-window rate limiter (per token + client IP) ---
_hits = defaultdict(deque)
_lock = threading.Lock()


def _rate_limited(key: str) -> bool:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.ASK_RATE_LIMIT_PER_MINUTE:
            return True
        q.append(now)
        return False


def _tenant(token: Optional[str]) -> dict:
    tenant = resolve_assistant_token(token or "")
    if not tenant:
        raise HTTPException(401, "This assistant link is invalid or has been disabled. Please ask the organization for a new link.")
    return tenant


@router.get("/public/assistant")
def public_assistant_info(x_assistant_token: Optional[str] = Header(default=None), token: Optional[str] = None):
    """Minimal public info for the chat widget header. Exposes no documents or account data."""
    t = _tenant(x_assistant_token or token)
    return {"name": t["assistant_name"], "organization": t["org_name"]}


@router.post("/ask")
def ask(body: AskIn, request: Request, x_assistant_token: Optional[str] = Header(default=None)):
    tenant = _tenant(x_assistant_token or body.token)  # 1. organization identification
    client = request.client.host if request.client else "?"
    if _rate_limited(f"{tenant['org_id']}:{client}"):
        raise HTTPException(429, "Too many questions in a short time. Please wait a minute and try again.")
    try:
        result = pipeline.ask(tenant["org_id"], tenant["org_name"], tenant["assistant_name"], body.question)
    except pipeline.PipelineError:
        raise
    except Exception:
        log.exception("ask failed")
        raise HTTPException(500, "Something went wrong while answering. Please try again in a moment.")
    return result
