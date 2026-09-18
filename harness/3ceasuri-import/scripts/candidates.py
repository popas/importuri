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
"""

import json
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


def counts(path):
    out = dict.fromkeys(STATUSES, 0)
    for c in load(path).get("candidates", []):
        key = c.get("status", "pending")
        out[key] = out.get(key, 0) + 1
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: candidates.py next|counts <file>")
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
        print("usage: candidates.py next|counts <file>")
        sys.exit(2)
