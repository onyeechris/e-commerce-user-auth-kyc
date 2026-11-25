# Marketly Customer Auth Service

Authentication service for **customers**. Customers have no KYC step: they sign up with email + password (verified by an OTP) or with Google SSO, then log in and get a session. Forgot-password also uses an OTP.

This file is the quick start: **create your `.env`, build the image, run it in Docker on your machine**. The full explanation of every module is in `README.md`.

The steps below were run end to end (build, migrate, run, signup → verify → login → refresh) against a real PostgreSQL container.

## What you need

- Docker (any recent version)
- `openssl` (only to generate a secret; any long random string works)

Google and Resend accounts are **optional for local testing** (see step 1).

---

## 1. Create your `.env`

From the project folder:

```bash
cp .env.example .env
```

Then edit `.env`. Use this table to fill in every line.

**Rule: put comments on their own line.** `docker run --env-file` does not strip inline `# comments`, so `ENVIRONMENT=development # note` would set the value to the whole string.

| Variable | What to put for local Docker | Notes |
|---|---|---|
| `SERVICE_NAME` | `customer-identity-service` | Any name. Shows in the API docs title. |
| `ENVIRONMENT` | `development` | Turns on SQL logging. Never use it in production. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. See "Logging and Loki". |
| `LOG_OTP_CODES` | `True` locally, `False` (default) elsewhere | When `True` **and** `ENVIRONMENT=development` **and** mail is not configured, OTP codes are printed in the container log. Never enable it where logs are shipped to Loki. |
| `POSTGRES_DSN` | `postgresql+asyncpg://user:password@db:5432/app_db` | Format: `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE`. **Must** start with `postgresql+asyncpg://`. The host `db` is the Postgres container from step 2. USER, PASSWORD and DATABASE must match what you give that container. |
| `DB_REQUIRE_SSL` | `False` | `True` only for a managed database that requires SSL. |
| `OTP_TTL_MINUTES` | `10` | How long a code is valid. |
| `OTP_ATTEMPT_LIMIT` | `5` | Wrong guesses before a code is burned. |
| `OTP_RESEND_WAIT_SECONDS` | `60` | Wait before another code is sent. |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Your frontend's URL(s), comma separated, no trailing slash. Browsers can only call the API from these origins. |
| `SESSION_COOKIE_DOMAIN` | *(leave blank)* | Blank = cookie for the exact host only. |
| `SESSION_COOKIE_SECURE` | `False` | **Must be `False` on plain `http://localhost`**, otherwise the browser silently drops the login cookies. Use `True` on HTTPS. |
| `TOKEN_SIGNING_KEY` | output of `openssl rand -hex 32` | Signs login tokens. Anyone with this key can forge logins, so keep it secret. Changing it logs everyone out. |
| `TOKEN_ALGORITHM` | `HS256` | Leave as is. |
| `ACCESS_TTL_MINUTES` | `15` | Access token lifetime. |
| `REFRESH_TTL_DAYS` | `7` | Session lifetime before a fresh login is needed. |
| `GOOGLE_OAUTH_CLIENT_ID` | your Web client ID, or blank | Needed only for "Sign in with Google". Blank is fine: the service starts, and `/auth/google` just returns 401. See "Google sign-in" below. |
| `MAIL_API_KEY` | Resend API key (`re_...`), or blank | Blank is fine locally: the OTP codes are printed in the container log instead of emailed (needs `ENVIRONMENT=development` and `LOG_OTP_CODES=True`). |
| `MAIL_SENDER_EMAIL` | a sender on a domain verified in Resend, or blank | Until you verify a domain, `onboarding@resend.dev` works but only delivers to your own Resend account email. |
| `MAIL_SENDER_NAME` | `Marketly` | Display name on emails. |
| `RATE_LIMIT_ENABLED` | `True` | Keep on. |

Generate the signing key and put it in `.env`:

```bash
openssl rand -hex 32
# copy the output into TOKEN_SIGNING_KEY=...
```

A minimal working local `.env`:

```dotenv
SERVICE_NAME=customer-identity-service
ENVIRONMENT=development
LOG_LEVEL=INFO
LOG_OTP_CODES=True
POSTGRES_DSN=postgresql+asyncpg://user:password@db:5432/app_db
DB_REQUIRE_SSL=False
OTP_TTL_MINUTES=10
OTP_ATTEMPT_LIMIT=5
OTP_RESEND_WAIT_SECONDS=60
ALLOWED_ORIGINS=http://localhost:3000
SESSION_COOKIE_DOMAIN=
SESSION_COOKIE_SECURE=False
TOKEN_SIGNING_KEY=PASTE_THE_openssl_OUTPUT_HERE
TOKEN_ALGORITHM=HS256
ACCESS_TTL_MINUTES=15
REFRESH_TTL_DAYS=7
GOOGLE_OAUTH_CLIENT_ID=
MAIL_API_KEY=
MAIL_SENDER_EMAIL=
MAIL_SENDER_NAME=Marketly
RATE_LIMIT_ENABLED=True
```

