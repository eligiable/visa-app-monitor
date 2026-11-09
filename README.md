# Visa Appointment Monitoring System

## Overview

A visa appointment availability monitoring and staff notification platform for
eligiable Visa & Immigration Consultants. The system monitors permitted official
appointment sources and notifies authorized staff when verified availability
changes from unavailable to available.

## Coverage

- **Applicant origins:** Pakistan and the United Arab Emirates (UAE)
- **Destinations:** United States, Schengen countries, and other countries
  supported by official appointment providers
- **Providers:** VFS Global, BLS International, TLScontact, and other
  officially supported providers

Provider support must be verified individually. A provider name in
configuration does not grant permission to automate access.

## Features

- Configurable appointment monitoring and provider adapters
- Manual-check fallback for restricted or unverified provider access
- Authenticated browser operations dashboard and admin API
- Country, city, visa-centre, and visa-category reference data
- Availability history, transition detection, and deduplicated alerts
- Telegram and SMTP email notification pipeline
- Operational error and system-health reporting
- Docker-based deployment and automated tests

## Technology

| Component | Technology |
| --- | --- |
| Backend | Python, FastAPI |
| Database | PostgreSQL (SQLite for development and tests) |
| ORM and migrations | SQLAlchemy, Alembic |
| HTTP client | HTTPX |
| Frontend | HTML, CSS, JavaScript |
| Authentication | Secure session-based authentication |
| Notifications | SMTP and Telegram Bot API |
| Deployment | Docker, Docker Compose |
| Testing | Pytest |

## Start the Application

### Requirements

- Docker Engine and Docker Compose (the `docker compose` plugin or standalone
  `docker-compose`)
- `curl` for optional API checks

### Configure secrets

From the project directory:

```bash
cd ~/eligiable-visa-monitor
```

Copy the example environment file and generate unique secrets:

```bash
cp .env.example .env
openssl rand -hex 32
```

Edit `.env` and set `POSTGRES_PASSWORD` and `SESSION_SECURITY_KEY` to
independently generated random values. Keep `.env` private and never commit it.

The project branding, package name, and CLI commands use `eligiable`. When
upgrading an existing Docker deployment, keep its current `POSTGRES_DB` and
`POSTGRES_USER` values in `.env` so the existing database volume remains
accessible. Rebuild the images before using the renamed
`eligiable-seed-reference-data`, `eligiable-create-admin`, and
`eligiable-monitor-worker` commands.

### Start services and create the first account

For Docker setup, a Python virtual environment on the host is not required.
Build the application and migration images from the current project files, then
start the services:

```bash
docker-compose build web migrate scheduler
docker-compose up -d
```

If your installation provides the Compose plugin instead of the standalone
command, use `docker compose` in place of `docker-compose` in the commands
below.

Load the initial reference data:

```bash
docker-compose run --rm web eligiable-seed-reference-data \
  --file /app/configs/seed.yaml
```

After seeding completes successfully, create an administrator:

```bash
docker-compose exec web eligiable-create-admin
```

The administrator command prompts for a username and password. Use a password
of at least 12 characters. Open **http://localhost:8000** in a browser and sign
in with the account you created. The app is bound to localhost; do not expose it
directly to the internet.

For domain access, point your domain to the server and configure an HTTPS
reverse proxy to forward requests to the app on port 8000. Set these values in
`.env`, replacing the example domain with the exact public URL users will visit:

```env
PUBLIC_ORIGIN=https://appointments.example.com
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_NAME=__Host-eligiable_session
```

`PUBLIC_ORIGIN` must match the browser URL's scheme, hostname and port. After
changing `.env`, apply the settings by recreating the web service:

```bash
docker-compose up -d --force-recreate web
```

Users should then sign in through the configured HTTPS domain. Keep the app
behind the HTTPS reverse proxy; do not expose port 8000 directly to the
internet.

The dashboard provides an overview, monitoring jobs and availability history,
provider status, alerts, notification deliveries, system errors, and a
manual-verification workflow. Sign-in requires an existing `ADMIN` or `STAFF`
account; public registration is disabled.

### Staff and monitoring-job administration

Administrators can use **Staff Management** to create staff accounts. Staff
accounts cannot create other accounts or manage jobs. Public registration is
disabled, and the administrator must provide a password of at least 12
characters.

Administrators can use **Monitoring Jobs** to create jobs, edit their settings,
and enable or pause them. New jobs are disabled by default. Choose the origin,
destination, and seeded provider, then enter the city, centre, category,
appointment type, official HTTPS source URL, and polling interval (at least
300 seconds). A new city, centre, or category is added to the reference data
when needed. The source URL must match the selected centre's official origin.
The Docker deployment runs the monitoring worker separately from the web
application.

Providers remain sourced from the reference-data seed and manual-only by
default. Enabling a job does not grant permission for automated provider
access; the worker continues to require the existing provider permission gate.
The initial VFS Global, BLS International, and TLScontact records require
manual checks and do not make live portal requests. Staff can record manual
verifications. Alerts and notification deliveries are generated by monitoring
and delivery activity, and system errors are generated by application
failures; these records are not manually created in the dashboard.

