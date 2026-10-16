#!/usr/bin/env python3
"""Find public papers and create local drafts. No intranet access or mail sending."""
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
import fcntl
import getpass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote

import requests

MAILBOX = 'colloquium-slt@dfki.de'
API = 'https://api.openalex.org/works'


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            os.chmod(temp, 0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def read_team(path):
    members = {}
    with path.open(newline='') as handle:
        reader = csv.DictReader(handle)
        if not {'name', 'email', 'openalex_id', 'enabled'}.issubset(reader.fieldnames or []):
            raise ValueError('Roster needs name,email,openalex_id,enabled columns')
        for row in reader:
            if row['enabled'].lower() not in {'true', 'false'}:
                raise ValueError('enabled must be true or false')
            if row['enabled'].lower() == 'false':
                continue
            uid = row['openalex_id'].strip().removeprefix('https://openalex.org/')
            name, email = row['name'].strip(), row['email'].strip()
            if not re.fullmatch(r'A[0-9]+', uid) or uid in members:
                raise ValueError('Use a unique OpenAlex author ID for each row')
            if not name or any(c in name for c in '\r\n') or not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', email):
                raise ValueError('Roster contains an invalid name or email')
            members[uid] = {'name': name, 'email': email}
    if not members:
        raise ValueError('Roster has no enabled members')
    return members


def fetch_works(members, since, key):
    """Call only the documented OpenAlex works endpoint; fail on partial fetches."""
    if not key:
        raise ValueError('A verified OpenAlex API key is required for live pagination')
    works = []
    with requests.Session() as session:
        # Do not pick up .netrc credentials for other services.
        session.trust_env = False
        session.headers.update({'Authorization': 'Bearer ' + key, 'User-Agent': 'publication-monitor/1.0 (public metadata; local drafts)'})
        ids = sorted(members)
        request_count = 0
        for offset in range(0, len(ids), 50):
            cursor, visited = '*', set()
            while cursor:
                if cursor in visited or request_count >= 100:
                    raise ValueError('Pagination did not complete; state was not changed')
                visited.add(cursor)
                params = {'filter': 'authorships.author.id:' + '|'.join(ids[offset:offset+50]) + ',from_publication_date:' + since.isoformat(), 'per_page': 100, 'cursor': cursor}
                for attempt in range(3):
                    request_count += 1
                    time.sleep(0.5)
                    response = session.get(API, params=params, timeout=(10, 60), allow_redirects=False)
                    if response.status_code != 429 and response.status_code < 500:
                        break
                    if attempt < 2:
                        time.sleep(2 ** (attempt + 1))
                if response.status_code != 200:
                    raise ValueError(f'OpenAlex returned HTTP {response.status_code}; state was not changed')
                data = response.json()
                if not isinstance(data.get('results'), list) or not isinstance(data.get('meta'), dict) or 'next_cursor' not in data['meta']:
                    raise ValueError('Unexpected OpenAlex response')
                works.extend(data['results'])
                cursor = data['meta']['next_cursor']
    return works


def normalized_work(work, members, since):
    uid = str(work.get('id', '')).removeprefix('https://openalex.org/')
    if not re.fullmatch(r'W[0-9]+', uid):
        raise ValueError('Invalid OpenAlex work ID')
    published = work.get('publication_date')
    if not published:
        return None
    published = date.fromisoformat(published)
    if published < since:
        return None
    title = work.get('title') or work.get('display_name')
    if not isinstance(title, str) or not title.strip():
        return None
    recipient = None
    for authorship in work.get('authorships', []):
        author = (authorship.get('author') or {}).get('id', '')
        author = str(author).removeprefix('https://openalex.org/')
        if author in members:
            recipient = members[author]
            break
    if recipient is None:
        return None
    aliases = ['openalex:' + uid]
    doi = work.get('doi') or ''
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi, flags=re.I).lower().strip()
    if doi and not re.fullmatch(r'10\.[0-9]{4,9}/\S+', doi):
        raise ValueError('Invalid DOI')
    if doi:
        aliases.append('doi:' + doi)
    return {'title': title, 'date': published.isoformat(), 'url': 'https://doi.org/' + quote(doi, safe='/') if doi else 'https://openalex.org/' + uid, 'aliases': aliases, 'recipient': recipient, 'status': 'pending'}


def merge_records(records, works, members, since):
    for work in works:
        record = normalized_work(work, members, since)
        if record is None:
            continue
        matches = [key for key, old in records.items() if set(old['aliases']) & set(record['aliases'])]
        if len(matches) > 1:
            raise ValueError('Multiple existing records now share an ID/DOI; review state before proceeding')
        if matches:
            old = records[matches[0]]
            old['aliases'] = sorted(set(old['aliases']) | set(record['aliases']))
            # Preserve sent/dismissed decisions and original recipient.
            continue
        key = hashlib.sha256(record['aliases'][0].encode()).hexdigest()[:16]
        records[key] = record


