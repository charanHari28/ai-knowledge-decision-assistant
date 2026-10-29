"""Password hashing, admin sessions and assistant tokens.

Two completely separate credentials exist:
  * Admin session token  -> Authorization: Bearer <token>; grants dashboard/admin APIs.
  * Assistant token      -> public, embedded in the assistant URL; grants ONLY /api/ask
                            for its own organization.
They live in different tables, so an assistant token can never authenticate an admin call.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import settings
from app.db import get_conn

PBKDF2_ITERATIONS = 200_000


# ---------- passwords ----------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except ValueError:
        return False


# ---------- admin sessions ----------
def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_session(org_id: int) -> str:
    token = "sess_" + secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.SESSION_TTL_HOURS)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, org_id, expires_at) VALUES (?, ?, ?)",
            (_sha256(token), org_id, expires.isoformat()),
        )
    return token


def delete_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha256(token),))


def current_org_id(authorization: Optional[str] = Header(default=None)) -> int:
    """FastAPI dependency: resolves the admin session to an org_id or raises 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required.")
    token = authorization.split(" ", 1)[1].strip()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT org_id, expires_at FROM sessions WHERE token_hash = ?", (_sha256(token),)
        ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session. Please log in again.")
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        delete_session(token)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please log in again.")
    return int(row["org_id"])


AdminOrg = Depends(current_org_id)


# ---------- assistant tokens ----------
def new_assistant_token() -> str:
    # 192 bits of randomness; contains nothing derived from the org, its users or its documents.
    return "ast_" + secrets.token_urlsafe(24)


def resolve_assistant_token(token: str) -> Optional[dict]:
    """Server-side validation of the public assistant token -> {org_id, org_name, assistant_name}."""
    if not token or not token.startswith("ast_") or len(token) > 100:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """SELECT a.org_id, a.name AS assistant_name, o.name AS org_name
               FROM assistants a JOIN organizations o ON o.id = a.org_id
               WHERE a.token = ?""",
            (token,),
        ).fetchone()
    return dict(row) if row else None
