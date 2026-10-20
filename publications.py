"""Local CSV storage and invitation text for the colloquium viewer."""
import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile

MAILBOX = 'colloquium-slt@dfki.de'
SUBJECT = 'Invitation to present at the DFKI SLT Colloquium'


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), delimiter=';')
    if not {'id', 'title'}.issubset(reader.fieldnames or []):
        raise ValueError('This is not a publication export: id/title columns are missing.')
    papers = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError('The CSV contains an incomplete or malformed row.')
        if not row['id'].isdigit() or int(row['id']) <= 0 or not row['title'].strip():
            raise ValueError('A publication is missing its ID or title.')
        if row['id'] in papers:
            raise ValueError('The CSV contains duplicate publication IDs.')
        papers[row['id']] = row
    if not papers:
        raise ValueError('The CSV is empty. The saved publications were not changed.')
    return papers


def save_text(path, text):
    """Replace a local file atomically, with owner-only permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def load(path):
    if not path.exists():
        return {'papers': {}, 'invited': [], 'new': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('papers'), dict) or not all(isinstance(data.get(k), list) for k in ('invited', 'new')):
        raise ValueError('The saved publication file has an unexpected format.')
    for key, row in data['papers'].items():
        if not key.isdigit() or not isinstance(row, dict) or row.get('id') != key or not isinstance(row.get('title'), str):
            raise ValueError('The saved publication file contains an invalid entry.')
    return data


def import_csv(path, data):
    papers = parse_csv(path.read_text(encoding='utf-8-sig'))
    previous = data['papers']
    return {
        'papers': {**previous, **papers},
        'invited': list(data['invited']),
        'new': sorted(set(papers) - set(previous), key=int) if previous else [],
    }


def added_date(paper):
    try:
        return datetime.strptime(paper.get('creationdate', ''), '%d.%m.%Y').date()
    except ValueError:
        return None


def invitation(papers, name='', when='Thursdays at 14:00'):
    if not papers:
        return ''
    items = '\n\n'.join(
        paper['title'] + '\nhttps://intranet.dfki.de/research/publications/showPublication?pubid=' + paper['id']
        for paper in papers
    )
    plural = 's' if len(papers) != 1 else ''
    return (
        f"Dear {name.strip() or '[name]'},\n\n"
        f"Thank you for registering the following publication{plural} on the DFKI intranet:\n\n"
        f"{items}\n\n"
        "As the SLT contact for this work, we would strongly encourage you to "
        f"present it at the DFKI SLT Colloquium, which takes place on {when}. "
        "It's a great opportunity to share your work with the group, and we would really like to have it featured.\n\n"
        "Please reply to this email with your availability and we will find a slot for you.\n\n"
        f"Best regards,\nThe DFKI SLT Colloquium\n{MAILBOX}"
    )
