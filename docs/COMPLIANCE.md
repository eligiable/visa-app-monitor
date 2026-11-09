# Compliance and Responsible Automation Policy

## 1. Mandatory Policy

The eligiable Visa Appointment Monitoring System must access appointment sources only through methods that are publicly permitted or expressly authorized by the provider.

This document overrides any conflicting implementation request.

## 2. Permitted Access

An integration may operate automatically only when its access method is
supported by one of the following:

- Official documented API.
- Official public data interface explicitly permitting automated access.
- Written provider authorization.
- Other clearly documented and permitted integration method.

Public visibility alone does not establish permission to automate access.

## 3. Prohibited Techniques

The following are strictly prohibited:

- CAPTCHA solving.
- CAPTCHA bypass.
- Queue bypass.
- Session spoofing.
- Authentication bypass.
- IP rotation to evade restrictions.
- Proxy rotation to evade rate limits.
- Browser fingerprint manipulation.
- Automated account creation.
- Unauthorized credential use.
- Circumventing anti-bot protections.
- Accessing private or restricted endpoints without authorization.

Do not implement these features, even as optional plugins.

## 4. Manual-Check Fallback

If a portal requires human authentication, CAPTCHA, queue participation or
another interactive verification process without an authorized automated
method:

1. Stop automated checks for that source.
2. Mark it `MANUAL_CHECK_REQUIRED`.
3. Store the reason.
4. Display the status in the dashboard.
5. Show the official source link.
6. Allow authorized staff to record a manually verified result.
7. Preserve the manual result's timestamp and operator identity.

Never repeatedly retry a blocked or restricted interaction.

## 5. Provider Verification

Before enabling an adapter, administrators must document:

- Provider name.
- Official website.
- Relevant terms of use.
- Robots.txt location, where applicable.
- Official API documentation, if available.
- Written authorization, if required.
- Permitted request frequency.
- Permitted access method.
- Verification date.
- Responsible administrator.

If permission is unclear, the adapter must remain disabled or manual-only.

Administrators can record review evidence in the dashboard for seed-managed
providers. An approval requires the reviewed terms URL, documented permitted
method, request limits, evidence reference, verification timestamp, reviewer,
and a future review deadline. Editing a review returns it to pending, and
revocation is recorded and irreversible. Dashboard approval records evidence;
it does not grant access or change a provider, centre, job, or adapter mode.
Provider authorization and permitted access must be verified independently
before approval.

## 6. Robots.txt and Terms

Respect robots.txt directives and applicable website terms.

Robots.txt is not a substitute for legal permission or provider authorization.

Review the provider's policies before deployment and whenever they change.

## 7. Polling and Rate Limiting

Implement:

- Configurable minimum polling intervals.
- Randomized jitter.
- Per-provider request limits.
- Per-centre limits where required.
- Exponential backoff.
- Circuit breakers.
- Concurrency controls.

Never increase polling frequency to overcome missing or delayed results.

## 8. User-Agent

Use an identifiable User-Agent.

It should include:

- Application name.
- Application version.
- Responsible organization.
- Contact address controlled by eligiable.

Do not disguise the application as a normal consumer browser.

## 9. Browser Automation

Playwright may only be used where permitted.

Do not use it to bypass login requirements, CAPTCHA, queues or anti-bot restrictions.

If a permitted browser interaction encounters a restriction, stop and report the restriction.

## 10. Data Protection

Store only the information necessary for monitoring and operations.

Do not collect unnecessary applicant passport details, dates of birth, travel documents or other sensitive information.

Protect administrator accounts and notification credentials.

Use encryption in transit and appropriate protection at rest.
Dashboard-managed Telegram and SMTP credentials must be authenticated-
encrypted before database storage. Keep the encryption key outside the
database, share it only with the web and scheduler processes, and never include
credential values in API responses, logs, test-send errors, or audit metadata.

## 11. Manual Verification

A manual verification record must include:

- Monitoring job.
- Operator.
- Recorded status.
- Verification timestamp.
- Official source URL.
- Optional internal notes.

A manual result must be distinguishable from an automatically verified result.

## 12. Audit Trail

Record:

- Administrator-created staff accounts and monitoring-job configuration
  changes, without storing passwords or secrets in audit metadata.
- Provider permission-review creation, edits, approval, and revocation.
- Notification integration creation/updates and test-send outcomes, without
  credential values.
- Monitoring job changes.
- Access-mode changes.
- Manual status updates.
- Alert creation.
- Notification failures.
- Administrator actions.
- Compliance-related errors.

## 13. Failure Handling

When a provider returns unexpected content, blocks access, changes its
interface or behaves unexpectedly:

1. Stop processing the affected result.
2. Do not guess availability.
3. Record the error.
4. Open or retain a circuit breaker as appropriate.
5. Notify administrators.
6. Require review before resuming.

## 14. Compliance Review Checklist

Before enabling a provider:

- Official source identified.
- Terms reviewed.
- Robots.txt reviewed where applicable.
- Automation permission documented.
- API or permitted access method verified.
- Request limits configured.
- User-Agent configured.
- Error handling tested.
- Manual fallback tested.
- Administrator approval recorded.

## 15. Non-Negotiable Rule

When uncertain whether an operation is permitted, do not automate it.

Display `MANUAL_CHECK_REQUIRED` and direct the operator to the official
provider website.

Administrative job creation or enablement is not provider authorization.
Provider records remain manual-only unless a current, documented and approved
permission record explicitly permits the adapter's access method. Account
creation remains administrator-only; public staff registration is disabled.