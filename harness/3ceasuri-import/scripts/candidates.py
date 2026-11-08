#!/usr/bin/env python3
"""The candidates file as a work queue.

§6 decision 7 made the Haiku run one continuous session with no /clear between
watches, so nothing external tracks progress and "take the next unimported id"
cannot mean "remember which ones you did". Each candidate carries its own status,
written by the importer, so the queue survives a crash, a context checkpoint and a
fresh session equally well.

Also usable from the shell, deliberately without a browser:
    python3 candidates.py next   harness/3ceasuri-import/.candidates-olx-smart.json
    python3 candidates.py counts harness/3ceasuri-import/.candidates-olx-smart.json
    python3 candidates.py queues [--all]    every queue and what it has left, as a table
"""

import glob
import json
import os
import sys
import time

STATUSES = ("pending", "imported", "skipped", "error")


def load(path):
    with open(path) as f:
        return json.load(f)


def _save(path, doc):
    with open(path, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def next_pending(path):
    """The first candidate still to do, or None. Absent status counts as pending —
    files written before the queue existed are still usable."""
    for c in load(path).get("candidates", []):
        if c.get("status", "pending") == "pending":
            return c
    return None


def mark(path, ad_id, status, reason=None):
    """Record an outcome. Returns False when the id is not in this file.

    Ids are compared as strings: discovery writes whatever the OLX JSON held (an
    int), while AD_ID always arrives from the environment as a str.
    """
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % (STATUSES,))
    doc = load(path)
    for c in doc.get("candidates", []):
        if str(c.get("id")) == str(ad_id):
            c["status"] = status
            c["reason"] = reason
            c["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save(path, doc)
            return True
    return False


def history_imported(history_path):
    """Every ad id history.jsonl records as imported. Local knowledge only: it may
    steer how much work to do, never whether a watch is on the site (the admin is
    the ground truth for that)."""
    ids = set()
    try:
        with open(history_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("event") == "import" and r.get("id"):
                    ids.add(str(r["id"]))
    except OSError:
        pass
    return ids


def _count(doc):
    out = dict.fromkeys(STATUSES, 0)
    for c in doc.get("candidates", []):
        key = c.get("status", "pending")
        out[key] = out.get(key, 0) + 1
    return out


def counts(path):
    return _count(load(path))


def summary(directory):
    """One row per queue (.candidates-*.json) in `directory`: most pending first,
    the newer queue first among equals. A file that does not parse is a row with
    `unreadable`, not a crash -- one torn write must not hide every other queue."""
    rows = []
    for path in glob.glob(os.path.join(os.path.abspath(directory), ".candidates-*.json")):
        row = {"file": os.path.basename(path), "path": path}
        try:
            doc = load(path)
            row.update(_count(doc), profile=doc.get("profile") or "?",
                       generated=str(doc.get("generated") or "")[:10])
        except (OSError, ValueError, AttributeError) as e:
            row["unreadable"] = str(e) or type(e).__name__
        rows.append(row)
    rows.sort(key=lambda r: r["file"])
    rows.sort(key=lambda r: r.get("generated", ""), reverse=True)
    rows.sort(key=lambda r: r.get("pending", -1), reverse=True)
    return rows


HEADERS = ("Coadă", "Tip", "Pending", "Importate", "Sărite", "Erori", "Generată")
NUMERIC = (False, False, True, True, True, True, False)


def table(rows, running=None):
    """`rows` from summary() as an aligned Markdown table: readable in a terminal,
    pasteable as is. The queue `running` (a path) gets a ` *`."""
    cells = [HEADERS]
    for r in rows:
        name = r["file"] + (" *" if running and r["path"] == running else "")
        if "unreadable" in r:
            cells.append((name, "?", "-", "-", "-", "-", "nu se poate citi"))
        else:
            cells.append((name, r["profile"], r["pending"], r["imported"],
                          r["skipped"], r["error"],
                          r["generated"] or "-"))
    cells = [tuple(str(c) for c in row) for row in cells]
    widths = [max(len(row[i]) for row in cells) for i in range(len(HEADERS))]

    def line(row):
        return "| " + " | ".join(c.rjust(w) if num else c.ljust(w)
                                 for c, w, num in zip(row, widths, NUMERIC)) + " |"
    sep = "|" + "|".join("-" * (w + 1) + ":" if num else ":" + "-" * (w + 1)
                         for w, num in zip(widths, NUMERIC)) + "|"
    return "\n".join([line(cells[0]), sep] + [line(row) for row in cells[1:]])


def running_queue(root):
    """The queue state.json says a session is still open on, as an absolute path."""
    try:
        with open(os.path.join(root, "state.json")) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    if state.get("status") == "running" and state.get("queue"):
        return os.path.abspath(os.path.join(root, state["queue"]))
    return None


NEW_QUEUE_DOC = "docs/handover/2026-11-08-olx-loop-script.md, „Cum creezi o coadă nouă”"


def report(harness, root, show_all=False):
    """What `candidates.py queues` prints: the table, a totals line, and the command
    that starts the loop on the queue to take next."""
    rows = summary(harness)
    if not rows:
        return "Nicio coadă în %s.\nCreează una: %s" % (harness, NEW_QUEUE_DOC)
    running = running_queue(root)
    shown = rows if show_all else [r for r in rows if r.get("pending") or "unreadable" in r]
    hidden = len(rows) - len(shown)
    with_pending = [r for r in rows if r.get("pending")]
    out = []
    if shown:
        out += [table(shown, running), ""]
    out.append("cozi cu pending: %d · anunțuri pending: %d%s" % (
        len(with_pending), sum(r["pending"] for r in with_pending),
        " · cozi goale ascunse: %d (--all le arată)" % hidden if hidden else ""))
    if running and any(r["path"] == running for r in shown):
        out.append("* sesiune deschisă: aceeași comandă o reia; un --target nou e ignorat "
                   "până la `olx-step.py stop <coada>`")
    if not with_pending:
        out.append("Nicio coadă nu mai are anunțuri pending. Creează una: " + NEW_QUEUE_DOC)
        return "\n".join(out)
    first = next((r for r in with_pending if r["path"] == running), with_pending[0])
    out.append("Pornește: python3 harness/3ceasuri-import/scripts/olx-loop.py %s --target 10"
               % os.path.relpath(first["path"], root))
    return "\n".join(out)


USAGE = "usage: candidates.py next|counts <file>   |   candidates.py queues [--all]"

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "queues":
        harness = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        print(report(harness, os.path.dirname(os.path.dirname(harness)),
                     show_all="--all" in sys.argv[2:]))
        sys.exit(0)
    if len(sys.argv) < 3:
        print(USAGE)
        sys.exit(2)
    cmd, target = sys.argv[1], sys.argv[2]
    if cmd == "next":
        c = next_pending(target)
        if not c:
            print("QUEUE_EMPTY")
            sys.exit(1)
        print(c["id"])
    elif cmd == "counts":
        print(json.dumps(counts(target)))
    else:
        print(USAGE)
        sys.exit(2)
