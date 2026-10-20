"""Local CSV storage and invitation text for the colloquium viewer."""
import csv
from datetime import datetime
import io
import json
import os
import re
import unicodedata
from pathlib import Path
import tempfile
from urllib.parse import urlencode

EXPORT_URL = 'https://intranet.dfki.de/research/publications/exportPublications?' + urlencode({
    'save': '1', 'Type': '2', 's_creationdate1': '', 's_creationdate2': '',
    's_project': '', 's_projectRL': '0', 's_approved': '-1',
    's_bibtextype': 'all', 's_publanguage': 'all', 's_status': '-1',
    's_authors': '', 's_title': '', 's_month': '0', 's_year': '',
    's_RL:list': '4', 's_RL_AND': '0', 's_conference': '', 's_series_selection': '',
    's_series': '', 's_isbn': '', 's_doi': '', 's_publisher': '', 's_url': '',
    's_keywords': '', 's_dataset_published': '', 's_sourcecode_published': '', 'ok': 'Suchen',
})

MAILBOX = 'colloquium-slt@dfki.de'
SUBJECT = 'Invitation to present at the DFKI SLT Colloquium'


def load_staff(folder):
    path = folder / 'staff.csv'
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    if any(not re.fullmatch(r'[a-z0-9]+', row.get('uid', '')) or not row.get('name') for row in rows):
        raise ValueError('staff.csv needs name and lowercase alphanumeric uid columns.')
    exclusions = folder / 'excluded_uids.txt'
    excluded = set(exclusions.read_text().split()) if exclusions.exists() else set()
    return [row for row in rows if row['uid'] not in excluded]


def name_key(name):
    text = unicodedata.normalize('NFKD', name.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return tuple(sorted(re.findall(r'\w+', text)))


def matched_contacts(papers, staff):
    """First unambiguous eligible SLT author per paper; no online lookup."""
    found = {}
    for paper in papers:
        for names, team in re.findall(r'([^()]+)\(([^)]*)\)', paper.get('author_ou', '')):
            if not re.search(r'\bSLT\b', team, re.I):
                continue
            name = names.split(',')[-1].strip()
            matches = [row for row in staff if name_key(row['name']) == name_key(name)]
            if len(matches) == 1:
                row = matches[0]
                found[row['uid']] = row
                break
    return list(found.values())


def recipients(papers, staff):
    return [row['uid'] + '@dfki.de' for row in matched_contacts(papers, staff)]


def merge_papers(papers, data):
    previous = set(data['papers']) | set(data.get('known_ids', []))
    return dict(data, papers={**data['papers'], **papers},
                new=sorted(set(papers) - previous, key=int) if previous else [])


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
