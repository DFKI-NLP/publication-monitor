"""Import newer local exports when the viewer starts or the page reloads."""
import json
from pathlib import Path

import publications as pub


def refresh(state, data):
    config = state.parent / 'local_sources.json'
    folders = [state.parent]
    if config.exists():
        folders += [Path(p).expanduser() for p in json.loads(config.read_text())['folders']]
    files = {path.resolve() for folder in folders for path in folder.glob('publications*.csv')}
    watermark = data.get('local_csv_mtime', 0)
    pending = sorted((p for p in files if p.stat().st_mtime_ns > watermark), key=lambda p: (p.stat().st_mtime_ns, str(p)))
    updated = data
    warnings = []
    for path in pending:
        try:
            stamp = path.stat().st_mtime_ns
            papers = pub.parse_csv(path.read_text(encoding='utf-8-sig'))
            updated = pub.merge_papers(papers, updated)
            updated['local_csv_mtime'] = stamp
        except (ValueError, OSError) as exc:
            warnings.append(f'{path.name}: {exc}')
    if updated is not data:
        pub.save_text(state, json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
    return updated, warnings
