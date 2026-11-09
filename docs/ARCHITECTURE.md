# System Architecture

## 1. Architecture Principles

Build a modular monolithic application initially.

Avoid unnecessary microservices during the first release.

The initial deployment is a single cloud server using PostgreSQL. Runtime
configuration is stored in the database; YAML files are seed/import inputs and
are not a second runtime source of truth. Secrets are supplied through
environment variables or a cloud secret manager, never YAML.

Run the monitoring scheduler as a dedicated process, separate from the FastAPI
web process. The scheduler must coordinate job claims and execution using
database-backed locks or leases with expiry and ownership. This prevents
duplicate checks and permits abandoned work to be recovered and additional
workers to be introduced later. Keep the initial deployment simple; do not
introduce a message broker unless a measured requirement justifies it.

Separate the following responsibilities:

- Web dashboard.
- Authentication.
- Configuration management.
- Monitoring scheduler.
- Provider adapters.
- Availability detection.
- Notification delivery.
- Database persistence.
- Health monitoring.

The architecture must permit individual components to be extracted into separate services later.

## 2. Proposed Directory Structure

```text
eligiable-Visa-Monitor/
│
├── app/
│   ├── main.py
│   ├── config.py
│   ├── configuration/
│   │   └── seeds.py
│   │
│   ├── auth/
│   │   ├── router.py
│   │   ├── dependencies.py
│   │   ├── security.py
│   │   └── command.py
│   │
│   ├── api/
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── countries.py
│   │   ├── centres.py
│   │   ├── jobs.py
│   │   ├── history.py
│   │   └── health.py
│   │
│   ├── core/
│   │   ├── security.py
│   │   ├── logging.py
│   │   ├── scheduler.py
│   │   ├── change_detection.py
│   │   ├── circuit_breaker.py
│   │   └── retry.py
│   │
│   ├── database/
│   │   ├── session.py
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   ├── providers/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── models.py
│   │   ├── service.py
│   │   ├── errors.py
│   │   └── adapters/
│   │       ├── vfs_global.py
│   │       ├── bls_international.py
│   │       ├── tlscontact.py
│   │       └── manual_check.py
│   │
│   ├── monitoring/
│   │   ├── engine.py
│   │   ├── worker.py
│   │   └── health_monitor.py
│   │
│   ├── notifications/
│   │   ├── base.py
│   │   ├── telegram.py
│   │   ├── email.py
│   │   └── dispatcher.py
│   │
│   ├── services/
│   │   ├── job_service.py
│   │   ├── availability_service.py
│   │   └── configuration_service.py
│   │
│   ├── templates/
│   └── static/
│
├── configs/
│   └── seed.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── notifications/
│   └── fixtures/
│
├── migrations/
│   └── versions/
│       ├── 90b3f2469e7f_initial_schema.py
│       └── 2a17c948e5d0_auth_sessions_and_rate_limits.py
├── scripts/
├── docs/
│
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── pytest.ini
├── README.md
├── PROJECT_BRIEF.md
├── ARCHITECTURE.md
├── COMPLIANCE.md
├── IMPLEMENTATION_PLAN.md
├── AGENTS.md
└── CLAUDE.md
```

## 3. Database Design

Use SQLAlchemy models and Alembic migrations.

The initial SQLAlchemy schema and Alembic migration implement the entities and
constraints below. Integer primary keys and timezone-aware UTC timestamps are
used. Foreign keys use RESTRICT semantics; reference records are disabled
rather than hard-deleted so operational history remains intact. No automatic
history purge is implemented; retention durations and archival must be
approved before production.

Unique constraints protect stable country, origin, provider and category codes,
city names within a country, centre names within a city/provider, and the
logical monitoring-job dimensions. Composite foreign keys ensure a job's city
matches its destination and its centre matches the job's city/provider.
Indexes cover due-job claiming, lease expiry, check/history timelines,
permission review, outbox delivery, and audit/error timelines.

Runtime configuration records in the database are authoritative. Seed imports
are validated, idempotent, and never overwrite existing records. Import the
initial origins, destinations and manual-only provider records with
`eligiable-seed-reference-data`; set `DATABASE_URL` and run Alembic migrations first.

### Country

Fields:

- `id`
- `country_code`
- `name`
- `enabled`

### ApplicantOrigin

Fields:

- `id`
- `code`
- `name`
- `enabled`

### City

Fields:

- `id`
- `country_id`
- `name`
- `enabled`

### VisaCentre

Fields:

- `id`
- `city_id`
- `provider_id`
- `name`
- `official_url`
- `access_mode`
- `enabled`

### VisaCategory

Fields:

- `id`
- `name`
- `category_code`
- `description`
- `enabled`

### Provider

