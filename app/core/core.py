from fastapi import Response

from app.core.config import settings

ACCESS_COOKIE = "mk_access"
REFRESH_COOKIE = "mk_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _domain() -> str | None:
    return settings.SESSION_COOKIE_DOMAIN or None


def _set_session_cookie(response: Response, key: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        domain=_domain(),
        path=path,
    )


def set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    _set_session_cookie(response, ACCESS_COOKIE, access_token, settings.ACCESS_TTL_MINUTES * 60, "/")
    _set_session_cookie(response, REFRESH_COOKIE, refresh_token, settings.REFRESH_TTL_DAYS * 24 * 60 * 60, REFRESH_COOKIE_PATH)


def clear_session_cookies(response: Response) -> None:
    _set_session_cookie(response, ACCESS_COOKIE, "", 0, "/")
    _set_session_cookie(response, REFRESH_COOKIE, "", 0, REFRESH_COOKIE_PATH)
