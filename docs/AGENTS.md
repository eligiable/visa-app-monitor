AGENTS.md — Instructions for AI Coding Agents
Project Identity

You are working on the SRM Visa Appointment Monitoring System.

The project is a Python-based, cloud-hosted appointment monitoring and notification platform for SRM Visa & Immigration Consultants.

Before Writing Code

Read these documents:

README.md
PROJECT_BRIEF.md
ARCHITECTURE.md
COMPLIANCE.md
IMPLEMENTATION_PLAN.md

Treat these files as the project specification.

Primary Objective

Implement the application in phases, producing maintainable, tested and production-oriented code.

Do not generate the entire application in one uncontrolled operation.

Technology Requirements

Prefer:

Python.
FastAPI.
PostgreSQL.
SQLAlchemy.
Alembic.
Pydantic.
HTTPX.
Playwright only where permitted.
APScheduler or equivalent.
Pytest.
Docker.
Docker Compose.

Use a lightweight frontend unless there is a documented reason to introduce a separate frontend framework.

Architecture Rules
Use modular provider adapters.
Separate business logic from API routes.
Keep database operations in repositories or dedicated services.
Keep notification providers interchangeable.
Keep configuration external to application code.
Use dependency injection where appropriate.
Avoid circular imports.
Use asynchronous I/O where beneficial.
Use type hints.
Document public interfaces.
Provider Integration Rules

Every provider must have its own adapter.

Never assume VFS Global, BLS International or TLScontact permits automated appointment scraping.

Before implementing live automation:

Identify the official provider source.
Verify permitted access methods.
Review applicable terms.
Review robots.txt where applicable.
Identify published rate limits.
Record the verification in documentation.
Obtain required authorization.

If permission is absent or unclear, implement a manual-check adapter.

Never fabricate APIs, endpoints or response structures.

Security Rules

Never implement:

CAPTCHA bypass.
CAPTCHA solving.
Queue bypass.
Session spoofing.
Unauthorized authentication.
IP rotation for evading restrictions.
Proxy rotation for evading restrictions.
Anti-bot evasion.
Unauthorized private endpoint access.

Never commit credentials or secrets.

Never log passwords, tokens, cookies or sensitive applicant data.

Monitoring Rules
UNKNOWN is not AVAILABLE.
SOURCE_ERROR is not AVAILABLE.
MANUAL_CHECK_REQUIRED is not AVAILABLE.
Only verified AVAILABLE results can trigger availability alerts.
Alert on transitions, not every successful check.
Apply deduplication and cooldown.
Use bounded retries and exponential backoff.
Respect provider rate limits.
Prevent overlapping checks for the same job.
Stop automated access when a restriction is encountered.
Coding Standards
Follow PEP 8.
Use meaningful variable names.
Use small, focused functions.
Add type annotations.
Handle exceptions explicitly.
Avoid silent failures.
Add docstrings to important public interfaces.
Avoid unnecessary dependencies.
Keep business logic independently testable.
Testing Requirements

For every feature:

Write unit tests.
Add integration tests where appropriate.
Mock external provider interactions.
Test failure scenarios.
Test security restrictions.
Run the relevant test suite.

Do not rely on live visa portals for routine automated testing.

Development Workflow

For every implementation phase:

Inspect existing repository structure.
Identify the phase requirements.
Explain planned changes.
Implement the smallest complete feature set.
Add or update tests.
Run tests.
Fix failures.
Update relevant documentation.
Summarize changed files.
Identify outstanding work.

Do not claim that a feature works unless it has been tested.

Configuration Rules

Support:

Pakistan applicant origin.
UAE applicant origin.
USA destination.
European and Schengen destinations.
Provider-specific configuration.
Editable monitoring settings.

Validate configuration at startup.

Do not place secrets in YAML configuration files.

Deployment Rules

The application must support:

Docker builds.
Docker Compose.
Persistent database storage.
Environment-based secrets.
Health checks.
Restart policies.
Database migrations.
Backup and recovery documentation.
Definition of Done

A feature is complete only when:

Its implementation exists.
Its tests pass.
Its failure cases are handled.
Its security implications are reviewed.
Its documentation is updated.
Final Instruction

Build a reliable, maintainable and compliant business application.

Correctness, provider compliance, security and operational reliability take priority over maximizing the number of automated appointment sources.