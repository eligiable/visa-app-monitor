# Implementation Plan

## Development Strategy

Implement the eligiable Visa Monitoring System in controlled phases using the
approved ten-phase sequence below.

Do not skip testing or compliance review to accelerate development.

Every implementation phase must include relevant tests, documentation updates,
and a compliance/security review of the change. The architecture and schema
decisions in Phase 1 are formal prerequisites to application code. Review the
revised documentation and obtain approval before beginning implementation.

Locked architectural decisions:

- Modular monolith; initial deployment is one cloud server.
- PostgreSQL is the runtime database and authoritative source for runtime
  configuration. YAML is for initial seed/import only.
- A dedicated monitoring process uses database-backed job locks or expiring
  leases to prevent duplicate work and allow future multiple workers.
- Provider integrations are manual-only by default and require an active,
  documented, approved permission record before automated execution.
- Notifications use a durable outbox and independent delivery-attempt records.
- Manual verifications are staff-only, persisted with operator identity and
  timestamp, distinct from automated results, and optionally notify internal
  staff with an explicit manual-verification label.
- Secrets are supplied by environment variables or a cloud secret manager.
- Database backups, tested restoration, scheduler heartbeat, and independent
  system-failure alerts are production requirements.

## Phase 1 — Requirements, Architecture and Data Model

### Tasks

- Finalize domain states and transitions, including access mode, execution
  status and appointment availability as separate concepts.
- Finalize initial-AVAILABLE alert policy: disabled by default; configurable
  opt-in only for a verified AVAILABLE result.
- Define manual-verification notification policy and internal staff-only routing.
- Finalize relational schema, foreign keys, uniqueness constraints, indexes,
  retention, deletion behavior and UTC timestamp conventions.
- Define permission-record approval, expiry/review, revocation and evidence
  requirements.
- Define backup, restore, monitoring heartbeat and operational recovery targets.
- Document configuration seeding and database authority.

### Acceptance Criteria

- Architecture, domain model and schema are documented and approved before
  application source code is written.
- Automated access is impossible without an active approved permission record.
- No ambiguous policy remains for initial availability alerts or manual-result
  notifications.

## Phase 2 — Database Schema and Migrations

### Tasks

- Implement SQLAlchemy models and Alembic migrations for reference data,
  providers and permission records, monitoring jobs, check results, availability
  history, manual verifications, administrators/sessions, audit events, alert
  events, notification outbox items, delivery attempts and system errors.
- Implement idempotent YAML seed/import behavior that never silently overwrites
  database-managed changes.
- Add constraints and indexes for job identity, provider approval, job claiming,
  deduplication and history queries.
- Define safe retention and deletion behavior.

### Acceptance Criteria

- Migrations create and upgrade the schema from a clean database.
- Constraints prevent invalid references and duplicate logical records.
- Pakistan and UAE origins and destination configurations can be seeded.
- Invalid configurations produce clear errors without overwriting runtime data.

**Phase status: Implemented.** The schema and initial migration were validated
on SQLite, PostgreSQL migration SQL compiled successfully, and the YAML seed
import and schema tests pass. A live PostgreSQL server was not available for
connection-level validation.

## Phase 3 — FastAPI Foundation and Authentication

### Tasks

- Initialize the Python project and configure FastAPI, Pydantic settings,
  SQLAlchemy, Alembic, structured/redacted logging, Docker, Docker Compose,
  initial health endpoints and Pytest.
- Add environment-variable/cloud-secret-manager configuration.
- Implement secure administrator login.
- Implement logout.
- Implement session management.
- Add CSRF protection.
- Add role-based access.
- Add secure initial administrator provisioning, session expiry, secure headers
  and authentication rate limiting.

### Acceptance Criteria

- Application starts locally and in Docker Compose; database connection and
  health endpoints work.
- Environment secrets are not committed or logged.
- Unauthorized users cannot access protected pages.
- Administrator authentication and session protections are tested.

**Phase status: Implemented.** FastAPI startup, database health endpoints,
administrator provisioning, Argon2id login, opaque sessions, CSRF and
same-origin checks, role authorization, persistent login throttling, security
headers, Docker Compose, and focused tests are in place. Docker runtime image
startup, migrations and authentication were verified; the full Docker Compose
CLI workflow could not be exercised because the Compose plugin is unavailable
in the development environment.

## Phase 4 — Provider Adapter Framework

### Tasks

- Implement BaseProvider.
- Implement provider registry.
- Implement typed result models with separate access, execution and availability
  states.
