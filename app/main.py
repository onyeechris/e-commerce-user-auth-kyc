import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import request_id_var, setup_logging
from app.core.exception import unhandled_exception_handler, validation_exception_handler
from app.core.rate_limit import limiter

setup_logging()
logger = logging.getLogger("app.request")

app = FastAPI(title=settings.SERVICE_NAME)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    # /health is polled constantly by probes; keep it out of INFO.
    level = logging.DEBUG if request.url.path == "/health" else logging.INFO
    try:
        response = await call_next(request)
    except Exception:
        logger.error(
            "%s %s -> 500", request.method, request.url.path,
            extra={"method": request.method, "path": request.url.path, "status": 500,
                   "duration_ms": round((time.perf_counter() - start) * 1000, 1)},
        )
        raise
    else:
        response.headers["X-Request-ID"] = request_id
        logger.log(
            level, "%s %s -> %s", request.method, request.url.path, response.status_code,
            extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                   "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                   "client_ip": request.client.host if request.client else None},
        )
        return response
    finally:
        request_id_var.reset(token)


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router, prefix="/api/v1")

# Health check
@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