`.env` is git-ignored and is **not copied into the image** (`.dockerignore`); you pass it at run time with `--env-file`.

---

## 2. Start PostgreSQL

The service and the database need to reach each other, so put both on one Docker network. The database name and credentials here must match `POSTGRES_DSN`.

```bash
docker network create app-net

docker run -d --name db --network app-net \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=app_db \
  -v customer_pgdata:/var/lib/postgresql/data \
  postgres:16
```

- `--name db` is the hostname the service uses in `POSTGRES_DSN`.
- `-v customer_pgdata:...` keeps your data if the container is removed.
- To use your own password, change `POSTGRES_PASSWORD` here **and** in `POSTGRES_DSN`. Special characters in the password must be URL-encoded in the DSN.

---

## 3. Build the image

```bash
docker build -t auth-service .
```

The first build downloads base images and packages and takes a few minutes; later builds are fast. The result is a small distroless, non-root image (about 200 MB).

---

## 4. Create the database tables (migrations)

The image doesn't run migrations by itself. Run them once, and again after any schema change:

```bash
docker run --rm --network app-net --env-file .env \
  --entrypoint python3 auth-service -m alembic upgrade head
```

You should see `Running upgrade  -> 0001, create users, otps and refresh_tokens tables`.

---

## 5. Run the service

```bash
docker run -d --name auth-service --network app-net \
  --env-file .env -p 8000:8000 --restart unless-stopped \
  auth-service
```

Check it:

```bash
curl http://localhost:8000/health
# {"status":"ok","environment":"development"}
```

Interactive API docs: <http://localhost:8000/docs>

---

## 6. Try it

```bash
B=http://localhost:8000/api/v1/auth
H='Content-Type: application/json'

# sign up
curl -X POST $B/signup -H "$H" \
  -d '{"full_name":"Ada Buyer","email":"ada@example.com","password":"correct-horse","confirm_password":"correct-horse"}'

# the 6-digit code: emailed if Resend is set up, otherwise in the container log
docker logs auth-service 2>&1 | grep "DEV ONLY"   # logs are JSON; the code is in the "message" field

# verify the email; this also logs you in and saves cookies in jar.txt
curl -c jar.txt -X POST $B/verify-email -H "$H" -d '{"email":"ada@example.com","code":"123456"}'

# who am I?
curl -b jar.txt $B/user
```

`123456` is a placeholder; use your code. `-c jar.txt` saves the login cookies and `-b jar.txt` sends them back.

Forgot password works the same way: `POST /forgot-password` with `{"email": ...}`, take the code from the email or log, then `POST /reset-password`.

---

## Google sign-in (optional)

1. Google Cloud Console → **APIs & Services → Credentials → Create credentials → OAuth client ID** → type **Web application**.
2. Add your frontend origin (for example `http://localhost:3000`) under **Authorized JavaScript origins**.
3. Put the client ID in `GOOGLE_OAUTH_CLIENT_ID` in `.env`, then recreate the container (see "Changing settings").
4. Your frontend uses Google Identity Services and posts the returned `credential` to `POST /api/v1/auth/google` as `{"id_token": "..."}` with `credentials: "include"`.

## Real emails with Resend (optional)

Create an API key in the Resend dashboard and put it in `MAIL_API_KEY`. Set `MAIL_SENDER_EMAIL` to an address on a domain you verified in Resend (Domains -> add the DNS records), or `onboarding@resend.dev` for a first test (it only delivers to your own Resend account email). Once both are set, codes are emailed and never printed to the log, whatever `ENVIRONMENT` is.

---

## Everyday commands

```bash
docker logs -f auth-service          # follow logs
docker stop auth-service             # stop
docker start auth-service            # start again
docker restart auth-service

# stop everything (data kept)
docker stop auth-service db
```

**Changing settings.** `.env` is read when the container is created, so a restart is not enough:

```bash
docker rm -f auth-service
# edit .env, then run the step 5 command again
```

**Changing code.**

```bash
docker rm -f auth-service
docker build -t auth-service .
docker run ... # step 5 command; run step 4 first if you changed a model
```

**Full reset (deletes all data).**

