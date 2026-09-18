#!/usr/bin/env python3
"""The candidates file as a work queue. A continuous session has no /clear between
watches and nothing external tracking progress, so 'which watch is next' has to be a
command, not something the model remembers."""
import json, os, sys, tempfile

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import candidates

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

path = os.path.join(tempfile.mkdtemp(), "c.json")
json.dump({"generated": "2026-09-19T10:00:00", "source": "olx", "profile": "smart",
           "category": 1943,
           "candidates": [{"id": "1", "title": "a"},
                          {"id": "2", "title": "b"},
                          {"id": "3", "title": "c"}]}, open(path, "w"))

# 1. a candidate with no status is pending
n = candidates.next_pending(path)
check(n and n["id"] == "1", "1: first pending should be 1, got %r" % (n or {}).get("id"))

# 2. marking advances the queue
candidates.mark(path, "1", "imported")
n = candidates.next_pending(path)
check(n and n["id"] == "2", "2: after marking 1, next should be 2, got %r" % (n or {}).get("id"))

# 3. a skip records the reason and the timestamp
candidates.mark(path, "2", "skipped", "thin_description")
rec = [c for c in candidates.load(path)["candidates"] if c["id"] == "2"][0]
check(rec["status"] == "skipped", "3: status not written")
check(rec["reason"] == "thin_description", "3: reason not written")
check(rec.get("ts"), "3: ts not written")

# 4. counts are readable without parsing by hand
c = candidates.counts(path)
check(c == {"pending": 1, "imported": 1, "skipped": 1, "error": 0}, "4: counts wrong: %s" % c)

# 5. an exhausted queue returns None rather than raising
candidates.mark(path, "3", "imported")
check(candidates.next_pending(path) is None, "5: exhausted queue must return None")

# 6. marking an unknown id is reported, not silently ignored
check(candidates.mark(path, "999", "imported") is False, "6: unknown id must return False")

# 7. marking is idempotent and does not corrupt the file's own metadata
candidates.mark(path, "3", "imported")
d = candidates.load(path)
check(d["profile"] == "smart" and d["category"] == 1943, "7: file metadata lost on write")
check(len(d["candidates"]) == 3, "7: candidates lost on write")

# 8. an int id in the file matches a str id from the environment, and vice versa
path2 = os.path.join(tempfile.mkdtemp(), "c2.json")
json.dump({"candidates": [{"id": 307673714, "title": "int id"}]}, open(path2, "w"))
check(candidates.mark(path2, "307673714", "imported") is True,
      "8: a str ad id must match an int id in the file -- AD_ID is always a str")

# 9. an illegal status is a programming error, not a silent write
try:
    candidates.mark(path, "3", "done")
    check(False, "9: an unknown status must raise")
except ValueError:
    pass

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
