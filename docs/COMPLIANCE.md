Compliance and Responsible Automation Policy
1. Mandatory Policy

The SRM Visa Appointment Monitoring System must access appointment sources only through methods that are publicly permitted or expressly authorized by the provider.

This document overrides any conflicting implementation request.

2. Permitted Access

An integration may operate automatically only when its access method is supported by one of the following:

Official documented API.
Official public data interface explicitly permitting automated access.
Written provider authorization.
Other clearly documented and permitted integration method.

Public visibility alone does not establish permission to automate access.

3. Prohibited Techniques

The following are strictly prohibited:

CAPTCHA solving.
CAPTCHA bypass.
Queue bypass.
Session spoofing.
Authentication bypass.
IP rotation to evade restrictions.
Proxy rotation to evade rate limits.
Browser fingerprint manipulation.
Automated account creation.
Unauthorized credential use.
Circumventing anti-bot protections.
Accessing private or restricted endpoints without authorization.

Do not implement these features, even as optional plugins.

4. Manual-Check Fallback

If a portal requires human authentication, CAPTCHA, queue participation or another interactive verification process without an authorized automated method:

Stop automated checks for that source.
Mark it MANUAL_CHECK_REQUIRED.
Store the reason.
Display the status in the dashboard.
Show the official source link.
Allow authorized staff to record a manually verified result.
Preserve the manual result's timestamp and operator identity.

Never repeatedly retry a blocked or restricted interaction.

5. Provider Verification

Before enabling an adapter, administrators must document:

Provider name.
Official website.
Relevant terms of use.
Robots.txt location, where applicable.
Official API documentation, if available.
Written authorization, if required.
Permitted request frequency.
Permitted access method.
Verification date.
Responsible administrator.

If permission is unclear, the adapter must remain disabled or manual-only.

6. Robots.txt and Terms

Respect robots.txt directives and applicable website terms.

Robots.txt is not a substitute for legal permission or provider authorization.

Review the provider's policies before deployment and whenever they change.

7. Polling and Rate Limiting

Implement:

Configurable minimum polling intervals.
Randomized jitter.
Per-provider request limits.
Per-centre limits where required.
Exponential backoff.
Circuit breakers.
Concurrency controls.

Never increase polling frequency to overcome missing or delayed results.

8. User-Agent

Use an identifiable User-Agent.

It should include:

Application name.
Application version.
Responsible organization.
Contact address controlled by SRM.

Do not disguise the application as a normal consumer browser.

9. Browser Automation

Playwright may only be used where permitted.

Do not use it to bypass login requirements, CAPTCHA, queues or anti-bot restrictions.

If a permitted browser interaction encounters a restriction, stop and report the restriction.

10. Data Protection

Store only the information necessary for monitoring and operations.

Do not collect unnecessary applicant passport details, dates of birth, travel documents or other sensitive information.

Protect administrator accounts and notification credentials.

Use encryption in transit and appropriate protection at rest.

11. Manual Verification

A manual verification record must include:

Monitoring job.
Operator.
Recorded status.
Verification timestamp.
Official source URL.
Optional internal notes.

A manual result must be distinguishable from an automatically verified result.

12. Audit Trail

Record:

Provider configuration changes.
Monitoring job changes.
Access-mode changes.
Manual status updates.
Alert creation.
Notification failures.
Administrator actions.
Compliance-related errors.
13. Failure Handling

When a provider returns unexpected content, blocks access, changes its interface or behaves unexpectedly:

Stop processing the affected result.
Do not guess availability.
Record the error.
Open or retain a circuit breaker as appropriate.
Notify administrators.
Require review before resuming.
14. Compliance Review Checklist

Before enabling a provider:

Official source identified.
Terms reviewed.
Robots.txt reviewed where applicable.
Automation permission documented.
API or permitted access method verified.
Request limits configured.
User-Agent configured.
Error handling tested.
Manual fallback tested.
Administrator approval recorded.
15. Non-Negotiable Rule

When uncertain whether an operation is permitted, do not automate it.

Display MANUAL_CHECK_REQUIRED and direct the operator to the official provider website.