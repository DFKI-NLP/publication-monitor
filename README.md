# SLT colloquium publications

A small desktop tool for reviewing publications and copying invitation text into Outlook. No email sending, contact lookups, stored passwords, or scheduled jobs.

## Open a CSV

Use Python 3.11 or newer with Tkinter installed. On Debian/Ubuntu, Tkinter is provided by `python3-tk`.

```bash
python3 viewer.py /path/to/publications.csv
```

You can also open `viewer.py` without a filename and click **Import CSV**.

- Publications are sorted by their intranet registration date; search by title or author.
- The recent filter shows entries added in the last 180 days. Unknown registration dates stay visible. Missing publication years do not hide papers.
- Select one or more papers, enter the addressee’s name, and click **Copy invitation**. Use **Copy subject** for the subject line.
- Paste into Outlook, choose the recipient, and send manually from `colloquium-slt@dfki.de`.
- After sending, click **Mark invited**. Copying alone does not mark anything.

Imports update `data/publications.json`, keeping your invited markers and previously imported papers. The first import establishes a baseline; later imports highlight newly added IDs. This does not infer who was invited by earlier tools. Keep the window open until you paste, since clipboard persistence depends on the desktop environment.

## Optional manual download

The viewer has no network access. You can export the CSV manually in your browser and import it.

If automated intranet access has been authorized, the separate downloader makes **one GET request**, validates the CSV, and saves it locally. It does not follow redirects, retry, look up contacts, or run on a schedule.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python download_csv.py --output data/publications.csv
python3 viewer.py data/publications.csv
```

The downloader prompts for your intranet username and password; neither is saved. DFKI network/VPN access is required. Downloading does not launch the viewer or update its history until you import the file.

## Files

- `publications.py` — CSV parsing, local storage, invitation wording.
- `viewer.py` — offline desktop window and clipboard.
- `download_csv.py` — optional, manually invoked CSV request.

This version replaces the earlier automated discovery and invitation workflow. Earlier code remains in Git history. The original job remains disabled; this version does not install a replacement job.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Download tests use mocked responses and never contact the intranet.
