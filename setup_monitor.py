#!/usr/bin/env python3
"""Interactive Linux setup; credentials never appear in command arguments."""
import argparse
import fcntl
import getpass
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import smtplib
import ssl
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


class SetupError(Exception):
    pass


def read_config(path):
    """Read shell-quoted assignments without executing a shell or substitutions."""
    if not path.exists():
        return {}
    config = {}
    for line in path.read_text().splitlines():
        fields = shlex.split(line, comments=True)
        if not fields:
            continue
        if len(fields) != 1 or '=' not in fields[0]:
            raise SetupError('Existing .env must contain simple KEY=value assignments')
        key, value = fields[0].split('=', 1)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise SetupError('Invalid setting name in .env')
        config[key] = value
    return config


def write_config(path, config):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            os.chmod(temp, 0o600)
            for key, value in sorted(config.items()):
                if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or '\n' in value or '\r' in value:
                    raise SetupError('Invalid configuration value')
                handle.write(f'{key}={shlex.quote(value)}\n')
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def collect_config(existing, replace=False):
    config = dict(existing)
    old_user = config.get('DFKI_USER', '')
    for key, prompt, secret in [
        ('DFKI_USER', 'DFKI username: ', False),
        ('DFKI_PASS', 'Intranet password: ', True),
        ('SMTP_PASS', 'Mail password: ', True),
    ]:
        if replace or (not config.get(key) and not config.get(key + '_FILE')) or config.get(key) in {'replace-locally', 'your-intranet-username'}:
            value = getpass.getpass(prompt) if secret else input(prompt).strip()
            if not value:
                raise SetupError(f'{key} cannot be empty')
            config[key] = value
            config.pop(key + '_FILE', None)
    if '@' in config.get('DFKI_USER', ''):
        config['DFKI_USER'] = config['DFKI_USER'].split('@', 1)[0]
    if (not config.get('SMTP_USER') and not config.get('SMTP_USER_FILE')) or config.get('SMTP_USER') == 'your-smtp-login@example.org' or (replace and config.get('SMTP_USER') == old_user + '@dfki.de'):
        config['SMTP_USER'] = config['DFKI_USER'] + '@dfki.de'
    if config.get('EXCLUDED_UIDS') is None or config.get('EXCLUDED_UIDS') == 'replace-with-your-excluded-uids':
        print('Keep heads/admins out of invitations. Enter their intranet UIDs, separated by commas.')
        value = input('Excluded UIDs (or type NONE for no exclusions): ').strip()
        if not value:
            raise SetupError('An explicit exclusion policy is required')
        config['EXCLUDED_UIDS'] = '' if value == 'NONE' else value
    config.setdefault('COLLOQUIUM_WHEN', 'Thursdays at 14:00')
    return config


def read_crontab():
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and 'no crontab for' in result.stderr.lower():
        return ''
    raise SetupError('Cannot read crontab; no schedule was changed')


def scheduled_crontab(existing, root):
    """Replace only this installation's managed block, preserving other jobs."""
    tag = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    start, end = f'# publication-monitor {tag} BEGIN', f'# publication-monitor {tag} END'
    if existing.count(start) != existing.count(end) or existing.count(start) > 1:
        raise SetupError('Malformed managed cron block')
    if start in existing:
        before, rest = existing.split(start, 1)
        _, after = rest.split(end, 1)
        existing = before + after.lstrip('\n')
    for line in existing.splitlines():
        if line.strip() and not line.lstrip().startswith('#') and ('monitor_publications' in line or 'publication-monitor' in line):
            raise SetupError('Another publication monitor is already scheduled; migrate that job before installing this one')
    # cron treats percent as a newline, including inside shell quotes.
    def cron_quote(path):
        return shlex.quote(str(path)).replace('%', r'\%')
    job = f'0 7 * * * {cron_quote(root / "monitor_publications.sh")} >> {cron_quote(root / "monitor.log")} 2>&1'
    return existing.rstrip('\n') + ('\n' if existing else '') + f'{start}\n{job}\n{end}\n'


def check_access_and_baseline():
    # Runs inside the installed venv with credentials supplied only in env.
    import monitor_publications as monitor
    print('Checking DFKI intranet access...', flush=True)
    papers = monitor.fetch_publications()
    print('Checking mail login over TLS...', flush=True)
    with smtplib.SMTP('smtp.office365.com', 587, timeout=60) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(monitor.setting('SMTP_USER'), monitor.setting('SMTP_PASS'))
    # Authentication alone cannot establish Send As permissions; no test email
    # is sent. The operator must have been granted permission by the mailbox admin.
    state = Path(os.getenv('STATE_FILE', 'state/known_publication_ids.json'))
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.with_suffix(state.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if state.exists():
            monitor.load_state(state)
            print('Existing publication history preserved.')
        else:
            monitor.save_state(state, set(papers))
            print(f'Initialized history with {len(papers)} publications. No historical invitations sent.')
    print('Intranet and mail authentication passed. No emails sent.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', action='store_true', help='Replace saved login credentials')
    parser.add_argument('--no-schedule', action='store_true', help='Set up and check access without installing a cron job')
    parser.add_argument('--check-access', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    os.umask(0o077)
    os.chdir(ROOT)
    try:
        if args.check_access:
            check_access_and_baseline()
            return 0
        if sys.version_info[:2] not in {(3, 13), (3, 14)}:
            raise SetupError('Use Python 3.13 or 3.14')
        if not args.no_schedule:
            if not shutil.which('crontab'):
                raise SetupError('Install and enable cron first, or use --no-schedule')
            existing_cron = read_crontab()
            # Refuse a duplicate installation before asking for credentials.
            proposed_cron = scheduled_crontab(existing_cron, ROOT)
        python = ROOT / '.venv/bin/python'
        if not python.exists():
            print('Creating Python environment...', flush=True)
            subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
        print('Installing dependencies...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
        print('Use a DFKI mail account authorized to send as colloquium-slt@dfki.de.')
        path = ROOT / '.env'
        config = collect_config(read_config(path), args.credentials)
        write_config(path, config)
        print('Settings saved privately in .env (owner read/write only).', flush=True)
        # Remove inherited settings so the saved configuration is authoritative.
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DFKI_', 'SMTP_')) and k not in {'STATE_FILE', 'EXCLUDED_UIDS'}}
        env.update(config)
        subprocess.run([str(python), str(ROOT / 'setup_monitor.py'), '--check-access'], env=env, check=True)
        if not args.no_schedule:
            if read_crontab() != existing_cron:
                raise SetupError('Crontab changed during setup; rerun setup to preserve those changes')
            subprocess.run(['crontab', '-'], input=proposed_cron, text=True, check=True)
            print('Daily run installed for 07:00 in the cron scheduler timezone. Keep cron and the VPN running.')
        print('Setup complete. Credentials are reused automatically. Logs: monitor.log')
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # Never echo exceptions containing credentials or raw SMTP replies.
        if isinstance(exc, SetupError):
            print(str(exc), file=sys.stderr)
        print(f'Setup stopped ({type(exc).__name__}). Check intranet/VPN access, mail login, Python/cron availability and the exclusion policy. Saved settings can be reused by rerunning ./setup.sh.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
