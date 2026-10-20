# SLT colloquium publications

A local webpage for reviewing publications and copying invitations into Outlook. No automatic emails or intranet lookups.

## Start

Python 3.11 or newer is all you need for the web interface:

```bash
python3 app.py
```

Your browser opens at **http://127.0.0.1:8765**. Keep the terminal running; press Ctrl+C to stop. The server listens only on your machine. Use `--port 8766` if the default port is occupied, or `--no-browser` to open the page yourself.

## Use

1. Click **Download CSV from intranet** to download the SLT export in your browser (DFKI network/VPN and intranet sign-in required). Then click **Import CSV** and choose the publication CSV you exported manually. The file is processed and saved locally.
2. Search by author/title or filter to entries added in the last 180 days. Click a publication title to open its intranet page in a new tab.
3. Select one or more papers. Each colleague gets a separate draft; only papers for the same colleague are grouped together. Use **Choose a colleague’s draft** to switch between them. The matched colleague name and recipient address fill in automatically. Type in **Address invitation to** for suggestions from your local roster. Choose a name with the mouse or arrow keys and Enter to update that draft’s recipient address and greeting. Existing exclusions apply. Review the invitation and edit any field as needed; changing the selection regenerates the draft, and editing the name updates its greeting.
4. Copy the current draft’s recipient, subject, and invitation into Outlook. Repeat separately for each colleague. Send manually from `colloquium-slt@dfki.de`.
5. Click **Mark this draft invited** after sending. This marks only the papers in that colleague’s draft. **Undo this draft** reverses those markers; copying alone does not mark anything.

Imports update `data/publications.json`, preserving invited markers and previously imported papers. The first import establishes a baseline; later imports highlight newly added IDs. Invalid imports leave existing data intact. Dates refer to intranet registration, and unknown dates remain visible.

For recipient suggestions, put a comma-separated `staff.csv` with `uid,name` columns in `data/`, and excluded staff UIDs in `data/excluded_uids.txt`, one per line. These private files are ignored by Git. The viewer suggests the first uniquely matched, non-excluded SLT author per paper using `uid@dfki.de`, grouping papers by recipient. Unmatched papers each get their own draft for manual review. Unmatched names require manual review. Verwalter are not included in the publication CSV.

Your existing local state and roster work without conversion. With `--state /path/to/publications.json`, the roster and exclusions are read from that same folder.

The page starts with saved publications, rather than an empty upload screen. On page load it checks for newer `publications*.csv` files beside the state file. Additional folders can be listed in the private `data/local_sources.json` file as `{"folders": ["/path/to/exports"]}`. Exports are processed oldest to newest, preserving invitation markers. A browser upload takes priority over older files on disk. Refresh the page to pick up a newly downloaded export.

An imported historical `known_ids` list records previously seen publications, not invitations. Only confirmed invitation history should be carried into `invited`; the old seen-ID cache alone cannot establish who was emailed.

## Optional separate downloader

The webpage never fetches from the intranet. Publication links require DFKI network/VPN access when you click them.

If automated intranet access is authorized, the separate CLI can download an export with one GET, without redirects or retries:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python download_csv.py --output data/publications.csv
```

It prompts for an intranet username/password without saving either. Import the downloaded file using the webpage. No scheduled jobs are installed. The previous automated workflow remains in Git history.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests use local fixtures and mocked downloads, never the intranet.
