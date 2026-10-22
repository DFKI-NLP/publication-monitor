# Optional approved automation

The local web interface still sends no emails. This separate monitor is for deployments with authorization for automated exports, contact lookups, and invitations.

The export timer runs at 20:00 Europe/Berlin, following daylight-saving changes. It runs `scheduled.py prepare` to resolve contacts and queue invitations without sending them. A separate timer runs `scheduled.py send` at 09:00 to send the saved invitations and digest without accessing the intranet. It does not catch up missed runs immediately after boot. Each run makes one CSV export GET, without redirects or retries. Set `CSV_OUTPUT` to save the validated CSV locally.

New eligible publications trigger Verwalter lookups. `STAFF_ROSTER` points to a private `uid,name` CSV of SLT colleagues. Known colleagues resolve locally; unfamiliar authors may need a directory search, and unfamiliar Verwalter may need a staff-profile check for SLT membership. Email addresses are always constructed as `uid@dfki.de`; there are no email-address lookups. `EXCLUDED_UIDS` retains the configured exclusions.

Invitations are grouped by recipient and sent separately. The digest goes only to `colloquium-slt@dfki.de`. Previously known publications are not invited again. The existing six-month publication-date filter remains in place. Queued IDs are saved before advancing history. Each recipient’s delivery status is persisted before and after SMTP, so interrupted or failed sends require review rather than an automatic retry. Completed drafts are never sent again.

Run under a dedicated service account with root-owned code and systemd encrypted credentials. The four variables `DFKI_USER_FILE`, `DFKI_PASS_FILE`, `SMTP_USER_FILE`, and `SMTP_PASS_FILE` point to credentials supplied to the service by systemd. No secrets or private staff data belong in this repository.

Tests never contact the intranet or send mail:

```bash
python3 automation/test_update.py
python3 automation/test_schedule.py
```
