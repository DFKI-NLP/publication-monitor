#!/usr/bin/env python3
"""Send new DFKI-SLT publications to the colloquium shared mailbox only."""
import argparse
import csv
import fcntl
import html
import io
import json
import logging
import os
from pathlib import Path
import smtplib
import ssl
import tempfile
from email.message import EmailMessage
from urllib.parse import urlencode

import requests

MAILBOX = "colloquium-slt@dfki.de"
INTRANET_ROOT = "https://intranet.dfki.de"
CSV_URL = INTRANET_ROOT + "/research/publications/exportPublications?" + urlencode({
    "save": "1", "Type": "2", "s_creationdate1": "", "s_creationdate2": "",
    "s_project": "", "s_projectRL": "0", "s_approved": "-1",
    "s_bibtextype": "all", "s_publanguage": "all", "s_status": "-1",
    "s_authors": "", "s_title": "", "s_month": "0", "s_year": "",
    "s_RL:list": "4", "s_RL_AND": "0", "s_conference": "", "s_series_selection": "",
    "s_series": "", "s_isbn": "", "s_doi": "", "s_publisher": "", "s_url": "",
    "s_keywords": "", "s_dataset_published": "", "s_sourcecode_published": "",
    "ok": "Suchen",
})
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
    with requests.Session() as session:
        session.auth = (setting("DFKI_USER"), setting("DFKI_PASS"))
        response = session.get(CSV_URL, timeout=(15, 120), allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Intranet returned a redirect or unexpected status")
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")), delimiter=";")
        if not reader.fieldnames or not {"id", "title"}.issubset(reader.fieldnames):
            raise ValueError("Intranet response is not the expected publication CSV")
        papers = {}
        for row in reader:
            if None in row or row.get("title") is None:
                raise ValueError("Malformed CSV row")
            pubid = int(row["id"])
            if pubid <= 0 or pubid in papers:
                raise ValueError("Invalid or duplicate publication ID")
            papers[pubid] = row
        if not papers:
            raise ValueError("Empty publication list; preserving existing state")
        return papers


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
            + "</ul><p>Automated publication summary. No individual invitations were sent.</p>")


def send_summary(papers):
    # No caller-controlled recipients or sender: both header and SMTP envelope
    # are restricted to the shared mailbox. Author addresses are never used.
    msg = EmailMessage()
    msg["Subject"] = f"DFKI SLT – {len(papers)} new publication(s)"
    msg["From"] = MAILBOX
    msg["To"] = MAILBOX
    msg.set_content("New DFKI-SLT publications. View the HTML part for details.")
    msg.add_alternative(build_body(papers), subtype="html")
    user, password = setting("SMTP_USER"), setting("SMTP_PASS")
    with smtplib.SMTP("smtp.office365.com", 587, timeout=60) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg, from_addr=MAILBOX, to_addrs=[MAILBOX])


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
        if dry_run:
            LOG.info("Would send %d new publication(s) only to %s", len(new), MAILBOX)
            return
        send_summary(new)
        # Never remove previously seen IDs if the intranet temporarily omits them.
        save_state(state, known | current)
        LOG.info("Sent %d new publication(s) to %s; state updated", len(new), MAILBOX)


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
        LOG.error("Monitor failed (%s). Check intranet/VPN access, credentials, SMTP permissions and state directory. State is retained for retry.", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
