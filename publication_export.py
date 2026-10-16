"""DFKI intranet publication export and CSV validation.

Extracted from monitor_publications.py as a refactor. The full application
also resolves contacts and sends invitations; those operations are elsewhere.
Importing this module makes no network requests.
"""
import csv
import io
from urllib.parse import urlencode

import requests

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


def fetch_publications(username, password):
    """Fetch and validate the SLT publication CSV using supplied credentials."""
    with requests.Session() as session:
        session.auth = (username, password)
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

