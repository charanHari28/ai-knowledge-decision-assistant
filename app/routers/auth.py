"""Organization registration, login and logout."""
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.db import get_conn
from app.security import AdminOrg, create_session, delete_session, hash_password, new_assistant_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    org_name: str
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/register", status_code=201)
def register(body: RegisterIn):
    name, email = body.org_name.strip(), body.email.strip().lower()
    if not (2 <= len(name) <= 100):
        raise HTTPException(400, "Organization name must be 2-100 characters.")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO organizations (name, email, password_hash) VALUES (?,?,?)",
                (name, email, hash_password(body.password)),
            )
            org_id = cur.lastrowid
            conn.execute(
                "INSERT INTO assistants (org_id, token, name) VALUES (?,?,?)",
                (org_id, new_assistant_token(), f"{name} Assistant"),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists. Please log in.")
    return {"token": create_session(org_id), "organization": {"id": org_id, "name": name, "email": email}}


@router.post("/login")
def login(body: LoginIn):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, email, password_hash FROM organizations WHERE email = ?", (body.email.strip().lower(),)
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Incorrect email or password.")
    return {"token": create_session(row["id"]), "organization": {"id": row["id"], "name": row["name"], "email": row["email"]}}


@router.post("/logout")
def logout(org_id: int = AdminOrg, authorization: Optional[str] = Header(default=None)):
    delete_session(authorization.split(" ", 1)[1].strip())
    return {"ok": True}


@router.get("/me")
def me(org_id: int = AdminOrg):
    with get_conn() as conn:
        row = conn.execute("SELECT id, name, email, created_at FROM organizations WHERE id = ?", (org_id,)).fetchone()
    return dict(row)