Fields:

- `id`
- `name`
- `provider_code`
- `access_mode`
- `terms_url`
- `documentation_url`
- `health_status`

### ProviderPermissionRecord

Fields:

- `id`
- `provider_id`
- `official_source_url`
- `terms_url`
- `robots_txt_url`
- `api_documentation_url`
- `permitted_access_method`
- `request_limits`
- `verified_at`
- `review_due_at`
- `responsible_administrator_id`
- `approval_status`
- `evidence_reference`

An adapter may execute automated access only when a current, approved
permission record exists and the provider and job are explicitly enabled for
automation. Permission records must be auditable and revocable. Missing,
expired, unclear or revoked permission means manual-only or disabled operation.
An approved record requires a verification timestamp, review deadline and
responsible administrator. Provider names and public visibility are not
evidence of permission.

### Administrator

Fields:

- `id`
- `username`
- `password_hash`
- `role`
- `enabled`
- `created_at`
- `last_login_at`

### Session

Fields:

- `id`
- `administrator_id`
- `token_hash`
- `csrf_token_hash`
- `created_at`
- `expires_at`
- `revoked_at`

Do not store raw passwords, session secrets or notification credentials in
these records.

Authentication uses Argon2id password hashes and opaque, random session
tokens. Store only session-token and session-bound CSRF-token hashes.
State-changing browser requests require a matching Origin and CSRF header.
Login throttling is stored in the database with an HMAC of username and client
address rather than either raw value. Administrator session cookies are
HttpOnly, SameSite=Lax, Secure in production, and use the `__Host-` prefix
when Secure. The one-time administrator bootstrap accepts a password from a
prompt or environment, never command-line arguments, and refuses to replace
an existing account.

### AuthRateLimit

Fields:

- `id`
- `key_hash`
- `window_started_at`
- `failure_count`
- `blocked_until`
- `created_at`
- `updated_at`

### MonitoringJob

Fields:

- `id`
- `origin_id`
- `destination_country_id`
- `city_id`
- `visa_centre_id`
- `category_id`
- `provider_id`
- `appointment_type`
- `official_source_url`
- `polling_interval`
- `jitter_seconds`
- `enabled`
- `access_mode`
- `execution_status`
- `availability_status`
- `initial_available_alert_policy`
- `next_check_at`
- `last_check_at`
- `lock_owner`
- `lock_expires_at`

Access mode, execution status and appointment availability are separate
dimensions. `MANUAL_CHECK_REQUIRED` is an access/workflow condition, not an
appointment availability result.

### CheckResult

Fields:

- `id`
- `job_id`
- `provider_permission_record_id`
- `checked_at`
- `execution_status`
- `availability_status`
- `source_url`
- `response_code`
- `duration_ms`
- `error_message`

An execution failure or restricted check cannot carry an availability status.
Only successfully verified automated checks may establish automated
availability. Store safe diagnostics only. Do not retain raw provider
responses, session cookies, passwords, tokens or unnecessary applicant data in
check results or logs.

### AvailabilityHistory

Fields:

- `id`
- `job_id`
- `previous_status`
- `new_status`
- `detected_at`
- `source_check_result_id`
- `manual_verification_id`

### ManualVerification

Fields:

- `id`
- `job_id`
- `operator_administrator_id`
- `recorded_status`
- `verified_at`
- `official_source_url`
- `internal_notes`

Only authorized staff may create manual verification records. Keep them
distinct from automated check results; any resulting internal notification
must be explicitly labeled as manually verified. A verification may record
AVAILABLE or UNAVAILABLE only when directly confirmed on the official source;
an inconclusive review creates no availability result or availability alert.

### AuditEvent

Fields:

- `id`
- `administrator_id`
- `action`
- `entity_type`
- `entity_id`
- `occurred_at`
- `safe_metadata`

Record administrative changes, provider permission and access-mode changes,
manual verification, job changes, alert creation and compliance-related
events. Do not put secrets or sensitive applicant data in audit metadata.

### AlertEvent

Fields:

- `id`
- `job_id`
- `availability_history_id`
- `availability_status`
- `verification_source`
- `created_at`
- `deduplication_key`

### NotificationOutboxItem

Fields:

- `id`
- `alert_event_id`
- `channel`
- `recipient_reference`
- `created_at`
- `next_attempt_at`
- `state`

### NotificationDeliveryAttempt

Fields:

- `id`
- `outbox_item_id`
- `attempt_number`
- `attempted_at`
- `delivery_status`
- `provider_message_reference`
- `safe_error_detail`

Keep the logical alert separate from channel- and recipient-specific delivery
attempts. Retries must be bounded and idempotent; record each attempt
independently.

