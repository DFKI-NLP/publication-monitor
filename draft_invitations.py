#!/usr/bin/env python3
"""Create copy-and-paste colloquium invitations from local JSON; never send mail."""
import argparse
from email.message import EmailMessage
from email.policy import SMTP
import json
import os
from pathlib import Path
import re
import sys

from monitor_publications import MAILBOX, invitation_body


def load_invitations(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get('invitations'), list):
        raise ValueError('Expected an object with an invitations list')
    invitations = []
    for item in data['invitations']:
        name, address = item.get('name', ''), item.get('email', '')
        if not isinstance(name, str) or not name.strip() or '\n' in name or '\r' in name:
            raise ValueError('Each invitation needs a name without line breaks')
        if not isinstance(address, str) or not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', address):
            raise ValueError('Each invitation needs one valid email address')
        papers = {}
        for paper in item.get('publications', []):
            pubid = paper.get('id')
            if type(pubid) is not int or pubid <= 0 or pubid in papers:
                raise ValueError('Publication IDs must be unique positive integers per invitation')
            if not isinstance(paper.get('title'), str) or not paper['title'].strip():
                raise ValueError('Each publication needs a title')
            for field in ('year', 'booktitle', 'journal'):
                if field in paper and not isinstance(paper[field], str):
                    raise ValueError(f'{field} must be text')
            papers[pubid] = dict(paper)
        if not papers:
            raise ValueError('Each invitation needs at least one publication')
        invitations.append({'name': name, 'email': address, 'papers': papers})
    if not invitations:
        raise ValueError('No invitations supplied')
    return invitations


def build_draft(rec, when):
    lines = [f"Dear {rec['name']},", '',
             'Thank you for registering the following publication(s) on the DFKI intranet:', '']
    for pubid, paper in sorted(rec['papers'].items()):
        lines.extend([paper['title'],
                      f'https://intranet.dfki.de/research/publications/showPublication?pubid={pubid}', ''])
    lines.extend([
        'As the SLT contact for this work, we would strongly encourage you to '
        f'present it at the DFKI SLT Colloquium, which takes place on {when}. '
        "It's a great opportunity to share your work with the group, and we would really like to have it featured.",
        '', 'Please reply with your availability and we will find a slot for you.', '',
        'Best regards,', 'The DFKI SLT Colloquium', MAILBOX,
    ])
    msg = EmailMessage(policy=SMTP)
    msg['From'] = MAILBOX
    msg['Reply-To'] = MAILBOX
    msg['To'] = rec['email']
    msg['Subject'] = 'Invitation to present at the DFKI SLT Colloquium'
    msg['X-Unsent'] = '1'
    msg.set_content('\n'.join(lines))
    msg.add_alternative(invitation_body(rec, when=when), subtype='html')
    return msg


def save_private(path, text):
    # Avoid overwriting earlier drafts or following an existing symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Local JSON containing selected recipients and publications')
    parser.add_argument('--output', type=Path, help='New directory for private .txt and .eml files; otherwise print drafts')
    parser.add_argument('--when', default='Thursdays at 14:00', help='Meeting time written into the invitations')
    args = parser.parse_args(argv)
    try:
        drafts = [build_draft(rec, args.when) for rec in load_invitations(args.input)]
        if args.output:
            args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        for index, msg in enumerate(drafts, start=1):
            text = (f"From: {msg['From']}\nTo: {msg['To']}\nSubject: {msg['Subject']}\n\n"
                    + msg.get_body(preferencelist=('plain',)).get_content())
            if args.output:
                save_private(args.output / f'invitation-{index:03d}.txt', text)
                save_private(args.output / f'invitation-{index:03d}.eml', msg.as_string())
            else:
                if index > 1:
                    print('\n' + '-' * 60 + '\n')
                print(text)
        print(f'Created {len(drafts)} draft(s). No intranet access, email sending, or publication-state changes.', file=sys.stderr)
        return 0
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        print(f'Could not create drafts ({type(exc).__name__}); check the input format and choose a new output directory.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