### Health and API checks

Health endpoints:

- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`

To check login and the dashboard API with `curl`:

```bash
curl -i -c /tmp/eligiable-cookies.txt \
  -H 'Origin: http://localhost:8000' \
  -H 'Content-Type: application/json' \
  -X POST http://localhost:8000/api/auth/login \
  -d '{"username":"YOUR_ADMIN_USERNAME","password":"YOUR_ADMIN_PASSWORD"}'
```

On success, the response contains the username, role, and a `csrf_token`; the
session cookie is saved in `/tmp/eligiable-cookies.txt`.

```bash
curl -i -b /tmp/eligiable-cookies.txt http://localhost:8000/api/auth/me
curl -i -b /tmp/eligiable-cookies.txt http://localhost:8000/api/admin/dashboard/overview
```

The login response sets an HttpOnly cookie. The browser UI uses this cookie and
the session-bound CSRF token without exposing the session token to JavaScript.
FastAPI OpenAPI/Swagger endpoints are disabled. `STAFF` accounts can view
operational data and record manual verifications; the administrator ping
endpoint remains administrator-only.

### Stop and inspect

Stop services while keeping the database volume:

```bash
docker-compose down
```

Inspect service status and web logs with `docker-compose ps` and
`docker-compose logs -f web`. To also delete the database volume and its data,
run `docker-compose down -v`.

## Local Python Development

Use Python 3.12+ and a running PostgreSQL instance or SQLite. Create and
activate a virtual environment, then install the project and development
dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Export the runtime settings in the same shell. For SQLite local development:

```bash
export DATABASE_URL='sqlite:///./dev.db'
export SESSION_SECURITY_KEY="$(openssl rand -hex 32)"
export PUBLIC_ORIGIN='http://localhost:8000'
export SESSION_COOKIE_NAME='eligiable_session'
export SESSION_COOKIE_SECURE='false'
```

Apply migrations, load reference data, provision an administrator, and start
the server:

```bash
alembic upgrade head
eligiable-seed-reference-data
eligiable-create-admin
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The app does not create or migrate tables at startup. For later Docker
deployments, apply schema changes with `docker-compose run --rm migrate`.

Use a cloud secret manager for production secrets where available.

## Provider Access and Compliance

Provider adapters are currently a framework with manual-only placeholders for
VFS Global, BLS International and TLScontact. No live portal requests are
implemented. Automated execution is rejected unless database configuration
enables every relevant provider, centre and job and an active approved
permission record matches the adapter's declared access method and source and
includes reviewed terms, evidence and request limits.

The application must respect official provider terms, applicable robots.txt
directives, published rate limits, access restrictions, and applicable law.
CAPTCHA solving or bypass, queue bypass, session spoofing, IP rotation to evade
restrictions, and unauthorized portal access are prohibited. Sources without
verified permission must remain manual-check-only.

## Security

- Never commit `.env` or expose API keys and credentials.
- Use HTTPS for production access.
- Require authenticated access and role-based permissions.
- Use secure password hashing and keep audit logs.
- Protect applicant information; do not store applicant credentials unless
  strictly necessary and explicitly authorized.

## Deployment

The intended deployment environment is Linux cloud infrastructure (for example
AWS, DigitalOcean, Hetzner, or an equivalent provider). Docker Compose
configures PostgreSQL persistence, restart policies, container health checks,
and application startup dependencies. Put the web service behind a
TLS-terminating reverse proxy before remote access.

## Project Status

Phases 2–10 are implemented and validated for production-readiness checks:
SQLAlchemy schema and migrations, seed import, FastAPI health endpoints,
administrator login/session/CSRF/role controls, database-backed
authentication throttling, secure initial-admin provisioning, Docker Compose
scaffolding, provider adapter framework with database-backed permission
gating, monitoring engine, availability detection, notification pipeline,
dashboard API and operational health reporting. VFS Global, BLS International
and TLScontact remain manual-only, with no live portal access enabled.

## Phase 10 Verification

The project keeps the operational verification path aligned with the
implementation plan and validates the key production safeguards before
release:

- Scheduler heartbeat and stale-health detection are covered by unit tests.
- Database readiness and secure response headers are enforced in the main app.
- Administrative authentication remains protected by rate limits and session
  expiry.
- Provider permissions, manual verification fallback, and stop-on-restriction
  flow are covered by the provider and API test suite.
- Availability transitions, deduplication, cooldown, and staff-only alert
  routing are validated in the monitoring and dashboard tests.
- Notification outbox and delivery-attempt failures remain isolated per
  channel and are retried safely with mock providers.

Run the focused verification suite:

```bash
cd ~/eligiable-visa-monitor && . .venv/bin/activate && pytest -q \
  tests/unit/test_auth_api.py \
  tests/unit/test_availability_detection.py \
  tests/unit/test_notification_pipeline.py \
  tests/unit/test_dashboard_api.py \
  tests/unit/test_monitoring_engine.py \
  tests/unit/test_monitoring_health.py
```

This verification intentionally avoids live portal access and relies on mocked
or controlled data paths for production-readiness checks.