```bash
docker rm -f auth-service db
docker volume rm customer_pgdata
docker network rm app-net
```

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Container exits immediately; `docker logs auth-service` shows `ValidationError ... Field required` | A required variable is missing or misspelled in `.env`. Names are case-sensitive; compare with `.env.example`. |
| `could not translate host name "db"` / connection refused | The database isn't running, or the two containers aren't on the same network. Check `docker ps` and that both commands used `--network app-net`. |
| `password authentication failed` | The user/password/database in `POSTGRES_DSN` don't match the ones the Postgres container was **first created** with. Use a full reset, or recreate the user. |
| `relation "users" does not exist` | You skipped step 4 (migrations). |
| Signup works but the login cookie is never stored | `SESSION_COOKIE_SECURE=True` on plain `http://`. Set it to `False` for localhost. |
| Browser shows a CORS error | Your frontend's exact origin (scheme, host and port, no trailing slash) isn't in `ALLOWED_ORIGINS`. The frontend must also send `credentials: "include"`. |
| No email arrives | Resend isn't configured, or the sender domain isn't verified (check the container log for `Mail send failed: 403`). With `ENVIRONMENT=development`, `LOG_OTP_CODES=True` and blank mail settings the code is in `docker logs auth-service`. |
| `429 Too Many Requests` | Rate limit hit (for example 5 signups a minute). Wait a minute. |
| `.env` values look wrong (comment text inside a value) | An inline `# comment` after a value. Put comments on their own line. |
| Port 8000 already in use | Use `-p 8080:8000` and call `http://localhost:8080`. |

---

## API summary

All routes are under `/api/v1/auth`. Sessions are HttpOnly cookies (`mk_access`, `mk_refresh`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/signup` | Create an account, email an OTP |
| POST | `/verify-email` | Submit the OTP, activate the account, log in |
| POST | `/resend-verification-code` | Send a new verification OTP |
| POST | `/login` | Email + password login |
| POST | `/google` | Sign up or log in with a Google ID token |
| POST | `/refresh` | Rotate the refresh token, get a new access token |
| POST | `/logout` | Revoke the refresh token, clear cookies |
| POST | `/forgot-password` | Email a password-reset OTP |
| POST | `/reset-password` | Submit OTP + new password (revokes all sessions) |
| GET | `/user` | Current customer |

## Logging and Loki

The service writes **one JSON object per line to stdout** (never to a file), which is what Promtail / Grafana Alloy expects from a container. Configure it with `LOG_LEVEL` (default `INFO`). Uvicorn's own logs use the same format.

Example request line:

```json
{"timestamp": "2026-10-18T00:05:39+00:00", "level": "INFO", "logger": "app.request", "message": "GET /api/v1/auth/user -> 401", "service": "customer-identity-service", "environment": "production", "request_id": "0b1a95fb...", "method": "GET", "path": "/api/v1/auth/user", "status": 401, "duration_ms": 10.7, "client_ip": "10.0.1.5"}
```

- Every request gets a `request_id` (taken from an incoming `X-Request-ID` header, or generated). It is returned in the `X-Request-ID` response header and added to every log line written while handling that request, including errors with `exception` stack traces.
- `GET /health` is logged at `DEBUG` only, so probes don't flood the logs.
- Uvicorn's access log is turned off; the request line above replaces it.
- To add fields to a log line: `logger.info("msg", extra={"order_id": 5})`.
- Don't log passwords, tokens, OTP codes or full emails.

Code: `app/core/logging.py` (formatter and setup), request middleware in `app/main.py`.

### Shipping to Loki with Promtail

Promtail runs **outside this repo** (for Kubernetes, as a DaemonSet in your deployment repo). It tails the container logs and pushes them to Loki. Minimal config for Kubernetes:

```yaml
server:
  http_listen_port: 9080
positions:
  filename: /run/promtail/positions.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    pipeline_stages:
      - cri: {}                  # use `docker: {}` on Docker-runtime nodes
      - json:
          expressions:
            level: level
            request_id: request_id
      - labels:
          level:                 # low-cardinality only; keep request_id as a field, not a label
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        target_label: app
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_uid, __meta_kubernetes_pod_container_name]
        separator: /
        replacement: /var/log/pods/*$1/*.log
        target_label: __path__
```

For plain Docker, use `docker_sd_configs` (socket `unix:///var/run/docker.sock`) with a `docker: {}` stage instead.

Useful LogQL queries in Grafana:

```logql
{app="auth-service"} | json | level="ERROR"
{app="auth-service"} | json | status >= 500
{app="auth-service"} | json | request_id="0b1a95fb557f4e6a8d650ccf4eadd9a0"
{app="auth-service"} | json | duration_ms > 1000
```

Promtail is deprecated (end of life March 2026); Grafana Alloy (`loki.source.kubernetes` / `loki.source.docker`) is the replacement and works with the same log format.

## Running without Docker (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# in .env use a reachable host in POSTGRES_DSN, e.g. localhost instead of db
alembic upgrade head
uvicorn app.main:app --reload
pytest        # tests need no database or credentials
```

## Production notes

Set `ENVIRONMENT=production`, `SESSION_COOKIE_SECURE=True`, a strong `TOKEN_SIGNING_KEY`, real Resend settings, and `DB_REQUIRE_SSL=True` if your database requires it. Kubernetes and CI files are in `k8s/` and `.github/`; see `README.md` section 13.