All reference and configuration entities use soft-disable fields where
applicable. Foreign-key deletion is restricted, including for audit and
delivery history; no automatic deletion/retention job is part of this phase.
The retention schedule must be approved before production. An approved
permission record without a review deadline is rejected by a database
constraint. Error messages and audit metadata must be sanitized before storage.

### SystemError

Fields:

- `id`
- `component`
- `provider_id`
- `severity`
- `message`
- `occurred_at`
- `resolved_at`

## 4. Provider Adapter Interface

All provider integrations must implement a common interface.

Adapters return a typed normalized result with separate execution and
availability statuses, provenance, and safe diagnostic details. Unexpected
content, access restrictions, or an unrecognized response must stop processing
and must never be guessed to mean AVAILABLE. Provider health is distinct from
individual job health. The initial VFS Global, BLS International and
TLScontact adapters are non-scraping placeholders.

The implementation provides an abstract, typed `BaseProvider` contract and
provider-specific configuration, context and result models.
`execute_provider_check` is the supported execution entry point. Before
invoking an adapter, it requires the provider, centre and job to be enabled and
`AUTOMATED`, the adapter to declare `AUTOMATED` capability and a permitted
access method, and a current approved permission record for that method. The
permission reviewer must be an enabled administrator; the record must not be
revoked or past its review deadline, and its official source must match the
job URL's origin. Automation also requires an HTTPS terms URL, non-empty
documented evidence reference and non-empty request-limit configuration;
incomplete approval records remain manual-only.

Missing, expired, revoked or mismatched permission returns
`SKIPPED_RESTRICTED` with `MANUAL_CHECK_REQUIRED` and no availability. A typed
provider source failure becomes `SOURCE_ERROR` with no availability and a safe
diagnostic code. If an adapter reports restricted access or unexpected source
content, automation is switched off for the provider and an audit event is
written in the caller's database transaction; the caller must commit the
transaction for both changes to persist. Access restrictions return
`SKIPPED_RESTRICTED`. Unexpected programming exceptions propagate for
worker-level supervision; they are not converted into successful or
availability-shaped results. The result validator rejects unsupported
provenance, missing permission evidence, result-provider mismatches and source
URL changes.

Conceptually:

```python
class BaseProvider(ABC):
    async def check_availability(
        self, context: ProviderCheckContext
    ) -> ProviderCheckResult: ...

    async def health_check(self) -> ProviderHealthResult: ...

    def get_access_mode(self) -> ProviderAccessMode: ...
```

Use a standardized typed result with distinct fields for:

- Execution status (for example, `SUCCEEDED`, `SOURCE_ERROR`, or
  `SKIPPED_RESTRICTED`).
- Availability status (`AVAILABLE`, `UNAVAILABLE`, `UNKNOWN`, or not
  applicable).
- Verification source (authorized automation for adapter results; staff manual
  verification is stored as a separate `ManualVerification` record).
- Checked timestamp, official source URL, and safe diagnostic details.

`MANUAL_CHECK_REQUIRED` is an access/workflow mode, not a check execution
outcome or appointment availability. A restricted job is not executed and
must not produce an automated availability result.

The implementation must validate adapter results before storing or alerting.
The initial VFS Global, BLS International and TLScontact adapters are
non-networking manual-check placeholders. Their health status is `UNKNOWN`;
no live provider integration or HTTP client has been added. Provider-specific
URLs, access modes, permission evidence and request limits remain database
configuration; YAML remains seed-only.

## 5. Monitoring Workflow

```text
Scheduler
   |
   v
Claim due job using a database-backed lease
   |
   v
Check access mode and current provider permission record
   |
   +---- No valid permission / restricted ----> Stop; require manual check
   |
   v
Check provider health and circuit breaker
   |
   v
Execute permitted provider adapter
   |
   v
Normalize result, persist CheckResult, and compare verified availability state
   |
   +---- No transition ----> Finish
   |
   v
UNAVAILABLE -> AVAILABLE?
   |
   +---- Verified transition or configured initial policy ----> Create alert
                         |
                         v
                  Durable notification outbox
                         |
                         v
                  Independent delivery attempts
```

## 6. Scheduling

Use a dedicated monitoring process with APScheduler or an equivalent
scheduler.

Requirements:

- Per-job scheduling.
- Minimum configurable polling interval.
- Randomized jitter.
- Persistent scheduling state.
- No overlapping checks for the same job.
- Database-backed job locks or expiring leases with owner identity.
- Bounded concurrency.
- Per-provider concurrency limits.
- Graceful shutdown.
- Recovery after process restart or expired worker lease.
- Scheduler heartbeat independent from the web process.

Polling defaults must be conservative and must never override provider restrictions.

## 7. Change Detection

Implement a dedicated service.

