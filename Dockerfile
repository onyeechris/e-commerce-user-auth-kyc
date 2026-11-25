# ---- Builder stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

# ---- Runtime stage: distroless ----
FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app

COPY --from=builder /deps /app/deps
COPY --chown=nonroot:nonroot . .

ENV PYTHONPATH=/app/deps \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# --proxy-headers so rate limiting sees the real client IP behind the ingress
ENTRYPOINT ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
