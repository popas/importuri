#!/usr/bin/env python3
"""The candidates file as a work queue. A continuous session has no /clear between
watches and nothing external tracking progress, so 'which watch is next' has to be a
command, not something the model remembers."""
import json, os, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
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

# --- the logger turns a marker line into a history entry --------------------
import subprocess, tempfile as _tf
_dir = _tf.mkdtemp()
_hist = os.path.join(_dir, "history.jsonl")
_state = os.path.join(_dir, "state.json")
json.dump({"session_imported": 4, "session_skipped": 1, "status": "running"},
          open(_state, "w"))
_line = ('RESULT: {"ad_id":"307673714","ok":true,"state_entry":'
         '{"source":"olx","id":"307673714","brand":"Garmin","model":"Fenix 7X Solar",'
         '"price":1700,"currency":"RON","images":3}}')
_p = subprocess.run([sys.executable,
                     os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-log-result.py"),
                     "--history", _hist, "--state", _state],
                    input=_line, capture_output=True, text=True)
check(_p.returncode == 0, "logger: exit %d, stderr %s" % (_p.returncode, _p.stderr[:200]))
_rec = json.loads(open(_hist).read().strip())
check(_rec["event"] == "import", "logger: event not set")
check(_rec["id"] == "307673714" and _rec["brand"] == "Garmin", "logger: state_entry not copied")
check(_rec.get("ts"), "logger: ts not set")
check(json.load(open(_state))["session_imported"] == 5, "logger: counter not bumped")

_skip = 'SKIP: {"ad_id":"111","reason":"thin_description","source":"olx"}'
subprocess.run([sys.executable,
                os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-log-result.py"),
                "--history", _hist, "--state", _state],
               input=_skip, capture_output=True, text=True)
check(len(open(_hist).read().strip().splitlines()) == 2, "logger: skip not appended")
check(json.load(open(_state))["session_skipped"] == 2, "logger: skip counter not bumped")

# an UNVERIFIED import must never be recorded as a success
_bad = 'RESULT: {"ad_id":"222","ok":false,"state_entry":{"id":"222","brand":"X"}}'
_p = subprocess.run([sys.executable,
                     os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-log-result.py"),
                     "--history", _hist, "--state", _state],
                    input=_bad, capture_output=True, text=True)
check(len(open(_hist).read().strip().splitlines()) == 2,
      "logger: an unverified RESULT (ok:false) must append nothing")
check(json.load(open(_state))["session_imported"] == 5,
      "logger: an unverified RESULT must not bump the counter")

# a line that is not a marker is a no-op, not a crash
_p = subprocess.run([sys.executable,
                     os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-log-result.py"),
                     "--history", _hist, "--state", _state],
                    input="EXTRACT: {}", capture_output=True, text=True)
check(_p.returncode == 0 and "NOT_LOGGED" in _p.stdout, "logger: a non-marker line must be a no-op")

# `queues`: every queue file in the harness dir, most pending first, as a table
_root = tempfile.mkdtemp()
_h = os.path.join(_root, "harness/3ceasuri-import")
os.makedirs(_h)
def _queue(name, statuses, profile="smart", generated="2026-11-01T10:00:00", where=_h):
    json.dump({"generated": generated, "profile": profile,
               "candidates": [{"id": str(i), "status": s} for i, s in enumerate(statuses)]},
              open(os.path.join(where, name), "w"))
_queue(".candidates-olx-smart-a.json", ["pending", "imported", "skipped"])
_queue(".candidates-olx-watches-b.json", ["pending"] * 3 + ["error"], profile="classic",
       generated="2026-10-01T10:00:00")
_queue(".candidates-olx-smart-c.json", ["pending", "pending", "imported"],
       generated="2026-11-05T10:00:00")
_queue(".candidates-olx-smart-done.json", ["imported", "skipped"])
open(os.path.join(_h, ".candidates-olx-torn.json"), "w").write('{"candidates": [')
open(os.path.join(_h, "not-a-queue.json"), "w").write("{}")

_rows = candidates.summary(_h)
check([r["file"] for r in _rows] == [".candidates-olx-watches-b.json",
                                     ".candidates-olx-smart-c.json",
                                     ".candidates-olx-smart-a.json",
                                     ".candidates-olx-smart-done.json",
                                     ".candidates-olx-torn.json"],
      "queues: order must be most pending first, then the newer queue: %s"
      % [r["file"] for r in _rows])
_b = _rows[0]
check((_b["pending"], _b["error"], _b["profile"], _b["generated"]) == (3, 1, "classic", "2026-10-01"),
      "queues: row fields wrong: %s" % _b)
check("unreadable" in _rows[-1], "queues: a torn file must be a row marked unreadable, not a crash")

_out = candidates.report(_h, _root)
_lines = _out.splitlines()
check(_lines[0].startswith("| Coadă") and _lines[1].startswith("|:-"),
      "queues: the table header is missing: %r" % _lines[:2])
_table = _lines[:_lines.index("")]
check(len(_table) == 6 and len({len(l) for l in _table}) == 1,
      "queues: header + separator + 4 shown queues, all the same width: %r" % _table)
check("smart-done" not in _out, "queues: an empty queue is hidden without --all")
check("nu se poate citi" in _out, "queues: an unreadable queue must still be shown")
check("cozi goale ascunse: 1" in _out, "queues: the hidden count is missing")
check("olx-loop.py harness/3ceasuri-import/.candidates-olx-watches-b.json --target 10" in _out,
      "queues: the start command must name the queue with the most pending")
check("smart-done" in candidates.report(_h, _root, show_all=True), "queues: --all shows empty ones")

# a session still open on a queue: marked, and it is the one the command resumes
json.dump({"status": "running", "queue": "harness/3ceasuri-import/.candidates-olx-smart-a.json"},
          open(os.path.join(_root, "state.json"), "w"))
_out = candidates.report(_h, _root)
check(".candidates-olx-smart-a.json *" in _out and "sesiune deschisă" in _out,
      "queues: the queue with an open session must be marked")
check("olx-loop.py harness/3ceasuri-import/.candidates-olx-smart-a.json" in _out,
      "queues: an open session must be the queue the start command resumes")

# nothing pending anywhere: say how to make a new queue instead of a start command
_e = tempfile.mkdtemp()
_queue(".candidates-olx-smart-x.json", ["imported"], where=_e)
_out = candidates.report(_e, _root)
check("Creează una" in _out and "olx-loop.py" not in _out,
      "queues: with nothing pending it must point to queue creation: %r" % _out)
check("Creează una" in candidates.report(tempfile.mkdtemp(), _root),
      "queues: no queue files at all must point to queue creation")

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
