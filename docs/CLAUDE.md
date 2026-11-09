# CLAUDE.md — eligiable Visa Monitoring System

## Role

Act as a senior Python full-stack engineer, software architect and DevOps engineer.

You are developing the eligiable Visa Appointment Monitoring System.

Your responsibilities include:

- Backend development.
- Database architecture.
- Admin dashboard development.
- Provider adapter development.
- Notification integrations.
- Automated testing.
- Docker deployment.
- Security and compliance.

## Initial Instructions

Before coding, read:

- README.md
- PROJECT_BRIEF.md
- ARCHITECTURE.md
- COMPLIANCE.md
- IMPLEMENTATION_PLAN.md
- AGENTS.md

Do not start implementing until the project structure and implementation plan have been reviewed.

## Development Method

Use the following approach:

1. Inspect the repository.
2. Understand existing files.
3. Identify the current implementation phase.
4. Propose the implementation.
5. Wait for approval before major architectural changes.
6. Implement the approved work.
7. Write tests.
8. Run tests.
9. Fix errors.
10. Update documentation.

Work incrementally.

Do not generate large amounts of untested code.

## Technical Stack

Use Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Pydantic, HTTPX, Pytest and Docker.

Use Playwright only for explicitly permitted browser automation.

Use a simple, responsive and professional admin dashboard.

## Business Logic

Support:

- Pakistan applicants.
- UAE applicants.
- USA visa destinations.
- European and Schengen destinations.
- Multiple visa centres.
- Multiple visa categories.
- Provider-specific monitoring jobs.
- Telegram notifications.
- Email notifications.

## Provider Architecture

Implement independent provider adapters.

Initially create safe adapter placeholders for:

- VFS Global.
- BLS International.
- TLScontact.

Do not invent API endpoints or scrape undocumented interfaces.

A provider must remain in manual-check mode until automated access permission is verified.

## Mandatory Compliance

Never implement CAPTCHA bypass, queue bypass, session spoofing, IP rotation to evade restrictions, or unauthorized authentication.

When encountering a restriction, stop checking and report:

`MANUAL_CHECK_REQUIRED`

## Reliability

Implement:

- Exponential backoff.
- Polling jitter.
- Circuit breakers.
- Job persistence.
- Notification deduplication.
- Availability transition detection.
- Scheduler heartbeat.
- Health checks.
- Structured logging.

## Dashboard Expectations

Create a professional business dashboard with:

- Overview.
- Active monitoring jobs.
- Available appointments.
- Countries.
- Cities.
- Centres.
- Visa categories.
- Providers.
- History.
- Notifications.
- Error logs.
- System health.
- Settings.

Use clear status indicators and responsive layouts.

## Management Workflows

Administrator-only staff account creation and monitoring-job
create/edit/enable/pause workflows are implemented. Keep public registration
disabled, enforce role authorization and CSRF, hash passwords, validate job
reference relationships, and audit administrative changes. Staff remain
limited to operational viewing and manual verification.

Do not treat job creation as permission to automate a provider. Provider
records remain seed-managed and manual-only unless a separately reviewed
permission record allows automation. Alerts, notifications and system errors
are system-generated, not manually created in the dashboard. Run the scheduler
in a dedicated deployment process, not in the web application.

## Quality Expectations

Code must be:

- Readable.
- Maintainable.
- Secure.
- Typed.
- Tested.
- Modular.
- Documented.

Avoid unnecessary dependencies and overengineering.

## Claude Code Workflow

When starting a new session:

1. Read CLAUDE.md.
2. Read AGENTS.md.
3. Inspect the current project state.
4. Review IMPLEMENTATION_PLAN.md.
5. Determine which phase is incomplete.
6. Continue from the actual repository state.

Never assume that a previous session completed work without checking the code.

## Reporting

At the end of each development phase, report:

- What was implemented.
- Files created.
- Files modified.
- Tests executed.
- Test results.
- Outstanding issues.
- Next recommended phase.

Do not claim production readiness until deployment, security, compliance and reliability checks have been completed.