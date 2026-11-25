import asyncio
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import settings

from app.services.google_identity import GoogleIdentity

SIGNUP = {"full_name": "Ada Buyer", "email": "ada@example.com", "password": "correct-horse", "confirm_password": "correct-horse"}


async def _signup_and_verify(client, sent_codes, payload=SIGNUP):
    assert (await client.post("/api/v1/auth/signup", json=payload)).status_code == 201
    code = sent_codes[(payload["email"], "email_verification")]
    return await client.post("/api/v1/auth/verify-email", json={"email": payload["email"], "code": code})


async def test_signup_verify_logs_in(client, sent_codes):
    r = await _signup_and_verify(client, sent_codes)
    assert r.status_code == 200
    assert r.json()["account_status"] == "active"
    me = await client.get("/api/v1/auth/user")
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"


async def test_access_token_has_issuer_and_cookie_is_site_wide(client, sent_codes):
    r = await _signup_and_verify(client, sent_codes)
    claims = jwt.get_unverified_claims(client.cookies.get("mk_access"))
    assert claims["iss"] == "marketly-auth"
    assert {"sub", "scope", "iss", "iat", "exp"} <= claims.keys()
    # the access cookie must reach every path (other services read it); the refresh cookie stays narrow
    cookies = {c.split("=", 1)[0]: c for c in r.headers.get_list("set-cookie")}
    assert "Path=/;" in cookies["mk_access"] + ";"
    assert "Path=/api/v1/auth" in cookies["mk_refresh"]