def draft(record, when):
    rec = record['recipient']
    msg = EmailMessage()
    msg['From'] = MAILBOX
    msg['Reply-To'] = MAILBOX
    msg['To'] = rec['email']
    msg['Subject'] = 'Invitation to present at the DFKI SLT Colloquium'
    msg['X-Unsent'] = '1'
    msg.set_content(
        f"Dear {rec['name']},\n\n"
        "I came across your recent publication:\n\n"
        f"{record['title']}\n{record['url']}\n\n"
        f"Would you be interested in presenting this work at the DFKI SLT Colloquium? "
        f"Our usual slot is {when}.\n\n"
        "Please let us know if you are interested and which dates would work for you.\n\n"
        f"Best regards,\nThe DFKI SLT Colloquium\n{MAILBOX}\n"
    )
    return msg


def render_review(records, output, when):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-'), dir=output))
    lines = ['# Publications to review', '', 'Drafts only: check author identity and prior invitations, send manually, then mark sent.', '']
    for key, rec in records.items():
        if rec['status'] != 'pending' or not rec.get('eligible', True):
            continue
        msg = draft(rec, when)
        text = f"From: {msg['From']}\nTo: {msg['To']}\nSubject: {msg['Subject']}\n\n" + msg.get_content()
        write_private(directory / f'{key}.txt', text)
        write_private(directory / f'{key}.eml', msg.as_string())
        title_key = re.sub(r'\W+', '', rec['title']).casefold()
        duplicates = [other for other, candidate in records.items() if other != key and re.sub(r'\W+', '', candidate['title']).casefold() == title_key]
        lines += [f"## {html.escape(rec['title'])}", '', f"ID: `{key}` · {rec['date']} · {html.escape(rec['recipient']['name'])}", '', f"[Paper]({rec['url']}) · [Copyable email]({key}.txt) · [Email file]({key}.eml)", '']
        if duplicates:
            lines += ['Possible version duplicate; review these IDs before sending: ' + ', '.join(duplicates), '']
    if not any(r['status'] == 'pending' and r.get('eligible', True) for r in records.values()):
        lines += ['No pending invitations.', '']
    write_private(directory / 'review.md', '\n'.join(lines))
    return directory / 'review.md'


def read_state(path):
    if not path.exists():
        return {'version': 1, 'records': {}}
    data = json.loads(path.read_text())
    if data.get('version') != 1 or not isinstance(data.get('records'), dict):
        raise ValueError('Unrecognized public-monitor state')
    for key, record in data['records'].items():
        if not re.fullmatch(r'[0-9a-f]{16}', key) or record.get('status') not in {'pending', 'sent', 'dismissed'} or not isinstance(record.get('aliases'), list):
            raise ValueError('Invalid public-monitor state')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('state/public-monitor.json'))
    sub = parser.add_subparsers(dest='command', required=True)
    key = sub.add_parser('save-key', help='Save a public OpenAlex API key, with hidden input')
    key.add_argument('--key-file', type=Path, default=Path('secrets/openalex-api-key'))
    scan = sub.add_parser('scan', help='Discover papers and prepare local drafts')
    scan.add_argument('--team', required=True, type=Path)
    source = scan.add_mutually_exclusive_group(required=True)
    source.add_argument('--live', action='store_true', help='Query only api.openalex.org')
    source.add_argument('--fixture', type=Path, help='Offline OpenAlex-format JSON list')
    scan.add_argument('--key-file', type=Path, default=Path('secrets/openalex-api-key'))
    scan.add_argument('--days', type=int, default=180)
    scan.add_argument('--output', type=Path, default=Path('drafts/public'))
    scan.add_argument('--when', default='Thursdays at 14:00')
    mark = sub.add_parser('mark', help='Record your manual decision; never sends email')
    mark.add_argument('id')
    mark.add_argument('--status', required=True, choices=['sent', 'dismissed', 'pending'])
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == 'save-key':
            value = getpass.getpass('OpenAlex API key: ').strip()
            if not value:
                raise ValueError('API key cannot be empty')
            write_private(args.key_file, value + '\n')
            print('API key saved privately. No requests made.')
            return 0
        args.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with args.state.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = read_state(args.state)
            if args.command == 'mark':
                data['records'][args.id]['status'] = args.status
                write_private(args.state, json.dumps(data, indent=2))
                print(f'Recorded {args.id} as {args.status}. No email sent.')
                return 0
            if not 1 <= args.days <= 3660:
                raise ValueError('days must be between 1 and 3660')
            since = date.today() - timedelta(days=args.days)
            members = read_team(args.team)
            works = json.loads(args.fixture.read_text()) if args.fixture else fetch_works(members, since, args.key_file.read_text().strip())
            if not isinstance(works, list):
                raise ValueError('Expected a JSON list of works')
            merge_records(data['records'], works, members, since)
            active_emails = {member['email'].lower() for member in members.values()}
            for record in data['records'].values():
                record['eligible'] = record['recipient']['email'].lower() in active_emails
            review = render_review(data['records'], args.output, args.when)
            write_private(args.state, json.dumps(data, indent=2))
            print(f'Review: {review}')
            print('No emails sent. Mark sent only after sending manually; use dismissed to skip a paper.')
        return 0
    except (ValueError, KeyError, TypeError, AttributeError, OSError, requests.RequestException) as exc:
        # Never print requests exceptions containing headers/API keys.
        print(f'Public scan stopped ({type(exc).__name__}). Check roster, API key, input and state. No emails sent.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
