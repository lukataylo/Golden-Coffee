"""Tests for Golden Coffee user management (backend/auth.py + /auth routes).

Run with pytest:        .venv/bin/python -m pytest backend/test_auth.py -q
Or standalone (no dep): .venv/bin/python backend/test_auth.py

Every test points the store at a throwaway DB so nothing touches data/users.db.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make the repo root importable when run as a bare script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth  # noqa: E402


def _fresh_client(tmp: Path) -> TestClient:
    """A TestClient whose auth store is an empty temp DB."""
    db = tmp / "users.db"
    if db.exists():
        db.unlink()
    auth.set_db_path(db)
    auth.init_db()
    # Import the app AFTER repointing so module-level init_db() is harmless.
    from backend.main import app

    return TestClient(app)


SAMPLE = {
    "email": "Sam@Hearth.co",
    "password": "roastedbeans1",
    "name": "Sam Mara",
    "venue": "Hearth & Co",
    "plan": "autopilot",
    "profile": {
        "business_type": "Café",
        "ambiance": "Cosy & calm",
        "busiest_period": "Morning rush",
        "primary_goal": "Faster service",
        "room_size": "24",
        "extra_note": "corner unit, big windows",
        "devices": ["spotify", "hue"],
    },
}


def test_signup_returns_token_and_captures_profile(tmp_path):
    c = _fresh_client(tmp_path)
    r = c.post("/auth/signup", json=SAMPLE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["token"]
    user = body["user"]
    # email is normalised (lowercased) and password never echoed back
    assert user["email"] == "sam@hearth.co"
    assert "pw_hash" not in user and "password" not in user
    # all five canonical data-capture answers persisted
    prof = user["profile"]
    for q in auth.PROFILE_QUESTIONS:
        assert q in prof, f"missing captured answer: {q}"
    assert prof["ambiance"] == "Cosy & calm"
    assert prof["extra_note"] == "corner unit, big windows"  # extra keys kept
    assert prof["devices"] == ["spotify", "hue"]  # list answers stay lists


def test_duplicate_email_rejected(tmp_path):
    c = _fresh_client(tmp_path)
    assert c.post("/auth/signup", json=SAMPLE).status_code == 200
    # same email, different case -> still a duplicate (case-insensitive)
    dup = {**SAMPLE, "email": "SAM@hearth.CO"}
    r = c.post("/auth/signup", json=dup)
    assert r.status_code == 409, r.text
    assert "already exists" in r.json()["detail"].lower()


def test_signup_validation(tmp_path):
    c = _fresh_client(tmp_path)
    assert c.post("/auth/signup", json={**SAMPLE, "email": "nope"}).status_code == 422
    assert c.post("/auth/signup", json={**SAMPLE, "password": "short"}).status_code == 422
    assert c.post("/auth/signup", json={**SAMPLE, "name": ""}).status_code == 422
    # missing profile is allowed — canonical keys are backfilled empty
    no_profile = {k: v for k, v in SAMPLE.items() if k != "profile"}
    no_profile["email"] = "noprofile@x.co"
    r = c.post("/auth/signup", json=no_profile)
    assert r.status_code == 200, r.text
    assert set(auth.PROFILE_QUESTIONS) <= set(r.json()["user"]["profile"].keys())


def test_profile_size_bounded(tmp_path):
    c = _fresh_client(tmp_path)
    # too many keys -> 422 (DoS guard)
    many = {"email": "big1@x.co", "password": "roastedbeans1", "name": "B",
            "profile": {f"k{i}": "v" for i in range(200)}}
    assert c.post("/auth/signup", json=many).status_code == 422
    # oversized body -> 413 before parsing
    huge = {"email": "big2@x.co", "password": "roastedbeans1", "name": "B",
            "profile": {"blob": "x" * 200_000}}
    assert c.post("/auth/signup", json=huge).status_code == 413
    # null/object list items are dropped, not stored as "None"/repr
    msgy = {"email": "big3@x.co", "password": "roastedbeans1", "name": "B",
            "profile": {"devices": ["spotify", None, {"a": 1}, "  ", "hue"]}}
    r = c.post("/auth/signup", json=msgy)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["profile"]["devices"] == ["spotify", "hue"]


def test_login_success_and_failure(tmp_path):
    c = _fresh_client(tmp_path)
    c.post("/auth/signup", json=SAMPLE)
    # correct creds (email case-insensitive)
    r = c.post("/auth/login", json={"email": "sam@hearth.co", "password": "roastedbeans1"})
    assert r.status_code == 200, r.text
    assert r.json()["token"]
    # wrong password
    bad = c.post("/auth/login", json={"email": "sam@hearth.co", "password": "wrong"})
    assert bad.status_code == 401
    # unknown email -> same 401 (no account enumeration)
    unknown = c.post("/auth/login", json={"email": "ghost@nowhere.co", "password": "whatever12"})
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]


def test_me_requires_valid_token(tmp_path):
    c = _fresh_client(tmp_path)
    token = c.post("/auth/signup", json=SAMPLE).json()["token"]
    # no token
    assert c.get("/auth/me").status_code == 401
    # garbage token
    assert c.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    # valid token (Bearer prefix)
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "sam@hearth.co"
    # valid token (raw, no prefix) also accepted
    assert c.get("/auth/me", headers={"Authorization": token}).status_code == 200


def test_logout_revokes_token(tmp_path):
    c = _fresh_client(tmp_path)
    token = c.post("/auth/signup", json=SAMPLE).json()["token"]
    hdr = {"Authorization": f"Bearer {token}"}
    assert c.get("/auth/me", headers=hdr).status_code == 200
    assert c.post("/auth/logout", headers=hdr).status_code == 200
    assert c.get("/auth/me", headers=hdr).status_code == 401  # revoked


def test_admin_signups_guarded(tmp_path):
    c = _fresh_client(tmp_path)
    c.post("/auth/signup", json=SAMPLE)
    # ADMIN_TOKEN unset -> route hidden (404)
    import backend.main as m
    m.ADMIN_TOKEN = ""
    assert c.get("/admin/signups").status_code == 404
    # with a token set, wrong token -> 401, right token -> 200 with captures
    m.ADMIN_TOKEN = "s3cret"
    assert c.get("/admin/signups").status_code == 401
    r = c.get("/admin/signups", headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 200, r.text
    assert r.json()["stats"]["total_users"] == 1
    assert r.json()["signups"][0]["email"] == "sam@hearth.co"
    m.ADMIN_TOKEN = ""  # reset for any later tests


def test_password_is_hashed_not_stored_plaintext(tmp_path):
    c = _fresh_client(tmp_path)
    c.post("/auth/signup", json=SAMPLE)
    raw = (tmp_path / "users.db").read_bytes()
    assert b"roastedbeans1" not in raw  # plaintext password must never hit disk


# --------------------------------------------------------------------------- #
# Standalone runner (no pytest required)
# --------------------------------------------------------------------------- #
def _run_standalone() -> int:
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        with tempfile.TemporaryDirectory() as d:
            try:
                fn(Path(d))
                print(f"  PASS  {fn.__name__}")
            except Exception:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {fn.__name__}")
                traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
