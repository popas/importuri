#!/usr/bin/env python3
"""Offline checks for the loop driver's bookkeeping: the session target stops the
loop, and `stop` reports every skip of a session that ran past midnight. Runs the
driver against a scratch PROJECT_ROOT; no browser is reached on these paths."""
import json, os, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
STEP = os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-step.py")

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


def project(state, cands):
    root = tempfile.mkdtemp(prefix="olx-step-test-")
    os.makedirs(os.path.join(root, "harness/3ceasuri-import"))
    with open(os.path.join(root, "state.json"), "w") as f:
        json.dump(state, f)
    q = os.path.join(root, "harness/3ceasuri-import/.candidates-test.json")
    with open(q, "w") as f:
        json.dump({"generated": "2026-10-06T23:00:00", "profile": "classic",
                   "candidates": cands}, f)
    return root, q


def step(root, *args):
    p = subprocess.run([sys.executable, STEP] + list(args), capture_output=True, text=True,
                       env={"PROJECT_ROOT": root, "PATH": os.environ.get("PATH", "")},
                       timeout=60)
    return p.returncode, p.stdout


RUNNING = {"session_date": "2026-10-06", "session_started": "2026-10-06T23:40:00",
           "target": 2, "session_imported": 2, "session_skipped": 0, "status": "running"}
PENDING = [{"id": "1", "status": "pending", "photos": 5}]

# the target reached: `next` refuses and points at `stop`, without touching the queue
root, q = project(RUNNING, PENDING)
rc, out = step(root, "next", q)
check(rc == 4 and "TARGET_REACHED: 2 of 2" in out and out.strip().endswith(
      "stop harness/3ceasuri-import/.candidates-test.json"),
      "next at the target must say TARGET_REACHED and NEXT: stop, got rc=%s %r" % (rc, out))
check(json.load(open(q))["candidates"][0]["status"] == "pending",
      "next at the target must not touch the queue")

# below the target, `next` goes on (a one-photo candidate skips without a browser)
root, q = project(dict(RUNNING, session_imported=1),
                  [{"id": "1", "status": "pending", "photos": 1}])
rc, out = step(root, "next", q)
check("TARGET_REACHED" not in out and "SKIPPED 1" in out, "below the target: %r" % out)

# no target given at start -> never reached
root, q = project(dict(RUNNING, target=None, session_imported=40), PENDING[:0])
rc, out = step(root, "next", q)
check("TARGET_REACHED" not in out and "QUEUE_EMPTY" in out, "no target: %r" % out)

# a session past midnight keeps the first day's skip reasons
root, q = project(RUNNING, [
    {"id": "1", "status": "skipped", "reason": "bulk_lot", "ts": "2026-10-06T23:50:00"},
    {"id": "2", "status": "skipped", "reason": "repost", "ts": "2026-10-07T00:10:00"},
    {"id": "3", "status": "skipped", "reason": "old", "ts": "2026-10-06T10:00:00"}])
rc, out = step(root, "stop", q)
check('"bulk_lot": 1' in out and '"repost": 1' in out and '"old"' not in out,
      "stop must count skips since session_started, across midnight: %r" % out)
check(json.load(open(os.path.join(root, "state.json")))["status"] == "idle",
      "stop sets the state idle")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