Pseudocode:

```python
if result.is_verified_available:
    if previous_status == "UNAVAILABLE" or initial_available_alert_is_enabled(job):
        if not duplicate_alert_exists(job):
            create_alert(job)
```

Additional safeguards:

- UNKNOWN cannot trigger availability alerts.
- SOURCE_ERROR cannot trigger availability alerts.
- The MANUAL_CHECK_REQUIRED state itself cannot trigger an automated
  availability alert. A separate staff manual-verification event may create an
  internal notification only under the policy described above.
- DISABLED cannot trigger availability alerts.
- Deduplicate by job and availability transition.
- Apply cooldown.
- Persist alert state before delivery attempts.
- The default initial-AVAILABLE policy is disabled. If explicitly enabled by an
  administrator, it applies only to a verified AVAILABLE result. Staff may
  generate an internal notification from a manual verification only when
  configured; label it as manually verified, keep it separate from automated
  results, and do not notify applicants.

## 8. Notification Architecture

Define a common notification interface.

```python
class NotificationProvider:

    async def send(self, message, recipient):
        raise NotImplementedError
```

Implement:

- `TelegramNotificationProvider`
- `EmailNotificationProvider`

Use a notification outbox pattern so that temporary delivery failures do not
lose alerts.
Store each channel/recipient delivery attempt independently from the logical
alert event. Use bounded, idempotent retries and retain safe failure details.

## 9. Dashboard

FastAPI with server-rendered HTML templates is sufficient for the initial version.

Suggested pages:

- `/login`
- `/dashboard`
- `/countries`
- `/origins`
- `/cities`
- `/centres`
- `/categories`
- `/providers`
- `/jobs`
- `/history`
- `/alerts`
- `/logs`
- `/settings`

Use authenticated routes and CSRF protection where applicable.

### Implemented administration workflows

Authenticated, CSRF-protected administrator endpoints and role-aware dashboard
forms support:

- Creating and listing `STAFF` accounts; public registration remains disabled.
- Creating and updating monitoring jobs, including enable/pause state.
- Validating selected reference records and city/country,
  centre/provider, and official source URL relationships.
- Running the scheduler as a dedicated Docker service, separate from the web
  application, with the default manual-only provider registry.

Staff may use operational views and record manual verifications, but cannot
administer accounts or change job configuration. Provider records remain
seeded; job creation does not change provider access modes or permission
records. A job can be configured while its source is manual-only, but it does
not make an automated provider request without the existing permission gate.
Alerts, notification outbox items, and system errors remain system-generated.

## 10. Health Monitoring

Implement:

```text
GET /health
GET /health/live
GET /health/ready
```

The readiness endpoint should verify essential dependencies.

A separate heartbeat monitor must detect when scheduled checks stop running.

System-health alerts should be distinguishable from appointment-availability alerts.
Heartbeat monitoring and system-failure notifications must be independent of
the application process whose failure they detect.

## 11. Deployment Architecture

Initial deployment:

```text
Internet
   |
HTTPS Reverse Proxy
   |
   +---- FastAPI Web Application
   |
   +---- Dedicated Monitoring Process (scheduler and job execution)
   |
   +---- PostgreSQL (runtime configuration, state, and worker leases)
```

The database-backed lease design must support multiple monitoring workers
later without duplicate job execution. The initial release remains a
single-server modular monolith and does not require a broker.

Use Docker Compose for the initial deployment. Define backup frequency,
retention, access protection, and recovery objectives before production.
Document and test database restoration before release and on a recurring
schedule. Configure an independent operational alert path for missing
heartbeats or database/service failures.

Use persistent database volumes and container restart policies.

The initial deployment may run one scheduler instance. If additional scheduler
instances or workers are run, database-backed leases must coordinate claims and
prevent duplicate job execution.

## 12. Configuration Strategy

Keep configuration separate from application logic.

Use YAML for initial country, origin, destination and provider metadata.

Use database records as the authoritative source for all runtime-managed
configuration, including jobs and provider access settings. Seed/import
operations must be idempotent and must not silently overwrite database edits.
Secrets belong in environment variables or a cloud secret manager, not YAML.

Validate configuration using Pydantic.

Do not allow configuration files to override provider access restrictions or
compliance safeguards.

## 13. Scalability

Design for future improvements:

- Dedicated workers.
- Multiple application instances.
- Centralized logging.
- Metrics and dashboards.
- Managed PostgreSQL.
- External uptime monitoring.

Additional application instances, dedicated workers and managed PostgreSQL
are future deployment options, not mandatory initial dependencies. The
database-backed lease boundary is required in the initial design so multiple
workers can be introduced without changing job semantics. A broker is not
required unless a measured need emerges.