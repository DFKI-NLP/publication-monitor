# DFKI SLT publication monitor

Checks the DFKI intranet for newly registered SLT publications, **sends invitations directly to eligible publication contacts**, and sends the follow-up digest **only to `colloquium-slt@dfki.de`**. The shared mailbox is also the sender and reply-to address. No individual's address is hardcoded as an invitation or digest recipient.

## Who gets invited

The original selection rules are preserved:

1. Consider publications from the last six months (publication year/month; a missing month is treated as December).
2. Invite the first eligible **Verwalter** (publication manager) whose staff profile identifies SLT membership.
3. Also invite the first eligible **SLT-tagged author** whose directory entry can be resolved, if their email differs from the manager's.
4. Skip head/admin accounts listed in `EXCLUDED_UIDS` in either role, and skip ambiguous or unresolved contacts. Read addresses from intranet staff profiles; never construct addresses from names.
5. Deduplicate by email and group multiple publications into one invitation per recipient.

The digest reports invitations, skipped publications and delivery failures. Its SMTP envelope and To header contain only the shared mailbox, with no individual CC/BCC recipients. An author's name/address can appear in the digest body as a report of the invitation; that does not make them a digest recipient.

## Requirements

- Linux and Python 3.13 or 3.14.
- **DFKI intranet access**, through the DFKI network, a connected VPN, or another approved route. Intranet credentials alone do not establish a VPN connection.
- A DFKI intranet account permitted to download the publication export.
- An SMTP account with SMTP AUTH enabled and **Send As** permission for `colloquium-slt@dfki.de`. Outbound access to `smtp.office365.com:587` is required.

The SMTP implementation uses STARTTLS with certificate validation and username/password authentication. It works only where the Microsoft 365 tenant permits this authentication method. It does not implement OAuth token acquisition. For a new deployment, confirm the permitted authentication method with IT; see [Microsoft's SMTP submission guidance](https://learn.microsoft.com/en-us/Exchange/mail-flow-best-practices/how-to-set-up-a-multifunction-device-or-application-to-send-email-using-microsoft-365-or-office-365).

## Local setup

```bash
git clone https://github.com/DFKI-NLP/publication-monitor.git
cd publication-monitor
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Edit .env locally with credentials and your excluded head/admin UIDs.
./monitor_publications.sh --dry-run
./monitor_publications.sh
```

Use a versioned Python executable to create the environment. If that interpreter is removed during a system upgrade, recreate `.venv` and reinstall the requirements.

Set `EXCLUDED_UIDS` to your deployment's comma-separated head/admin UIDs before running. Keep the existing exclusion list when migrating an installation; this repository does not publish personal staff identifiers. An explicitly empty value disables exclusions. `COLLOQUIUM_WHEN` controls the meeting time in invitations.

The launcher reads `.env` as shell syntax; quote values appropriately and keep this file private. Only source a file you trust. Alternatively, export variables and invoke `.venv/bin/python monitor_publications.py` directly. Each credential also supports a `_FILE` suffix, for example `DFKI_PASS_FILE=/run/secrets/intranet_password`; set either the value or the file, not both.

The default state file is `state/known_publication_ids.json`. Override it with `STATE_FILE` or `--state PATH`. On the first normal run, the monitor records current publication IDs without emailing the historical backlog. Later runs resolve eligible contacts for newly seen publications, send direct invitations, then send the shared-mailbox digest. A dry run fetches and compares publications without sending mail or modifying publication state; it may create the state directory and lock file.

To migrate an existing installation, stop its scheduler during the switch and copy its `known_publication_ids.json` into the new state location before the first run. Do not run two installations against separate copies of the same history.

## Schedule

Once the VPN and credentials work, add this to the crontab of the account that owns the installation. Replace `/absolute/path/publication-monitor` with the actual directory:

```cron
0 7 * * * /absolute/path/publication-monitor/monitor_publications.sh >> /absolute/path/publication-monitor/monitor.log 2>&1
```

Cron uses the scheduler's configured timezone. Check that it matches the intended local time. The program runs once and exits; cron supplies the daily schedule. Monitor nonzero exits and rotate the local log as appropriate.

## VPN and Docker

**Recommended: manage the VPN on the Linux host**, using the DFKI-supported client and connection profile, then run this script through cron. For unattended operation, ask IT which reconnect/service configuration is supported, especially if the VPN requires MFA. A working host VPN is sufficient for the native installation.

A Docker container packages the application; it does not create DFKI network access by itself. The included Compose setup uses Linux host networking for builds and runs so it can use existing host VPN routes. Verify intranet DNS resolution from the container too: VPN-provided DNS is configuration-dependent. See [Docker host networking](https://docs.docker.com/engine/network/drivers/host/).

```bash
# Configure .env first, as above. Run on a Linux host with intranet access.
docker compose build
docker compose run --rm monitor --dry-run
docker compose run --rm monitor
```

Compose keeps publication state in a named volume. The first normal run initializes that volume without sending historical publications. Preserve the volume when upgrading; `docker compose down -v` deletes it. Use a host scheduler to invoke `docker compose run --rm monitor` daily. Run only one scheduled deployment.

Credentials are supplied at runtime and are excluded from the build context. Environment variables remain accessible to administrators with Docker access. For tighter handling, mount secret files and set the corresponding `_FILE` variables; see [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

A VPN sidecar is possible, but there is no universal DFKI VPN container configuration. It requires the approved client/protocol, gateway, certificate policy, and any MFA or service-account arrangement. A sidecar design would share the VPN container's network namespace and mount credentials as secrets. This repository intentionally does not ship an unverified auto-login configuration or embed VPN credentials. Get an approved unattended connection working first, then verify both intranet DNS and SMTP egress.

## Reliability and privacy

- A process lock prevents overlapping runs using the same state path.
- State is replaced atomically. As in the original monitor, once invitation delivery starts, the batch is marked handled even if some deliveries fail, to avoid automatically re-inviting people who already received mail.
- Previously seen IDs remain recorded even if the intranet temporarily omits them.
- Fetch/parse failures leave publication state unchanged. Invitation failures are reported in the shared-mailbox digest and return a nonzero exit status. Delivery failures require review and manual follow-up; they are not automatically retried. If the digest itself fails, review the local error log.
- As with SMTP generally, delivery is not exactly-once: a crash after server acceptance but before saving state can cause a duplicate summary. SMTP acceptance also does not guarantee final mailbox delivery.
- Error logs omit raw server responses and credentials. Publication titles and links appear only in the summary email, not routine logs.
- `.env`, secret files, logs, local state and environments are excluded from Git. The Docker build context includes only the application modules, requirements and Dockerfile.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Tests use synthetic publications and mocked SMTP/intranet connections. They cover direct invitation delivery, shared-mailbox-only digest routing, Verwalter/author selection, exclusions, address deduplication, recent-publication filtering, HTML escaping, initial state, failure handling, dry runs, invalid data, secret files and overlapping processes. GitHub Actions runs these tests without credentials or intranet access. An actual deployment still needs a live dry run on the intended network and valid SMTP permissions.