- Implement provider health checks.
- Implement manual-check adapter.
- Create VFS Global adapter placeholder.
- Create BLS International adapter placeholder.
- Create TLScontact adapter placeholder.
- Add provider-specific configuration.
- Add access-mode validation.

### Important

The initial provider adapters must be non-scraping stubs unless a permitted official integration method has been independently verified.

### Acceptance Criteria

- Every provider has a defined access mode.
- Manual-only sources stop automated checks.
- Automated execution is rejected unless a current approved permission record
  matches the provider and permitted access method.
- Restricted or unverified sources produce MANUAL_CHECK_REQUIRED without
  attempting a request.
- Expected provider-source failures produce SOURCE_ERROR without availability.
- Unexpected responses cannot be normalized as AVAILABLE.

**Status: Implemented.** The typed adapter framework, immutable registry,
database-backed authorization gate, explicit safe diagnostics, manual-check
adapter and VFS Global/BLS International/TLScontact placeholders are in
`app/providers/`. The gate requires enabled automated provider, centre and job
settings plus a current approved permission record with a matching access
method, active administrator, review deadline, HTTPS terms URL, documented
evidence, non-empty request limits and matching source origin. All three
initial adapters remain manual-only and perform no network access. Expected
typed provider errors are isolated as `SOURCE_ERROR`; unanticipated exceptions
remain visible for monitoring-worker supervision in Phase 5. No schema
migration or new runtime dependency was needed.

An adapter-reported access restriction or unexpected source content switches
the provider back to `MANUAL_CHECK_REQUIRED` and writes a safe audit event in
the caller-owned transaction, preventing subsequent adapter execution after
that transaction commits.

Focused provider-framework tests cover the access policy, result validation,
permission expiry/revocation/mismatch, manual fallback, health status and
explicit source failures.

## Phase 5 — Monitoring Engine

### Tasks

- Implement a dedicated monitoring process and scheduler, separate from the
  FastAPI web process.
- Implement job registration.
- Implement job pause and resume.
- Implement polling intervals.
- Implement jitter.
- Implement concurrency limits.
- Implement retry policy.
- Implement exponential backoff.
- Implement circuit breakers.
- Prevent overlapping checks using database-backed locks or expiring leases.
- Recover abandoned jobs after worker/process failure.
- Persist check results.
- Publish a monitoring-process heartbeat.

### Acceptance Criteria

- Jobs execute at configured intervals.
- Disabled jobs do not execute.
- Restricted providers and jobs without active permission do not execute
  automated checks.
- Errors do not crash unrelated jobs.
- Job state survives application restart.
- Concurrent workers cannot execute the same job simultaneously.

## Phase 6 — Availability Detection

### Tasks

- Implement normalized status handling.
- Implement transition detection.
- Implement availability history.
- Implement alert deduplication.
- Implement cooldown.
- Implement unknown-state handling.
- Implement verified-result provenance and the configurable initial-AVAILABLE
  policy, disabled by default.
- Support internal staff notifications from manual verification only when
  configured, with explicit manual-verification labeling.

### Acceptance Criteria

- UNAVAILABLE to AVAILABLE creates an alert.
- AVAILABLE to AVAILABLE does not create a duplicate alert.
- UNKNOWN never creates an availability alert.
- SOURCE_ERROR never creates an availability alert.
- MANUAL_CHECK_REQUIRED and DISABLED never create automated availability alerts.
- Initial AVAILABLE creates no alert unless the explicit verified-result policy
  is enabled.
- Manual verification notifications, when enabled, are labeled and staff-only.
- History is persisted.

## Phase 7 — Notification Pipeline

### Tasks

- Implement Telegram Bot API integration.
- Implement SMTP email integration.
- Implement notification templates.
- Implement recipient configuration.
- Implement delivery history.
- Implement notification outbox.
- Implement independent delivery-attempt records and bounded idempotent retries.
- Implement notification failure alerts.

### Acceptance Criteria

- Telegram test notification works.
- Email test notification works.
- Alert includes all required appointment details.
- Duplicate alerts are suppressed.
- Delivery failures are recorded.
- Failed notifications can be retried safely.
- One channel/recipient failure does not erase the logical alert or other
  delivery outcomes.

## Phase 8 — Dashboard Monitoring Views

### Tasks

- Add administrator-only staff-account creation and listing; keep public
  registration disabled and hash passwords with the existing password helper.
