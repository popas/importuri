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

# the /clear checkpoint: `clear_every` ads settled in this context -> `next` stops the
# operator without touching the queue, and the line tells the human to /clear
CLEAR = dict(RUNNING, target=50, session_imported=15, session_skipped=10, clear_every=25,
             context_from=0)
root, q = project(CLEAR, PENDING)
rc, out = step(root, "next", q)
check(rc == 5 and "CLEAR_CHECKPOINT: 25 ads" in out and "/clear" in out
      and "olx-step.py next" not in out,
      "next at the checkpoint must say CLEAR_CHECKPOINT and no next, got rc=%s %r" % (rc, out))
check(json.load(open(q))["candidates"][0]["status"] == "pending",
      "next at the checkpoint must not touch the queue")

# the outcome that reaches the checkpoint already prints it instead of `next`
root, q = project(dict(CLEAR, session_skipped=9),
                  [{"id": "1", "status": "pending", "photos": 1}])
rc, out = step(root, "next", q)
check("SKIPPED 1" in out and "CLEAR_CHECKPOINT: 25 ads" in out,
      "the 25th settled ad must end on the checkpoint: %r" % out)

# counted from context_from: after a resume the next 25 run on
root, q = project(dict(CLEAR, context_from=25), [{"id": "1", "status": "pending", "photos": 1}])
rc, out = step(root, "next", q)
check("CLEAR_CHECKPOINT" not in out and "SKIPPED 1" in out, "after a resume: %r" % out)

# the target wins over the checkpoint: stop, not /clear
root, q = project(dict(CLEAR, target=15), PENDING)
rc, out = step(root, "next", q)
check(rc == 4 and "TARGET_REACHED" in out and "CLEAR_CHECKPOINT" not in out,
      "target and checkpoint together: %r" % out)

# a state.json from before the checkpoint existed never stops
root, q = project(dict(RUNNING, target=None, session_imported=40), [
    {"id": "1", "status": "pending", "photos": 1}])
rc, out = step(root, "next", q)
check("CLEAR_CHECKPOINT" not in out, "no clear_every in the state: %r" % out)

# `start` after the checkpoint resumes (same queue, running); anything else is fresh.
# Checked on the function: `start` itself needs Chrome for its preflight.
import importlib.util
spec = importlib.util.spec_from_file_location("olx_step", STEP)
olx_step = importlib.util.module_from_spec(spec)
spec.loader.exec_module(olx_step)
qrel = "harness/3ceasuri-import/.candidates-test.json"
qabs = os.path.join(olx_step.ROOT, qrel)
check(olx_step.resumes(dict(CLEAR, queue=qrel), qabs), "start at the checkpoint resumes")
check(not olx_step.resumes(dict(CLEAR, queue=qrel, context_from=25), qabs),
      "start before the checkpoint is a fresh session")
check(not olx_step.resumes(dict(CLEAR, queue="harness/3ceasuri-import/.other.json"), qabs),
      "start on another queue is a fresh session")
check(not olx_step.resumes(dict(CLEAR, queue=qrel, status="idle"), qabs),
      "start after stop is a fresh session")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
