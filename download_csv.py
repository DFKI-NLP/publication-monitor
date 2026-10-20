#!/usr/bin/env python3
"""Manually download the SLT CSV with one GET. No contact lookups or scheduling."""
import argparse
import getpass
from pathlib import Path

import requests

from publications import parse_csv, save_text, EXPORT_URL as URL




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
    print(f'Saved {count} publications to {args.output}. Import this file using the local webpage.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
