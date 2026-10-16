# DFKI SLT publication monitor

Automatically invites eligible SLT publication authors and Verwalter to the colloquium. The follow-up digest goes **only to `colloquium-slt@dfki.de`**.

## Set up once

Use a Linux machine with **Python 3.13 or 3.14**, **cron**, and **DFKI intranet access** (DFKI network or a connected VPN). Your mail account must be authorized to **send as `colloquium-slt@dfki.de`** and use SMTP authentication.

```bash
git clone https://github.com/DFKI-NLP/publication-monitor.git
cd publication-monitor
./setup.sh
```

Enter your:

1. **DFKI username** — the mail login defaults to `username@dfki.de`.
2. **Intranet password**.
3. **Mail password**.

On a new installation, also enter the intranet IDs of heads/admins who should never receive invitations. Existing exclusions are preserved.

Setup installs dependencies, saves your settings privately, checks intranet access and mail authentication, records existing publications without emailing them, and schedules a daily check at **07:00 in the scheduler's timezone**. It sends no test emails; Send As permission must already be granted by the mailbox administrator.

**Keep the machine, cron, and VPN running.** Setup does not establish a VPN connection. Passwords are stored in a local, owner-only `.env` file, excluded from Git and Docker images. You only need to enter them again if they change.

## Everyday use

```bash
./monitor_publications.sh --dry-run  # Check without sending emails
./monitor_publications.sh            # Run now and send any new invitations
./setup.sh --credentials             # Update saved passwords
```

Logs are in `monitor.log`. Re-running setup keeps your publication history and replaces its own schedule rather than adding a duplicate. Use only one scheduled installation.

## Who gets invited?

For newly registered publications from the last six months, the monitor invites the eligible SLT Verwalter and the first eligible SLT author if they differ. It reads addresses from the intranet, applies your exclusions, and avoids duplicate invitations. Publications without a year are skipped. The digest reports invitations, skips, and failures.

For Docker, migration, different SMTP usernames, failure handling, and tests, see [advanced setup](docs/advanced.md).
