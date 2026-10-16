#!/usr/bin/env python3
"""Invite eligible SLT publication contacts and send a shared-mailbox digest."""
import argparse
import fcntl
import html
import json
import logging
import os
import re
from pathlib import Path
import smtplib
import ssl
import tempfile
from email.message import EmailMessage

import requests

from contacts import resolve_contacts
from publication_export import INTRANET_ROOT, fetch_publications as export_publications
from datetime import date

MAILBOX = "colloquium-slt@dfki.de"
LOG = logging.getLogger(__name__)


def setting(name, default=None):
    """Support environment variables or mounted secret files (NAME_FILE)."""
    value, filename = os.getenv(name), os.getenv(name + "_FILE")
    if value and filename:
        raise ValueError(f"Set only {name} or {name}_FILE")
    if filename:
        value = Path(filename).read_text().rstrip("\r\n")
    value = value or default
    if not value:
        raise ValueError(f"Missing {name} (or {name}_FILE)")
    return value


def fetch_publications():
    return export_publications(setting("DFKI_USER"), setting("DFKI_PASS"))


def load_state(path):
    if not path.exists():
        return None
    ids = json.loads(path.read_text())
    if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("Invalid publication state file")
    return set(ids)


def save_state(path, ids):
    """Replace state atomically; interrupted writes cannot truncate the cache."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(sorted(ids), handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def build_body(papers):
    items = []
    for pubid, paper in sorted(papers.items()):
        title = html.escape(paper.get("title") or "Untitled")
        venue = html.escape(paper.get("booktitle") or paper.get("journal") or "")
        year = html.escape(paper.get("year") or "")
        link = f"{INTRANET_ROOT}/research/publications/showPublication?pubid={pubid}"
        items.append(f'<li><a href="{link}">{title}</a> ({year})<br>{venue}</li>')
    return ("<p>New DFKI-SLT publications registered on the intranet:</p><ul>"
            + "".join(items)
            + "</ul>")


def send_email(subject, body, recipients):
    if not recipients or any(not re.fullmatch(r"[\w.+-]+@dfki\.de", addr, re.I) for addr in recipients):
        raise ValueError("Recipients must be intranet-resolved DFKI email addresses")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAILBOX
    msg["Reply-To"] = MAILBOX
    msg["To"] = ", ".join(recipients)
    msg.set_content("DFKI SLT Colloquium. View the HTML part for details.")
    msg.add_alternative(body, subtype="html")
    user, password = setting("SMTP_USER"), setting("SMTP_PASS")
    with smtplib.SMTP("smtp.office365.com", 587, timeout=60) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg, from_addr=MAILBOX, to_addrs=recipients)


def is_recent(paper, months=6):
    try:
        year = int(float(paper.get("year") or "nan"))
        try:
            month = int(float(paper.get("month") or "12"))
        except (ValueError, OverflowError):
            month = 12
        month = month if 1 <= month <= 12 else 12
        published = date(year, month, 1)
    except (ValueError, OverflowError):
        return False
    today = date.today()
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    return published >= date(year, month + 1, 1)


def plan_invitations(papers):
    # Require an explicit deployment policy; no personal UIDs in public source.
    raw_excluded = os.getenv("EXCLUDED_UIDS")
    if raw_excluded is None:
        raise ValueError("Set EXCLUDED_UIDS to the excluded head/admin UIDs (or explicitly empty)")
    excluded = {uid.strip() for uid in raw_excluded.split(",") if uid.strip()}
    invited, skipped = {}, []
    with requests.Session() as session:
        session.auth = (setting("DFKI_USER"), setting("DFKI_PASS"))
        for pubid, paper in papers.items():
            if not is_recent(paper):
                skipped.append((pubid, paper, "Outside the six-month invitation window or missing publication date"))
                continue
            contacts = resolve_contacts(session, str(pubid), paper.get("author_ou") or "", excluded)
            if not contacts:
                skipped.append((pubid, paper, "No eligible SLT Verwalter or author could be resolved"))
            for name, email, note in contacts:
                rec = invited.setdefault(email.lower(), {"name": name, "email": email, "papers": {}})
                rec["papers"][pubid] = paper
    return list(invited.values()), skipped


def invitation_body(rec, when=None):
    when = html.escape(when if when is not None else os.getenv("COLLOQUIUM_WHEN", "Thursdays at 14:00"))
    return (
        f"<p>Dear {html.escape(rec['name'])},</p>"
        "<p>Thank you for registering the following publication(s) on the DFKI intranet.</p>"
        + build_body(rec["papers"])
        + f"<p>As the SLT contact for this work, we would strongly encourage you to "
        f"present it at the DFKI SLT Colloquium, which takes place on {when}. "
        "It's a great opportunity to share your work with the group, and we would really like to have it featured.</p>"
        "<p>Please reply with your availability and we will find a slot for you.</p>"
        f"<p>Best regards,<br>The DFKI SLT Colloquium<br>{MAILBOX}</p>"
    )


def send_digest(invited, skipped, failed):
    # Digest routing is deliberately separate from invitation recipients.
    body = "<p>DFKI-SLT publication monitor – morning run summary.</p>"
    for rec in invited:
        status = "FAILED to send" if rec["email"].lower() in failed else "Invitation sent"
        body += (f"<p>{status}: {html.escape(rec['name'])} "
                 f"&lt;{html.escape(rec['email'])}&gt;</p>" + build_body(rec["papers"]))
    for pubid, paper, reason in skipped:
        body += f"<p>Skipped: {html.escape(reason)}</p>" + build_body({pubid: paper})
    send_email(
        f"DFKI SLT – {len(invited) - len(failed)} invitation(s), {len(skipped)} skipped, {len(failed)} failed",
        body, [MAILBOX],
    )


def run(state, dry_run=False):
    # Lock across fetching, delivery and state update, including other cron runs.
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.with_suffix(state.suffix + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info("Another monitor run is active; skipping")
            return
        known = load_state(state)
        papers = fetch_publications()
        current = set(papers)
        if known is None:
            if dry_run:
                LOG.info("First run: would save %d IDs without emailing", len(current))
            else:
                save_state(state, current)
                LOG.info("First run: saved %d IDs without emailing", len(current))
            return
        new = {i: papers[i] for i in sorted(current - known)}
        if not new:
            LOG.info("No new publications")
            return
        invited, skipped = plan_invitations(new)
        if dry_run:
            LOG.info("Would send %d direct invitation(s); %d publication(s) skipped; digest only to %s",
                     len(invited), len(skipped), MAILBOX)
            return
        failed = set()
        try:
            for rec in invited:
                try:
                    send_email("Invitation to present at the DFKI SLT Colloquium",
                               invitation_body(rec), [rec["email"]])
                except Exception as exc:
                    failed.add(rec["email"].lower())
                    LOG.error("Invitation failed (%s); details will be in the digest", type(exc).__name__)
            send_digest(invited, skipped, failed)
        finally:
            # Preserve the original policy: after delivery starts, mark the batch
            # handled even on failure so a later run does not re-invite people.
            save_state(state, known | current)
        LOG.info("Sent %d invitation(s); %d failed; digest only to %s; state updated",
                 len(invited) - len(failed), len(failed), MAILBOX)
        if failed:
            raise RuntimeError("Some invitations failed; review the shared-mailbox digest")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and compare without sending email or changing publication state")
    parser.add_argument("--state", type=Path, default=Path(os.getenv("STATE_FILE", "state/known_publication_ids.json")))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(args.state, args.dry_run)
    except Exception as exc:
        # SMTP/server errors can include account details: don't log raw responses.
        LOG.error("Monitor failed (%s). Check intranet/VPN access, credentials, SMTP permissions and state directory. Check state and the digest before retrying invitations.", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
