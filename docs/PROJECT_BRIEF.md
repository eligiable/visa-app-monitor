Project Brief — SRM Visa Appointment Monitoring System
1. Objective

Develop a reliable cloud-hosted visa appointment monitoring platform for SRM Visa & Immigration Consultants.

The platform should identify newly available appointment slots on official visa appointment portals, where automated access is expressly permitted, and notify authorized administrators.

The platform must operate continuously, including outside normal office hours.

## Locked Architecture Decisions

- Use a modular monolith with PostgreSQL for the initial single-cloud-server
  deployment.
- The database is authoritative for runtime configuration. YAML files are
  used only to seed or import initial configuration; imports must not silently
  overwrite administrator changes.
- Run monitoring in a dedicated process, separate from the FastAPI web
  process. Use database-backed job locks or expiring leases to prevent
  duplicate checks and support additional workers later.
- Provider integrations are manual-only by default. Automated execution
  requires a current, documented and approved provider permission record.
- Use a durable notification outbox with independent delivery-attempt records.
- Manual verification is staff-only, persisted with operator identity and
  timestamp, and kept distinct from automated results.
- Require tests in every implementation phase.
- Supply secrets through environment variables or a cloud secret manager, not
  YAML or source control.

2. Business Requirements

The system must support two applicant origins:

Pakistan
United Arab Emirates

It must support the following destinations:

United States
Germany
France
Italy
Spain
Netherlands
Switzerland
Austria
Belgium
Portugal
Greece
Sweden
Norway
Denmark
Finland
Poland
Czech Republic
Hungary
Other configurable European destinations

The list above is an initial configuration proposal, not a guarantee that every destination has an accessible automated appointment source.

3. Monitoring Dimensions

Each monitoring job should identify:

Applicant origin.
Destination country.
Destination city.
Appointment provider.
Visa application centre.
Visa category.
Appointment type.
Official source URL.
Provider access mode.
Polling interval.
Notification preferences.
Current monitoring status.

Example:

yaml
applicant_origin: PK
destination_country: DE
destination_city: Karachi
provider: vfs_global
visa_centre: Karachi
visa_category: Schengen Tourist
appointment_type: Short Stay


This is a configuration example, not a verified live appointment integration.

4. Monitoring Modes

Every provider adapter must support an explicit operating mode.

AUTOMATED

Used only when official documentation or explicit provider permission supports the integration.

MANUAL_CHECK_REQUIRED

Used when the portal requires login, CAPTCHA, queue interaction, or other human verification that cannot be handled through an expressly permitted integration.

DISABLED

Used when access is prohibited, the provider is unavailable, or an administrator disables the integration.

MAINTENANCE

Used when an integration is temporarily unavailable or undergoing maintenance.

The system must never automatically switch a restricted source into an unauthorized access method.

An unverified, missing, expired or revoked provider permission record prohibits
automated execution. Provider adapters must remain manual-only or disabled
until permission has been documented and approved.

5. Appointment Statuses

Appointment availability statuses:

AVAILABLE
UNAVAILABLE
UNKNOWN

Provider access modes are AUTOMATED, MANUAL_CHECK_REQUIRED, DISABLED and
MAINTENANCE. Check execution outcomes include SUCCEEDED, SOURCE_ERROR and
SKIPPED_RESTRICTED. Appointment availability is AVAILABLE, UNAVAILABLE or
UNKNOWN; it is not inferred when a check is skipped or fails. A restricted
provider or centre policy cannot be weakened by a job-level setting.

UNKNOWN must never be interpreted as AVAILABLE.

Keep provider access mode, check execution status and appointment availability
as separate concepts. Only a verified AVAILABLE result can establish
availability. A portal failure, changed interface, restriction or unexpected
response must never be interpreted as AVAILABLE.

6. Availability Change Detection

The primary notification event is:

text
UNAVAILABLE -> AVAILABLE


Additional rules:

Do not alert repeatedly for the same availability state.
Record every meaningful status transition.
Apply a configurable cooldown.
Deduplicate notification events.
Notify administrators when a source becomes unhealthy.
Do not notify applicants about unverified availability.

By default, an initial AVAILABLE observation does not generate an alert,
because no prior verified transition exists. An explicit configurable policy
may enable an initial-observation alert, but only for verified AVAILABLE
results. Subsequent automated availability alerts require a verified
UNAVAILABLE-to-AVAILABLE transition.

Authorized staff may record a manual verification. If configured, it may
generate an internal staff notification labeled prominently as manually
verified; it must not be presented as an automated result or sent to
applicants.
7. Notification Requirements
Telegram

Send a formatted notification to configured Telegram recipients.
Label automated alerts as automatically verified. Label staff-entered results
as manually verified and route them only to authorized internal staff.

Example:

text
SRM VISA APPOINTMENT ALERT

Status: APPOINTMENT AVAILABLE

Applicant Origin: Pakistan
Destination: Germany
City: Karachi
Visa Centre: Karachi
Category: Schengen Tourist

Detected At: 2026-11-09 10:30 UTC

Official Source:
https://official-provider.example/

Please verify availability on the official portal.


The example URL is illustrative and must be replaced by a verified official source URL.

Email

Email alerts must include the same information.

Support configurable SMTP credentials and recipients.

8. Admin Dashboard

The dashboard must provide:

Secure login.
Overview of active monitoring jobs.
Available appointment alerts.
Country and city management.
Visa centre management.
Visa category management.
Applicant-origin management.
Provider configuration.
Start, stop and edit monitoring jobs.
Historical availability.
Monitoring execution logs.
Error logs.
Notification delivery history.
System health.
Manual-check status.
9. Reliability

The system must implement:

Structured logging.
Retry with exponential backoff.
Configurable jitter.
Minimum polling intervals.
Per-provider circuit breakers.
Persistent job state.
Scheduler health monitoring.
Database health monitoring.
Notification failure handling.
Container restart policies.
Database backups with documented retention and protected access.
Database restoration testing before production and on a documented schedule.
An independent alert path for missing scheduler heartbeat or system failure.
Monitoring heartbeat.
Alerting when monitoring stops unexpectedly.
10. Non-Functional Requirements
Secure by default.
Modular and maintainable.
Configurable without changing Python code.
Suitable for multiple destinations.
Extensible to additional providers.
Testable using mocked provider responses.
Deployable to a Linux cloud server.
Able to run without a graphical browser for API-based adapters.
11. Initial Scope Assumptions
The first deployment is a single-node installation.
PostgreSQL is the intended production database.
SQLite is permitted for local development and demonstrations.
One admin account is provisioned securely during installation.
Monitoring is performed against public or explicitly authorized interfaces.
Restricted appointment portals use manual-check mode.
Appointment availability is not guaranteed until confirmed by the official provider.
YAML files seed or import initial configuration; database records are
authoritative for runtime configuration.
The dashboard is for SRM staff, not a public applicant booking portal.
12. Acceptance Criteria

The initial implementation is accepted when:

The application starts using Docker Compose.
An administrator can log in.
Countries and destinations can be configured.
Monitoring jobs can be created and stopped.
Provider adapters report their access mode.
Mocked permitted availability results can be processed.
An unavailable-to-available transition creates one alert.
Duplicate alerts are suppressed.
Telegram and email delivery tests pass.
Restricted portals display MANUAL_CHECK_REQUIRED.
Historical checks are visible.
System health is available through an endpoint.
Automated tests pass.
Deployment instructions are complete.