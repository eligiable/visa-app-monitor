SRM Visa Appointment Monitoring System
Project Overview

A cloud-hosted, 24/7 visa appointment availability monitoring platform for SRM Visa & Immigration Consultants.

The system monitors permitted official visa appointment sources and notifies authorized SRM staff when appointment availability changes from unavailable to available.

Business Coverage

Applicant origins

Pakistan
United Arab Emirates (UAE)

Destination coverage

United States of America
Schengen countries
Other European countries supported by official appointment providers

Appointment providers

VFS Global
BLS International
TLScontact
Other officially authorized appointment providers

Provider support must be verified individually. A provider name in the configuration does not imply permission to automate access.

Core Features
Configurable appointment monitoring.
Provider-specific integration adapters.
Manual-check fallback for restricted portals.
Admin dashboard with authentication.
Country, city, centre and visa-category management.
Pakistan and UAE applicant-origin configurations.
Email notifications.
Telegram notifications.
Availability history and change detection.
Error logging and system health monitoring.
Docker-based deployment.
Automated testing.
Technology Stack
Component	Technology
Backend	Python, FastAPI
Database	PostgreSQL
Initial development database	SQLite
ORM	SQLAlchemy
Migrations	Alembic
Scheduler	APScheduler or equivalent
HTTP client	HTTPX
Browser automation	Playwright, only where permitted
Frontend	HTML, CSS, JavaScript
Authentication	Secure session-based authentication
Notifications	SMTP and Telegram Bot API
Logging	Python structured logging
Deployment	Docker, Docker Compose
Testing	Pytest
Project Setup

The coding assistant must implement the application in stages according to IMPLEMENTATION_PLAN.md.

Do not attempt to implement every component in one unreviewed code-generation step.

Required Documentation

Read these files before implementing:

PROJECT_BRIEF.md
ARCHITECTURE.md
COMPLIANCE.md
IMPLEMENTATION_PLAN.md
AGENTS.md

Claude users should also follow CLAUDE.md.

GitHub Copilot users should follow .github/copilot-instructions.md.

Local Development and Admin UI

The project includes a browser-based operations dashboard at the application
root, backed by the authenticated FastAPI admin API. Accounts are provisioned
by an administrator; public registration is disabled. Start the project and
create the first administrator using the steps below.
Open a terminal in the project directory:

```bash
cd ~/srm-visa-monitor
```

Docker Compose (recommended)

Install Docker Engine and the Docker Compose plugin, then configure the
development environment:

```bash
cp .env.example .env
```

Edit `.env` and replace `POSTGRES_PASSWORD` and `SESSION_SECURITY_KEY` with
random secrets. Generate each secret with `openssl rand -hex 32`. Keep `.env`
private and never commit it.

Start the database, run migrations, and start the API:

```bash
docker compose up --build -d
docker compose run --rm web srm-seed-reference-data
docker compose exec web srm-create-admin
```

The administrator command prompts for a username and password. Use a password
of at least 12 characters. The application is available at
`http://localhost:8000`. The port is bound to localhost; do not expose it
directly to the internet. Open the URL in a browser and sign in with the
account you just created. The dashboard includes an overview, job and
availability history, provider status, alerts, notification deliveries,
system errors, and a manual-verification workflow.

Health endpoints are available for service checks:

- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`

You can also check the session and dashboard API with curl:

```bash
curl -i -c /tmp/srm-cookies.txt \
  -H 'Origin: http://localhost:8000' \
  -H 'Content-Type: application/json' \
  -X POST http://localhost:8000/api/auth/login \
  -d '{"username":"YOUR_ADMIN_USERNAME","password":"YOUR_ADMIN_PASSWORD"}'
