# Public papers → local invitations

This workflow uses **OpenAlex only**, with no DFKI intranet requests, SMTP connections, mailbox automation, or DFKI credentials. You review the drafts and send them yourself. It is separate from the disabled intranet job. Do not run `setup.sh` for this workflow: that sets up the original intranet monitor.

## Try it without network access

With the repository's Python environment installed:

```bash
.venv/bin/python public_monitor.py --state state/demo-public.json scan \
  --team examples/team.csv --fixture examples/openalex-works.json \
  --days 3660 --output drafts/demo
```

Open the reported `review.md`. Each entry has a public paper link, a copyable `.txt` invitation, and an `.eml` file. The example author/work IDs are synthetic; do not send the example invitation.

For a fresh clone, create `.venv` with Python 3.13 or 3.14 and install `requirements.txt`; no setup wizard or DFKI login is needed.

## Configure your team once

Copy `examples/team.csv` to `team.csv`. Replace the examples with verified names, email addresses and OpenAlex author IDs. Find each person at [OpenAlex](https://openalex.org/) and check their publications to distinguish people with similar names. Use the `A…` ID from their author record. Email addresses must come from your own verified contact list, not guessed names. Set `enabled` to `false` for people who should not receive invitations. The local roster is ignored by Git.

The first enabled team member in each paper's author order is selected. There is no Verwalter field in this public source. Check the chosen recipient before sending.

Create a free OpenAlex account, verify your email, and copy its API key from [Settings](https://openalex.org/settings/api). Save it with hidden input:

```bash
.venv/bin/python public_monitor.py save-key
```

The key is stored in `secrets/openalex-api-key` with owner-only permissions. It is not a DFKI password. [OpenAlex authentication and usage limits](https://help.openalex.org/api/authentication/).

## Check public publications

```bash
.venv/bin/python public_monitor.py scan --team team.csv --live
```

This explicitly contacts `https://api.openalex.org/works`. It requests the last 180 days by verified author ID, paginates, waits between requests, and backs off on temporary errors. The first scan includes existing recent publications: review or dismiss already-invited papers, because intranet IDs cannot be matched automatically to public records. No historical email is sent.

Later scans reuse `state/public-monitor.json`. Identical OpenAlex IDs or DOIs are merged. Papers with matching titles but different IDs/DOIs are flagged for review rather than assumed to be identical. Indexing delays and author-assignment mistakes are possible; repeated scans of the rolling date window catch newly indexed papers within that window. Increase `--days` if needed. This does not guarantee complete coverage.

Review the newest output folder; older folders are snapshots and can contain drafts since marked sent. After sending one invitation in Outlook from the shared mailbox, record its ID from the review:

```bash
.venv/bin/python public_monitor.py mark REVIEW_ID --status sent
```

For an irrelevant paper or duplicate version, use `--status dismissed`. Use `--status pending` to undo a decision. These commands only update local state; none sends email.

## Optional daily discovery

Once the roster and results have been checked, the public scan can be scheduled. The following is an example only; no job is installed automatically:

```cron
0 7 * * * cd /absolute/path/publication-monitor && .venv/bin/python public_monitor.py scan --team team.csv --live >> public-monitor.log 2>&1
```

This creates local review files; it does not deliver notifications or invitations. The machine needs ordinary Internet access, not the DFKI VPN. Keep your roster, key, state and drafts private. The old intranet job should remain disabled.
