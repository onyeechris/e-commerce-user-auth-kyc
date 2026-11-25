from dataclasses import dataclass

import cachecontrol
import requests
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings

# Reuses Google's signing certs between requests instead of downloading them every time.
_transport = google_requests.Request(session=cachecontrol.CacheControl(requests.Session()))


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None


def _verify(token: str) -> dict:
    return id_token.verify_oauth2_token(token, _transport, settings.GOOGLE_OAUTH_CLIENT_ID)


async def verify_google_id_token(token: str) -> GoogleIdentity:
    """Checks signature, expiry, issuer and audience (our client ID) of a Google ID token."""
    try:
        claims = await run_in_threadpool(_verify, token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credential")

    if not claims.get("email") or not claims.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")

    return GoogleIdentity(
        sub=claims["sub"],
        email=claims["email"].lower(),
        name=claims.get("name"),
        picture=claims.get("picture"),
    )