```

On success, the response contains the username, role, and a `csrf_token`; the
session cookie is saved in `/tmp/srm-cookies.txt`.

```bash
curl -i -b /tmp/srm-cookies.txt http://localhost:8000/api/auth/me
curl -i -b /tmp/srm-cookies.txt http://localhost:8000/api/admin/dashboard/overview
```

The login response sets an HttpOnly cookie, so browser JavaScript cannot read
the session token. The UI uses the cookie and session-bound CSRF token without
exposing either as page content. The FastAPI OpenAPI/Swagger documentation
endpoints are disabled. The dashboard is available to authenticated `ADMIN` and `STAFF` accounts.
`STAFF` accounts can view operational data and record manual verifications;
the separate administrator ping remains administrator-only.

When finished, stop the services while retaining the database volume:

```bash
docker compose down
```

To inspect running services or logs, use `docker compose ps` and
`docker compose logs -f web`. To remove the database and all its data as well,
use `docker compose down -v`.

For local Python development without Docker, use Python 3.12+, install the
development dependencies, and export the required settings (`DATABASE_URL`
and `SESSION_SECURITY_KEY`) into the shell environment. Use a local
PostgreSQL database, or SQLite for development; run `alembic upgrade head`,
`srm-seed-reference-data`, and `srm-create-admin`, then start the server with:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

For plain HTTP local testing, set `PUBLIC_ORIGIN=http://localhost:8000`,
`SESSION_COOKIE_SECURE=false`, and `SESSION_COOKIE_NAME=srm_session`. The app
does not create or migrate tables at startup. For later deployments, apply
schema changes with `docker compose run --rm migrate`.

For remote production access, place a TLS-terminating reverse proxy in front
of the app. Set `PUBLIC_ORIGIN` to the HTTPS site origin,
`SESSION_COOKIE_SECURE=true`, and `SESSION_COOKIE_NAME=__Host-srm_session`.
Use a cloud secret manager where available.

Provider adapters are currently a framework with manual-only placeholders for
VFS Global, BLS International and TLScontact. No live portal requests are
implemented. Automated execution is rejected unless database configuration
enables every relevant provider, centre and job and an active approved
permission record matches the adapter's declared access method and source and
includes reviewed terms, evidence and request limits.

Security
Never commit .env.
Never expose API keys.
Use HTTPS in production.
Require authenticated admin access.
Use secure password hashing.
Apply role-based permissions.
Keep audit logs.
Protect applicant information.
Do not store applicant credentials unless strictly necessary and explicitly authorized.
Compliance

The application must respect official provider terms, robots.txt where applicable, published rate limits, access restrictions and applicable law.

CAPTCHA solving, CAPTCHA bypass, queue bypass, session spoofing, IP rotation to evade restrictions and unauthorized portal access are prohibited.

If automated access is not permitted, the provider must be marked MANUAL_CHECK_REQUIRED.

Deployment

The intended deployment environment is a Linux cloud server hosted on:

AWS
DigitalOcean
Hetzner
Equivalent cloud infrastructure

Docker Compose should support application restart policies, persistent database storage, health checks and log collection.

Project Status

Phases 2–10 are implemented and validated for production-readiness checks:
SQLAlchemy schema and migrations, seed import, FastAPI health endpoints,
administrator login/session/CSRF/role controls, database-backed
authentication throttling, secure initial-admin provisioning, Docker Compose
scaffolding, provider adapter framework with database-backed permission
gating, monitoring engine, availability detection, notification pipeline,
dashboard API and operational health reporting. VFS Global, BLS International
and TLScontact remain manual-only, with no live portal access enabled.

Phase 10 production-readiness verification

The project keeps the operational verification path aligned with the
implementation plan and validates the key production safeguards before release:

- scheduler heartbeat and stale-health detection are covered by unit tests
- database readiness and secure response headers are enforced in the main app
- administrative authentication remains protected by rate limits and session expiry
- provider permissions, manual verification fallback and stop-on-restriction flow
  are covered by the provider and API test suite
- availability transitions, deduplication, cooldown and staff-only alert routing
  are validated in the monitoring and dashboard tests
- notification outbox and delivery-attempt failures remain isolated per channel
  and are retried safely with mock providers

The focused Phase 10 validation command is:

```bash
cd ~/srm-visa-monitor && . .venv/bin/activate && pytest -q \
  tests/unit/test_auth_api.py \
  tests/unit/test_availability_detection.py \
  tests/unit/test_notification_pipeline.py \
  tests/unit/test_dashboard_api.py \
  tests/unit/test_monitoring_engine.py \
  tests/unit/test_monitoring_health.py
```

This verification intentionally avoids live portal access and relies on mocked
or controlled data paths for production-readiness checks.