async def test_token_without_or_with_wrong_issuer_is_rejected(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    sub = jwt.get_unverified_claims(client.cookies.get("mk_access"))["sub"]
    for extra in ({}, {"iss": "solver-service"}):
        forged = jwt.encode(
            {"sub": sub, "scope": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **extra},
            settings.TOKEN_SIGNING_KEY,
            algorithm=settings.TOKEN_ALGORITHM,
        )
        client.cookies.set("mk_access", forged, path="/")
        assert (await client.get("/api/v1/auth/user")).status_code == 401


async def test_login_blocked_until_verified(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    r = await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert r.status_code == 403


async def test_duplicate_signup(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert (await client.post("/api/v1/auth/signup", json=SIGNUP)).status_code == 409


async def test_login_and_bad_password(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    client.cookies.clear()
    bad = await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": "wrong-password"})
    assert bad.status_code == 401
    ok = await client.post("/api/v1/auth/login", json={"email": "ADA@example.com", "password": SIGNUP["password"]})
    assert ok.status_code == 200


async def test_wrong_otp_is_rejected_and_limited(client, sent_codes):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    real = sent_codes[(SIGNUP["email"], "email_verification")]
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        r = await client.post("/api/v1/auth/verify-email", json={"email": SIGNUP["email"], "code": wrong})
        assert r.status_code == 400
    # attempt limit burned the code, so even the right one fails now
    r = await client.post("/api/v1/auth/verify-email", json={"email": SIGNUP["email"], "code": real})
    assert r.status_code == 400


async def test_refresh_rotation_and_reuse_detection(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    old = client.cookies.get("mk_refresh")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    new = client.cookies.get("mk_refresh")
    assert new != old
    client.cookies.set("mk_refresh", old, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    token = client.cookies.get("mk_refresh")
    await client.post("/api/v1/auth/logout")
    client.cookies.set("mk_refresh", token, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_forgot_and_reset_password(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    r = await client.post("/api/v1/auth/forgot-password", json={"email": SIGNUP["email"]})
    assert r.status_code == 200
    code = sent_codes[(SIGNUP["email"], "password_reset")]
    body = {"email": SIGNUP["email"], "code": code, "new_password": "brand-new-pass", "confirm_password": "brand-new-pass"}
    assert (await client.post("/api/v1/auth/reset-password", json=body)).status_code == 200
    # old sessions are dead, old password is dead, new one works
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": "brand-new-pass"})).status_code == 200


async def test_reset_password_invalidates_existing_access_token(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    assert (await client.get("/api/v1/auth/user")).status_code == 200
    await asyncio.sleep(1.1)  # JWT "iat" has one-second precision
    await client.post("/api/v1/auth/forgot-password", json={"email": SIGNUP["email"]})
    code = sent_codes[(SIGNUP["email"], "password_reset")]
    body = {"email": SIGNUP["email"], "code": code, "new_password": "brand-new-pass", "confirm_password": "brand-new-pass"}
    assert (await client.post("/api/v1/auth/reset-password", json=body)).status_code == 200
    # the access cookie from before the reset is still unexpired, but must no longer work
    stale = await client.get("/api/v1/auth/user")
    assert stale.status_code == 401 and stale.json()["detail"] == "Session expired. Please log in again."
    # logging in again with the new password gives a token that works immediately
    login = await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": "brand-new-pass"})
    assert login.status_code == 200
    assert (await client.get("/api/v1/auth/user")).status_code == 200


async def test_forgot_password_does_not_reveal_unknown_email(client, sent_codes):
    r = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200 and not sent_codes


def _fake_google(monkeypatch, identity):
    async def fake(_token):
        return identity

    monkeypatch.setattr("app.api.v1.endpoints.auth.verify_google_id_token", fake)


GOOGLE_BODY = {"id_token": "x" * 40}


async def test_google_signup_then_login(client, monkeypatch):
    _fake_google(monkeypatch, GoogleIdentity(sub="g-1", email="gina@example.com", name="Gina", picture=None))
    first = await client.post("/api/v1/auth/google", json=GOOGLE_BODY)
    assert first.status_code == 200 and first.json()["is_new_user"] is True
    second = await client.post("/api/v1/auth/google", json=GOOGLE_BODY)
    assert second.json()["is_new_user"] is False
    assert (await client.get("/api/v1/auth/user")).json()["auth_provider"] == "google"


async def test_google_cannot_password_login(client, monkeypatch):
    _fake_google(monkeypatch, GoogleIdentity(sub="g-1", email="gina@example.com", name="Gina", picture=None))
    await client.post("/api/v1/auth/google", json=GOOGLE_BODY)
    client.cookies.clear()
    r = await client.post("/api/v1/auth/login", json={"email": "gina@example.com", "password": "anything-at-all"})
    assert r.status_code == 401


async def test_google_links_verified_local_account(client, sent_codes, monkeypatch):
    await _signup_and_verify(client, sent_codes)
    client.cookies.clear()
    _fake_google(monkeypatch, GoogleIdentity(sub="g-2", email="ada@example.com", name="Ada", picture=None))
    r = await client.post("/api/v1/auth/google", json=GOOGLE_BODY)
    assert r.json()["is_new_user"] is False
    # password login still works for the linked local account
    assert (await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})).status_code == 200


async def test_google_takeover_of_unverified_signup_drops_password(client, monkeypatch):
    await client.post("/api/v1/auth/signup", json=SIGNUP)  # someone registers the address without owning it
    _fake_google(monkeypatch, GoogleIdentity(sub="g-3", email="ada@example.com", name="Ada", picture=None))
    assert (await client.post("/api/v1/auth/google", json=GOOGLE_BODY)).status_code == 200
    client.cookies.clear()
    r = await client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert r.status_code == 401


async def test_get_user_by_id_returns_public_fields_only(client, sent_codes):
    await _signup_and_verify(client, sent_codes)
    me = (await client.get("/api/v1/auth/user")).json()
    r = await client.get("/api/v1/auth/user", params={"id": me["id"]})
    assert r.status_code == 200
    assert set(r.json()) == {"id", "full_name", "avatar_url"}


async def test_get_user_by_id_requires_login_and_404s_unknown(client, sent_codes):
    import uuid
    other = str(uuid.uuid4())
    assert (await client.get("/api/v1/auth/user", params={"id": other})).status_code == 401
    await _signup_and_verify(client, sent_codes)
    assert (await client.get("/api/v1/auth/user", params={"id": other})).status_code == 404
    assert (await client.get("/api/v1/auth/user", params={"id": "nope"})).status_code == 422
