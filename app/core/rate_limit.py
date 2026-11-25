from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Behind the ingress the client IP arrives via X-Forwarded-For; uvicorn runs with --proxy-headers.
limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)