- Add administrator-only monitoring-job creation, editing and enable/pause
  controls, with CSRF protection, audit records and validation of related
  reference records.
- Keep seeded providers manual-only by default; job management must not grant
  provider permission or weaken the provider access gate.
- Keep alerts, notification records and system errors generated by application
  activity rather than manually authored dashboard records.
- Add current availability table.
- Add status filters.
- Add job history.
- Add availability history.
- Add notification history.
- Add provider health.
- Add error logs.
- Add manual-check workflow.
- Add system health indicators.
- Add permission-record review and revocation visibility.
- Record manual verification with operator, timestamp, official URL, status and
  optional internal notes.

### Acceptance Criteria

- Staff can see which jobs are active.
- Staff can identify manual-check sources.
- Staff can view historical checks.
- Staff can inspect notification failures.
- Administrators can start and stop permitted jobs; staff cannot change job
  configuration.
- Staff can distinguish automated results from manual verification and identify
  why automated access is disabled.
- Administrators can create staff accounts and configure jobs; staff cannot
  perform these administrative actions.

### Management workflow implementation status

The planned management workflow is implemented:

- Administrator-only staff account listing and creation, with hashed passwords,
  validation, audit events, role checks and CSRF protection.
- Administrator-only job creation, editing, enablement and pause controls,
  with validated reference relationships and safe source URL checks.
- Dashboard forms with role-aware staff and job management controls.
- A dedicated Docker scheduler service, separate from the web service. Its
  default provider registry remains manual-only and cannot bypass permission
  checks.
- Tests covering account provisioning, job validation, staff/admin
  authorization, permission-gate preservation and worker persistence.

The reference-data seed remains responsible for provider records; job
management does not create providers or approve automation. Alerts,
notifications, and system errors remain generated by application activity.
The full test suite currently passes (67 tests). Production heartbeat
monitoring and independent failure alerting remain outstanding under Phase 9.

Provider creation/editing, permission approval, manual creation of alerts or
notifications, and direct system-error entry are outside this update's scope.

## Phase 9 — Deployment, Reliability and Security

### Tasks

- Add database health checks.
- Add per-provider circuit breakers.
- Add bounded retries.
- Add structured error reporting.
- Add secure headers.
- Add session expiry.
- Add rate limiting to administrative authentication.
- Add audit logs.
- Review secrets handling.
- Review dependency vulnerabilities.
- Prepare production Docker Compose with PostgreSQL persistence, HTTPS reverse
  proxy, container restart policies and log handling.
- Configure protected database backups, retention, documented recovery
  objectives and restoration testing.
- Configure external uptime/heartbeat monitoring and an independent
  system-failure notification path.

### Acceptance Criteria

- Missing scheduler heartbeat and database/service failures are detected by a
  path independent of the failed process.
- Application recovery works.
- Administrative endpoints are protected.
- Backups can be restored using the documented procedure.
- Secrets are externalized and logs redact credentials and sensitive data.

## Phase 10 — Production-Readiness Verification

### Tasks

- Run and complete targeted unit, integration, API, database migration,
  container-startup and recovery tests accumulated across all phases.
- Verify provider permissions, rate limits, manual fallbacks and stop-on-
  restriction behavior.
- Verify authentication, authorization, audit trail and secrets handling.
- Verify alert transitions, initial-AVAILABLE policy, cooldown, deduplication,
  manual-result labels and staff-only routing.
- Verify Telegram and email delivery, independent attempts, failure recording
  and safe retries using mocks or controlled test endpoints.
- Perform a backup restoration exercise and verify scheduler heartbeat and
  independent operational alerts.
- Complete operational documentation and security/compliance review.

### Acceptance Criteria

- All relevant tests pass; no routine test requires live portal access.
- Integration tests use mocked or recorded responses.
- Production readiness is documented and reviewed.
- No live provider adapter is enabled until its access permission has been
  reviewed, approved and recorded as current.

## AI Development Rules

The coding assistant must:

- Complete one phase at a time.
- Explain the implementation before major architectural changes.
- Avoid overwriting working code without reason.
- Write tests alongside functionality.
- Run tests before declaring a phase complete.
- Update documentation when implementation changes.
- Avoid hardcoded credentials.
- Never fabricate provider API endpoints.
- Never assume a provider permits automated access.
- Ask for approval before introducing paid external services or changing the
  architecture.

## Final Deliverable

A tested, documented, Docker-deployable application with a secure dashboard,
configurable monitoring, compliant provider adapters, and reliable
notification delivery.