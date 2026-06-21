"""Caffe Steve — user management & sign-up.

A small, dependency-free account layer for the landing-page sign-up flow:

  landing/onboarding.html --POST /auth/signup--> [users.db]  (account + 5-Q profile)
  landing/signin.html     --POST /auth/login --> {token}
  landing/account.html    --GET  /auth/me    --> {user, profile}

Design choices (deliberately boring so it deploys anywhere with zero new deps):
  * SQLite (stdlib `sqlite3`) at data/users.db — survives restarts, no server.
  * Passwords hashed with PBKDF2-HMAC-SHA256 (stdlib `hashlib`), per-user salt.
  * Opaque bearer tokens (stdlib `secrets`), stored hashed, 30-day expiry.
  * The 5-question data capture (business type, ambiance, …) is stored verbatim
    as a JSON blob on the user row so we never lose what a café told us.

This module owns its own connection-per-call (SQLite is fine for this load) and
exposes plain functions; backend/main.py wires them to FastAPI routes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
# GC_USERS_DB lets deploys/tests relocate the store (e.g. a Railway volume or a
# throwaway temp file) without code changes. Defaults to data/users.db.
DB_PATH = Path(os.environ.get("GC_USERS_DB") or (REPO_ROOT / "data" / "users.db"))

# PBKDF2 parameters. 200k iterations is comfortable for a low-traffic signup form
# and still cheap enough that tests run instantly.
_PBKDF2_ITERS = 200_000
_TOKEN_TTL_S = 30 * 24 * 3600  # 30 days

# Bounds on the captured profile so an unauthenticated signup can't be used to
# exhaust disk/DB (a 50k-key body would otherwise store a ~20 MB row). The real
# onboarding form sends ~12 small keys, so these are generous.
_MAX_PROFILE_KEYS = 40
_MAX_PROFILE_BYTES = 16 * 1024  # serialized JSON

# The canonical set of data-capture questions. Kept here so the backend can
# validate/normalise what the onboarding form sends and the answers stay
# self-describing in storage. Free-text answers are allowed (chips are a UI
# convenience) but must be non-empty strings.
PROFILE_QUESTIONS = (
    "business_type",   # Café / Coffee shop / Restaurant / Bar / Kiosk
    "ambiance",        # Cosy & calm / Buzzy & social / Focused & quiet / Upscale
    "busiest_period",  # Morning rush / Lunch / Afternoon / Evening / All day
    "primary_goal",    # Faster service / More comfort / Higher spend / Quieter
    "room_size",       # approx covers / seats
)


class AuthError(Exception):
    """Raised for any client-correctable auth problem. Carries an HTTP status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


# --------------------------------------------------------------------------- #
# DB plumbing
# --------------------------------------------------------------------------- #
def _db_path() -> Path:
    """Resolve the DB path at call time so tests can repoint it via set_db_path."""
    return DB_PATH


def set_db_path(path: Path | str) -> None:
    """Test hook: point the store at a throwaway DB."""
    global DB_PATH
    DB_PATH = Path(path)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if absent. Idempotent — safe to call on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT NOT NULL UNIQUE,
                name        TEXT NOT NULL,
                venue       TEXT NOT NULL DEFAULT '',
                pw_hash     TEXT NOT NULL,
                pw_salt     TEXT NOT NULL,
                plan        TEXT NOT NULL DEFAULT '',
                profile     TEXT NOT NULL DEFAULT '{}',
                created_at  REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash  TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                created_at  REAL NOT NULL,
                expires_at  REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# Hashing / tokens
# --------------------------------------------------------------------------- #
def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERS
    )
    return dk.hex()


