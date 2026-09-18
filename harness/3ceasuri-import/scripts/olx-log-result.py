#!/usr/bin/env python3
"""Turn an importer marker line into a history entry and a counter bump.

Run with python3 — this one is NOT a browser-use payload:
    <the RESULT: or SKIP: line> | python3 olx-log-result.py

history.jsonl is append-only and never read back in bulk: an append cannot drift
the way a counter does (the old state.json counter reached 33 while the site held
80+). state.json holds session bookkeeping only, by design.
"""

import argparse
import json
import os
import sys
import time

DEFAULT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")


def parse(line):
    """(event, record) from a marker line, or (None, None) if it is not one."""
    line = (line or "").strip()
    for tag, event in (("RESULT:", "import"), ("SKIP:", "skip")):
        if line.startswith(tag):
            try:
                payload = json.loads(line[len(tag):])
            except ValueError:
                return None, None
            if event == "import":
                # An unverified import is not an import. Recording it would put a
                # watch in history that the admin never saved -- and the admin is
                # ground truth, so the two must never disagree in that direction.
                if not payload.get("ok"):
                    return None, None
                rec = dict(payload.get("state_entry") or {})
            else:
                rec = {"id": payload.get("ad_id"), "source": payload.get("source", "olx"),
                       "reason": payload.get("reason")}
            rec["event"] = event
            rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            return event, rec
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=os.path.join(DEFAULT_ROOT, "history.jsonl"))
    ap.add_argument("--state", default=os.path.join(DEFAULT_ROOT, "state.json"))
    args = ap.parse_args()

    # The importer prints several marker lines; take the last RESULT:/SKIP: in the
    # stream so the whole stdout can be piped in without pre-filtering it.
    event, rec = (None, None)
    for line in sys.stdin.read().splitlines():
        e, r = parse(line)
        if e:
            event, rec = e, r
    if not event:
        print("NOT_LOGGED: no RESULT:/SKIP: line, or the import was not verified")
        return 0

    with open(args.history, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    try:
        with open(args.state) as f:
            state = json.load(f)
    except Exception:
        state = {}
    key = "session_imported" if event == "import" else "session_skipped"
    state[key] = int(state.get(key, 0)) + 1
    with open(args.state, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print("LOGGED: " + json.dumps({"event": event, "id": rec.get("id")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
