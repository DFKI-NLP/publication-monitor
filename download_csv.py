#!/usr/bin/env python3
"""Manually download the SLT CSV with one GET. No contact lookups or scheduling."""
import argparse
import getpass
from pathlib import Path
from urllib.parse import urlencode

import requests

from publications import parse_csv, save_text

URL = 'https://intranet.dfki.de/research/publications/exportPublications?' + urlencode({
    'save': '1', 'Type': '2', 's_creationdate1': '', 's_creationdate2': '',
    's_project': '', 's_projectRL': '0', 's_approved': '-1',
    's_bibtextype': 'all', 's_publanguage': 'all', 's_status': '-1',
    's_authors': '', 's_title': '', 's_month': '0', 's_year': '',
    's_RL:list': '4', 's_RL_AND': '0', 's_conference': '', 's_series_selection': '',
    's_series': '', 's_isbn': '', 's_doi': '', 's_publisher': '', 's_url': '',
    's_keywords': '', 's_dataset_published': '', 's_sourcecode_published': '', 'ok': 'Suchen',
})


def download(username, password, output):
    # No retry or redirect: this invocation makes exactly one HTTP GET request.
    response = requests.get(URL, auth=(username, password), timeout=(15, 120), allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f'Export returned HTTP {response.status_code}; existing file kept.')
    text = response.content.decode('utf-8-sig')
    count = len(parse_csv(text))
    save_text(output, text)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/publications.csv'))
    args = parser.parse_args()
    print('This contacts the DFKI intranet. Only use it with the required authorization.')
    username = input('DFKI username: ').strip()
    password = getpass.getpass('Intranet password: ')
    if not username or not password:
        parser.error('Username and password are required.')
    try:
        count = download(username, password, args.output)
    except (requests.RequestException, ValueError, OSError) as exc:
        print(f'Download failed ({type(exc).__name__}). Check access and credentials; no automatic retry.')
        return 1
    print(f'Saved {count} publications to {args.output}. Import this file in viewer.py.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
