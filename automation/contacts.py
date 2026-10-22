"""Resolve invitation contacts using the original SLT Verwalter/author rules."""
import csv
import os
from pathlib import Path
import logging
import re
import unicodedata
from typing import List, Optional, Set, Tuple

import requests

INTRANET_ROOT = "https://intranet.dfki.de"
SLT_TAG_RE = re.compile(r"\bSLT\b", re.IGNORECASE)
SLT_PROFILE_MARKER = "Speech and Language Technology"

def parse_author_ou(author_ou: str) -> List[Tuple[str, str]]:
    """Parse 'Name1 (FB/FG MLT), Name2 (FB/FG SLT)' -> [(name, ou), ...]."""
    pairs = []
    for m in re.finditer(r"([^()]+?)\s*\(([^)]*)\)", author_ou):
        # External co-authors carry no "(FB/FG …)" tag, so several comma-
        # separated names can precede the tagged one; the tagged author is the
        # last comma-separated segment (author names contain no commas here).
        name = m.group(1).split(",")[-1].strip()
        ou = m.group(2).strip()
        if name:
            pairs.append((name, ou))
    return pairs


def slt_author_names(author_ou: str) -> List[str]:
    """Ordered names of authors tagged as SLT in the author_ou field."""
    return [name for name, ou in parse_author_ou(author_ou) if SLT_TAG_RE.search(ou)]


def _name_tokens(name: str) -> frozenset:
    """Accent-folded, order-independent set of name tokens (handles 'Last, First')."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    # split on whitespace, commas and hyphens so compound surnames
    # ("España-Bonet" vs "España i Bonet") still match by token subset
    return frozenset(t for t in re.split(r"[\s,\-]+", n) if t)


# Matches <a href='…viewStaffDetails?uid=UID…'>Name</a> (either quote style).
_STAFF_ANCHOR = re.compile(
    r"""<a[^>]+href=['"][^'"]*viewStaffDetails\?uid=([\w.-]+)['"][^>]*>(.*?)</a>""",
    re.S,
)


def staff_uid_by_name(s: requests.Session, name: str) -> Optional[str]:
    """Look a person up in the DFKI staff directory by surname; return uid if the
    full name matches exactly one directory entry (else None → ambiguous/unknown)."""
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if len(parts) < 2:
        return None
    lastname = parts[-1]
    url = f"{INTRANET_ROOT}/intranet/organisation/staff/viewStaff"
    try:
        html = s.get(url, params={"lastname": lastname}, timeout=60, allow_redirects=False).text
    except requests.exceptions.RequestException as e:
        logging.warning("Staff directory lookup failed (%s)", type(e).__name__)
        return None
    want = _name_tokens(name)
    matches = set()
    for m in _STAFF_ANCHOR.finditer(html):
        uid = m.group(1).strip()
        dir_name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        # accept when every token of the author's name is present in the entry
        if want and want <= _name_tokens(dir_name):
            matches.add(uid)
    if len(matches) == 1:
        return next(iter(matches))
    return None  # zero matches, or ambiguous


def fetch_staff_profile(s: requests.Session, uid: str) -> Optional[str]:
    """Return the HTML of a staff profile page (None on network error)."""
    url = f"{INTRANET_ROOT}/intranet/organisation/staff/viewStaffDetails?uid={uid}"
    try:
        return s.get(url, timeout=60, allow_redirects=False).text
    except requests.exceptions.RequestException as e:
        logging.warning("Staff profile lookup failed (%s)", type(e).__name__)
        return None


def uid_email(uid):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", uid):
        raise ValueError("Invalid staff UID")
    return uid.lower() + "@dfki.de"


def staff_roster():
    filename = os.getenv("STAFF_ROSTER")
    if not filename:
        return []
    with Path(filename).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        uid_email(row["uid"])
        if not row.get("name"):
            raise ValueError("Invalid local staff roster")
    return rows


def verwalter_uids(s: requests.Session, pubid: str) -> List[Tuple[str, str]]:
    """Ordered (uid, name) of the entry's Verwalter (managers), from the pub page."""
    url = f"{INTRANET_ROOT}/research/publications/showPublication?pubid={pubid}"
    try:
        html = s.get(url, timeout=60, allow_redirects=False).text
    except requests.exceptions.RequestException as e:
        logging.warning("Publication page lookup failed (%s)", type(e).__name__)
        return []
    idx = html.find("Verwalter:")
    if idx < 0:
        return []
    end = html.find("</table>", idx)  # the managers live in a nested table cell
    block = html[idx:end] if end > idx else html[idx:idx + 1500]
    out: List[Tuple[str, str]] = []
    for m in re.finditer(
        r"""viewStaffDetails\?uid=([\w.-]+)['"]>(.*?)</a>""", block, re.S
    ):
        uid = m.group(1).strip()
        name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if uid and (uid, name) not in out:
            out.append((uid, name))
    return out


def resolve_contacts(
    s: requests.Session, pubid: str, author_ou: str, excluded_uids: Set[str]
) -> List[Tuple[str, str, str]]:
    """Return a list of (name, email, note) to invite — empty means skip the paper.

    Two contacts are considered and both are invited when they differ:
      * the entry's Verwalter (submitter/manager), if an SLT researcher, and
      * the paper's first SLT-tagged author.
    Heads/admins in excluded_uids are never emailed (e.g. an admin Verwalter is
    skipped, leaving just the author). Duplicates are collapsed by address.
    """
    contacts: List[Tuple[str, str, str]] = []
    seen: Set[str] = set()
    roster = staff_roster()
    slt_uids = {row["uid"] for row in roster}

    # 1) First Verwalter who is an SLT researcher (and not an excluded head/admin).
    for uid, name in verwalter_uids(s, pubid):
        if uid in excluded_uids:
            continue
        if uid not in slt_uids:
            profile = fetch_staff_profile(s, uid)
            if not profile or SLT_PROFILE_MARKER not in profile:
                continue
        email = uid_email(uid)
        if email:
            contacts.append((name, email, f"Verwalter, SLT (uid={uid})"))
            seen.add(email.lower())
            break

    # 2) First SLT-tagged author we can resolve (added only if different).
    for name in slt_author_names(author_ou):
        matches = {row["uid"] for row in roster if _name_tokens(row["name"]) == _name_tokens(name)}
        if len(matches) > 1:
            continue  # ambiguous local name: never guess a recipient
        uid = next(iter(matches)) if matches else staff_uid_by_name(s, name)
        if uid and uid not in excluded_uids:
            email = uid_email(uid)
            if email:
                if email.lower() not in seen:
                    contacts.append((name, email, f"SLT author (uid={uid})"))
                    seen.add(email.lower())
                break

    return contacts


