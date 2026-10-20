#!/usr/bin/env python3
"""Offline publication viewer. Import CSV files and copy invitation text."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import publications as pub


class Viewer:
    def __init__(self, window, state):
        self.window, self.state = window, state
        self.data = pub.load(state)
        self.staff = pub.load_staff(state.parent)
        window.title('SLT Colloquium · Publications')
        window.geometry('1100x760')
        window.minsize(850, 600)
        outer = ttk.Frame(window, padding=12)
        outer.pack(fill='both', expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x', pady=(0, 10))
        ttk.Button(toolbar, text='Import CSV…', command=self.choose_csv).pack(side='left')
        ttk.Label(toolbar, text='Search:').pack(side='left', padx=(15, 5))
        self.search = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.search, width=35).pack(side='left')
        self.recent = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='Added in the last 180 days', variable=self.recent, command=self.refresh).pack(side='left', padx=15)
        self.search.trace_add('write', lambda *_: self.refresh())
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('status', 'added', 'title', 'authors'), show='headings', selectmode='extended')
        for column, title, width in [('status', 'Status', 80), ('added', 'Added', 100), ('title', 'Publication', 520), ('authors', 'Authors', 260)]:
            self.table.heading(column, text=title)
            self.table.column(column, width=width, stretch=column in ('title', 'authors'))
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        self.table.tag_configure('new', background='#e8f3ff')
        self.table.bind('<<TreeviewSelect>>', lambda _: self.preview())
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=10)
        ttk.Label(controls, text='Address invitation to:').pack(side='left')
        self.name = tk.StringVar()
        ttk.Entry(controls, textvariable=self.name, width=25).pack(side='left', padx=8)
        self.name.trace_add('write', lambda *_: self.preview())
        self.copy_button = ttk.Button(controls, text='Copy invitation', command=self.copy)
        self.copy_button.pack(side='left', padx=5)
        ttk.Button(controls, text='Copy subject', command=lambda: self.clipboard(pub.SUBJECT)).pack(side='left')
        ttk.Button(controls, text='Mark invited', command=lambda: self.mark(True)).pack(side='right')
        ttk.Button(controls, text='Undo invited', command=lambda: self.mark(False)).pack(side='right', padx=5)
        recipients = ttk.Frame(outer)
        recipients.pack(fill='x', pady=(0, 8))
        ttk.Label(recipients, text='Suggested author recipients:').pack(side='left')
        self.addresses = tk.StringVar()
        ttk.Entry(recipients, textvariable=self.addresses).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(recipients, text='Copy recipients', command=lambda: self.clipboard(self.addresses.get())).pack(side='right')
        self.text = tk.Text(outer, height=14, wrap='word', padx=10, pady=10)
        self.text.pack(fill='both', expand=True)
        self.text.configure(state='disabled')
        self.status = ttk.Label(outer)
        self.status.pack(anchor='w', pady=(8, 0))
        ttk.Label(outer, text='Offline · Copying does not send or mark anything invited. Send manually from ' + pub.MAILBOX).pack(anchor='w')
        self.refresh()

    def persist(self):
        pub.save_text(self.state, json.dumps(self.data, ensure_ascii=False, indent=2) + '\n')

    def choose_csv(self):
        filename = filedialog.askopenfilename(title='Choose a manually exported publication CSV', filetypes=[('CSV files', '*.csv'), ('All files', '*')])
        if filename:
            self.import_file(Path(filename))

    def import_file(self, path):
        try:
            updated = pub.import_csv(path, self.data)
            pub.save_text(self.state, json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
            self.data = updated
            self.refresh()
        except (ValueError, OSError) as exc:
            messagebox.showerror('Could not import CSV', str(exc))

    def refresh(self):
        selection = set(self.table.selection())
        self.table.delete(*self.table.get_children())
        query = self.search.get().casefold().strip()
        cutoff = date.today() - timedelta(days=180)
        papers = sorted(self.data['papers'].items(), key=lambda item: (pub.added_date(item[1]) or date.min, int(item[0])), reverse=True)
        for key, paper in papers:
            added = pub.added_date(paper)
            if self.recent.get() and added is not None and added < cutoff:
                continue
            if query and query not in (paper['title'] + ' ' + paper.get('author', '')).casefold():
                continue
            status = 'Invited' if key in self.data['invited'] else 'New' if key in self.data['new'] else ''
            self.table.insert('', 'end', iid=key, values=(status, paper.get('creationdate', ''), paper['title'], paper.get('author', '')), tags=('new',) if status == 'New' else ())
        visible = set(self.table.get_children())
        self.table.selection_set(list(selection & visible))
        self.status.configure(text=f"{len(visible)} shown · {len(self.data['papers'])} saved · {len(self.data['new'])} new on last import · {len(self.data['invited'])} marked invited")
        self.preview()

    def preview(self):
        papers = [self.data['papers'][key] for key in self.table.selection()]
        self.addresses.set('; '.join(pub.recipients(papers, self.staff)))
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', pub.invitation(papers, self.name.get()) if papers else 'Import a CSV and select one or more publications. Enter the addressee’s name, then copy the invitation into Outlook.')
        self.text.configure(state='disabled')
        self.copy_button.configure(state='normal' if papers else 'disabled')

    def clipboard(self, text):
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        self.status.configure(text='Copied. Keep this window open until you paste into Outlook.')

    def copy(self):
        if self.table.selection():
            self.clipboard(self.text.get('1.0', 'end-1c'))

    def mark(self, invited):
        selected = set(self.table.selection())
        if not selected:
            return
        previous = list(self.data['invited'])
        self.data['invited'] = sorted((set(previous) | selected) if invited else (set(previous) - selected), key=int)
        try:
            self.persist()
        except OSError as exc:
            self.data['invited'] = previous
            messagebox.showerror('Could not save', str(exc))
        self.refresh()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', nargs='?', type=Path, help='Optional CSV to import on opening')
    parser.add_argument('--state', type=Path, default=Path(__file__).resolve().parent / 'data/publications.json')
    args = parser.parse_args()
    window = tk.Tk()
    try:
        app = Viewer(window, args.state)
    except (OSError, ValueError) as exc:
        messagebox.showerror('Could not load saved publications', str(exc))
        window.destroy()
        return
    if args.csv:
        app.import_file(args.csv)
    window.mainloop()


if __name__ == '__main__':
    main()