def _new_token() -> tuple[str, str]:
    """Return (clear_token, token_hash). Only the hash is ever stored."""
    clear = secrets.token_urlsafe(32)
    return clear, hashlib.sha256(clear.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _norm_email(email: object) -> str:
    e = str(email or "").strip().lower()
    if not _EMAIL_RE.match(e) or len(e) > 254:
        raise AuthError(422, "A valid email address is required.")
    return e


def _validate_password(pw: object) -> str:
    p = str(pw or "")
    if len(p) < 8:
        raise AuthError(422, "Password must be at least 8 characters.")
    if len(p) > 256:
        raise AuthError(422, "Password is too long.")
    return p


def _clean_profile(profile: object) -> dict:
    """Normalise the 5-question data capture into a flat dict of strings.

    We keep every answer the client sends (forward-compatible) but guarantee the
    five canonical keys exist so downstream tuning never KeyErrors. Values are
    coerced to trimmed strings and length-capped to keep the row sane.
    """
    raw = profile if isinstance(profile, dict) else {}
    if len(raw) > _MAX_PROFILE_KEYS:
        raise AuthError(422, "Too many profile fields.")
    out: dict = {}
    for k, v in raw.items():
        key = str(k)[:64]
        if isinstance(v, (list, tuple)):
            # Preserve list answers (e.g. connected devices) as a list of strings
            # so the frontend can render them as a list, not split a joined blob.
            # Only keep genuine string entries — drop nulls/objects rather than
            # storing their Python repr.
            out[key] = [x.strip()[:200] for x in v if isinstance(x, str) and x.strip()][:50]
        else:
            out[key] = str(v if v is not None else "").strip()[:500]
    for q in PROFILE_QUESTIONS:
        out.setdefault(q, "")
    if len(json.dumps(out)) > _MAX_PROFILE_BYTES:
        raise AuthError(422, "Profile data is too large.")
    return out


def _row_to_user(row: sqlite3.Row) -> dict:
    """Public, safe view of a user row (never leaks pw hash/salt)."""
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "venue": row["venue"],
        "plan": row["plan"],
        "profile": json.loads(row["profile"] or "{}"),
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
def signup(payload: dict) -> dict:
    """Create an account + store the data-capture profile. Returns {token, user}.

    Raises AuthError(409) if the email is already registered.
    """
    email = _norm_email(payload.get("email"))
    password = _validate_password(payload.get("password"))
    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise AuthError(422, "Your name is required.")
    venue = str(payload.get("venue") or "").strip()[:160]
    plan = str(payload.get("plan") or "").strip()[:60]
    profile = _clean_profile(payload.get("profile"))

    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    now = time.time()

    try:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (email, name, venue, pw_hash, pw_salt, plan, profile, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (email, name, venue, pw_hash, salt, plan, json.dumps(profile), now),
            )
            user_id = cur.lastrowid
            token = _issue_session(conn, user_id, now)
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    except sqlite3.IntegrityError:
        # UNIQUE(email) violation — the only integrity constraint that can fire.
        raise AuthError(409, "An account with that email already exists.")

    return {"token": token, "user": _row_to_user(row)}


def login(payload: dict) -> dict:
    """Verify credentials and mint a session. Returns {token, user}.

    Always raises the same 401 for unknown-email and wrong-password so the
    endpoint can't be used to enumerate which emails are registered.
    """
    email = _norm_email(payload.get("email"))
    password = str(payload.get("password") or "")
    now = time.time()

    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        # Always run the KDF (even on unknown email, against a dummy salt) so the
        # response time doesn't reveal whether the email exists.
        salt = row["pw_salt"] if row else "0" * 32
        expected = row["pw_hash"] if row else "0" * 64
        candidate = _hash_password(password, salt)
        if not row or not hmac.compare_digest(candidate, expected):
            raise AuthError(401, "Incorrect email or password.")
        token = _issue_session(conn, row["id"], now)
        conn.commit()
        return {"token": token, "user": _row_to_user(row)}


def _issue_session(conn: sqlite3.Connection, user_id: int, now: float) -> str:
    clear, token_hash = _new_token()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash, user_id, now, now + _TOKEN_TTL_S),
    )
    return clear


def user_for_token(token: Optional[str]) -> dict:
    """Resolve a bearer token to its user, or raise AuthError(401)."""
    if not token:
        raise AuthError(401, "Authentication required.")
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise AuthError(401, "Authentication required.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.time()
    with _connect() as conn:
        sess = conn.execute(
            "SELECT * FROM sessions WHERE token_hash=?", (token_hash,)
        ).fetchone()
        if not sess:
            raise AuthError(401, "Invalid or expired session.")
        if sess["expires_at"] < now:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
            conn.commit()
            raise AuthError(401, "Session expired — please sign in again.")
        row = conn.execute(
            "SELECT * FROM users WHERE id=?", (sess["user_id"],)
        ).fetchone()
        if not row:
            raise AuthError(401, "Account no longer exists.")
        return _row_to_user(row)


def logout(token: Optional[str]) -> None:
    """Revoke a session token. No-op if absent/unknown."""
    if not token:
        return
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        conn.commit()


def list_signups(limit: int = 500) -> list[dict]:
    """Admin view of captured signups (most recent first) for the data capture."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_row_to_user(r) for r in rows]


def stats() -> dict:
    """Aggregate counts for a quick ops/admin overview."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        by_type = conn.execute("SELECT profile FROM users").fetchall()
    counts: dict[str, int] = {}
    for r in by_type:
        bt = (json.loads(r["profile"] or "{}").get("business_type") or "Unknown")
        counts[bt] = counts.get(bt, 0) + 1
    return {"total_users": total, "by_business_type": counts}
