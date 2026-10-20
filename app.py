#!/usr/bin/env python3
"""Local web interface for manually exported publication CSVs."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import time
from pathlib import Path
import webbrowser

import publications as pub
import local_sources

ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content_type='application/json'):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin', 'http://' + self.headers.get('Host', '')) in {'http://' + host for host in hosts}

    def do_GET(self):
        if not self.local_request():
            return self.reply(403, {'error': 'Local requests only.'})
        if self.path == '/api/publications':
            try:
                self.server.data, warnings = local_sources.refresh(self.server.state, self.server.data)
            except (OSError, ValueError, KeyError) as exc:
                warnings = [str(exc)]
            data = self.server.data
            papers = []
            for key, paper in data['papers'].items():
                added = pub.added_date(paper)
                papers.append({k: paper.get(k, '') for k in ('id', 'title', 'author', 'creationdate')} | {
                    'date': added.isoformat() if added else '',
                    'invited': key in data['invited'], 'new': key in data['new']})
            return self.reply(200, {'papers': papers, 'export_url': pub.EXPORT_URL, 'warnings': warnings})
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path not in assets:
            return self.reply(404, {'error': 'Not found.'})
        name, kind = assets[self.path]
        self.reply(200, (ROOT / 'web' / name).read_bytes(), kind)

    def do_POST(self):
        if not self.local_request() or self.headers.get('Content-Type') != 'application/json':
            return self.reply(403, {'error': 'Local JSON requests only.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 25 * 1024 * 1024:
                raise ValueError('Choose a CSV smaller than 25 MB.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Expected an object.')
            data = self.server.data
            if self.path == '/api/import':
                if not isinstance(body.get('csv'), str):
                    raise ValueError('Upload a CSV text file.')
                papers = pub.parse_csv(body['csv'])
                updated = pub.merge_papers(papers, data)
                updated['local_csv_mtime'] = time.time_ns()
                self.save(updated)
                return self.reply(200, {'imported': len(papers), 'new': len(updated['new'])})
            ids = body['ids']
            if not isinstance(ids, list) or any(not isinstance(key, str) or key not in data['papers'] for key in ids):
                raise ValueError('Select existing publications.')
            if self.path == '/api/drafts':
                papers = [data['papers'][key] for key in ids]
                staff = pub.load_staff(self.server.state.parent)
                return self.reply(200, {'drafts': pub.invitation_groups(papers, staff)})
            if self.path == '/api/draft':
                papers = [data['papers'][key] for key in ids]
                staff = pub.load_staff(self.server.state.parent)
                if len(pub.invitation_groups(papers, staff)) > 1:
                    raise ValueError('Prepare a separate invitation for each colleague.')
                names = [row['name'] for row in pub.matched_contacts(papers, staff)]
                suggested_name = ' and '.join(names)
                name = body.get('name', suggested_name)
                if not isinstance(name, str):
                    raise ValueError('Name must be text.')
                addresses = pub.recipients(papers, staff)
                missing = sum(not pub.recipients([paper], staff) for paper in papers)
                return self.reply(200, {'name': name, 'body': pub.invitation(papers, name), 'subject': pub.SUBJECT, 'recipients': '; '.join(addresses), 'unmatched': missing})
            if self.path == '/api/mark':
                if type(body.get('invited')) is not bool:
                    raise ValueError('Invited must be true or false.')
                marked = set(data['invited'])
                marked = marked | set(ids) if body['invited'] else marked - set(ids)
                self.save(dict(data, invited=sorted(marked, key=int)))
                return self.reply(200, {'ok': True})
            self.reply(404, {'error': 'Not found.'})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.reply(400, {'error': str(exc)})

    def save(self, data):
        pub.save_text(self.server.state, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        self.server.data = data


def make_server(state, port=8765):
    data = pub.load(state)
    server = HTTPServer(('127.0.0.1', port), Handler)
    server.state, server.data = state, data
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--state', type=Path, default=ROOT / 'data/publications.json')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    server = make_server(args.state, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Publications: {url}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
