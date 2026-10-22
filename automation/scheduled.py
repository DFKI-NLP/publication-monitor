#!/usr/bin/env python3
"""Prepare invitations in the evening; deliver the saved drafts in the morning."""
import argparse
from datetime import datetime
import fcntl
import json
import logging
from pathlib import Path
import os
import tempfile
from zoneinfo import ZoneInfo

import monitor_publications as monitor


def save(path, data):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def prepare(state, queue):
    known = monitor.load_state(state)
    papers = monitor.fetch_publications()
    if known is None:
        monitor.save_state(state, set(papers))
        return
    queued_ids = set()
    for path in queue.glob('*.json'):
        queued_ids.update(json.loads(path.read_text())['ids'])
    new = {i: papers[i] for i in sorted(set(papers) - known - queued_ids)}
    if new:
        invitations, skipped = monitor.plan_invitations(new)
        for rec in invitations:
            rec['status'] = 'pending'
        batch = {'ids': list(new), 'invitations': invitations, 'skipped': skipped, 'digest': 'pending'}
        stamp = datetime.now(ZoneInfo('Europe/Berlin')).strftime('%Y%m%d-%H%M%S-%f')
        save(queue / (stamp + '.json'), batch)
        logging.info('Queued %d invitations for the next morning', len(invitations))
    # Queue is durable before IDs become known; queued IDs prevent duplicate planning.
    monitor.save_state(state, known | set(papers) | queued_ids)


def send(queue):
    errors = False
    for path in sorted(queue.glob('*.json')):
        batch = json.loads(path.read_text())
        if batch['digest'] != 'pending':
            continue
        for rec in batch['invitations']:
            if rec['status'] != 'pending':
                continue
            # Persist before SMTP: interrupted sends need review, never blind resending.
            rec['status'] = 'sending'
            save(path, batch)
            try:
                monitor.send_email('Invitation to present at the DFKI SLT Colloquium',
                                   monitor.invitation_body(rec), [rec['email']])
                rec['status'] = 'sent'
            except Exception:
                rec['status'] = 'failed'
            save(path, batch)
        failed = {rec['email'].lower() for rec in batch['invitations'] if rec['status'] != 'sent'}
        errors |= bool(failed)
        batch['digest'] = 'sending'
        save(path, batch)
        try:
            monitor.send_digest(batch['invitations'], batch['skipped'], failed)
            batch['digest'] = 'sent'
        except Exception:
            batch['digest'] = 'failed'
            errors = True
        save(path, batch)
    if errors:
        raise RuntimeError('Some queued deliveries failed or have an uncertain outcome; review the queue and digest.')


def run(action, state):
    queue = state.parent / 'invitation-queue'
    queue.mkdir(exist_ok=True, mode=0o700)
    with state.with_suffix(state.suffix + '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another scheduled step is still running.')
        if action == 'prepare':
            prepare(state, queue)
        else:
            send(queue)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'send'))
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        run(args.action, args.state)
    except Exception as exc:
        logging.error('Scheduled step failed (%s); review local queue and journal.', type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
