#!/usr/bin/env python3
"""Offline checks for olx-loop.py (issue #2): it sequences olx-step.py and asks the
model only for the decision. Both are fakes here - a scripted olx-step.py and a
scripted `claude -p` - so no browser, no network, no model, no git."""
import json, os, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
LOOP = os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-loop.py")
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import decide

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

FAKE_STEP = r'''
import json, os, sys
script = os.environ["FAKE_STEP_SCRIPT"]
steps = json.load(open(script))
with open(os.environ["FAKE_STEP_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
s = steps.pop(0) if steps else {"cmd": "?", "rc": 9, "out": "FAKE: script exhausted"}
json.dump(steps, open(script, "w"))
if s["cmd"] != sys.argv[1]:
    print("FAKE: expected %s, got %s" % (s["cmd"], sys.argv[1])); sys.exit(9)
print(s["out"]); sys.exit(s["rc"])
'''
FAKE_CLAUDE = r'''
import json, os, sys
prompt = sys.stdin.read()
path = os.environ["FAKE_ANSWERS"]
answers = json.load(open(path))
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps(prompt) + "\n")
a = answers.pop(0)
json.dump(answers, open(path, "w"))
print(json.dumps({"result": a if isinstance(a, str) else json.dumps(a), "is_error": False,
                  "total_cost_usd": 0.07, "modelUsage": {"claude-sonnet-5-5": {}}, "num_turns": 2}))
'''

SHEET = """AD 9 | smart | "Suunto Run nou" | 4 photos | 750 RON
TEXT: Suunto Run nou
  Ceas Suunto Run, nou, sigilat. Livrez oriunde.
PHOTO (read exactly this one): /x/.photos/olx-9/01.jpg
DESCRIPTION - write it with the Write tool to harness/3ceasuri-import/.contracts/olx-9.description.txt (plain text, no quotes); finish picks it up. Rule: the seller's text
MODELS Suunto has on the site - `model` is one of these when it is this watch's line: Run, Race
DECIDE (field = current value | rule):
  model         = null               | MUST ANSWER - the line
  variant       = null               | edition
  is_bulk_lot   = null               | MUST ANSWER - true|false.
  connectivity  = null               | one of gsm|no_gsm.
KEEP (already filled, do not pass them): brand="Suunto" price=750
NEXT: python3 harness/3ceasuri-import/scripts/olx-step.py finish q.json 9 'model=...'
  Pass ONLY the fields whose value you change; a field you omit keeps its current value."""

START = {"cmd": "start", "rc": 0, "out": "READY: Chrome | queue q.json {} | target 2\nAPI: on\nNEXT: next"}
NEXT_SHEET = {"cmd": "next", "rc": 0, "out": SHEET}
GOOD = {"action": "finish", "skip_code": None, "description": "Ceas Suunto Run, nou, sigilat.",
        "fields": {"model": "Run Pro", "new_model": True, "variant": None, "is_bulk_lot": False,
                   "connectivity": "no_gsm", "price": 1}}


def run(steps, answers):
    tmp = tempfile.mkdtemp(prefix="olx-loop-test-")
    os.makedirs(os.path.join(tmp, "harness/3ceasuri-import"))
    q = os.path.join(tmp, "harness/3ceasuri-import/.candidates-test.json")
    json.dump({"candidates": [{"id": "9", "status": "pending"}]}, open(q, "w"))
    for name, src in (("step.py", FAKE_STEP), ("claude.py", FAKE_CLAUDE)):
        open(os.path.join(tmp, name), "w").write(src)
    json.dump(steps, open(os.path.join(tmp, "steps.json"), "w"))
    json.dump(answers, open(os.path.join(tmp, "answers.json"), "w"))
    env = dict(os.environ, PROJECT_ROOT=tmp, OLX_STEP=os.path.join(tmp, "step.py"),
               CLAUDE_BIN="%s %s" % (sys.executable, os.path.join(tmp, "claude.py")),
               FAKE_STEP_SCRIPT=os.path.join(tmp, "steps.json"),
               FAKE_STEP_LOG=os.path.join(tmp, "step.log"),
               FAKE_ANSWERS=os.path.join(tmp, "answers.json"),
               FAKE_CLAUDE_LOG=os.path.join(tmp, "claude.log"))
    p = subprocess.run([sys.executable, LOOP, q, "--target", "2", "--no-push"],
                       capture_output=True, text=True, env=env, timeout=60)
    log = lambda n: [json.loads(l) for l in open(os.path.join(tmp, n))] \
        if os.path.exists(os.path.join(tmp, n)) else []
    return p, log("step.log"), log("claude.log"), tmp, q


# 1. sheet -> finish -> IMPORTED -> TARGET_REACHED -> stop
p, steps, prompts, tmp, q = run(
    [START, NEXT_SHEET,
     {"cmd": "finish", "rc": 0, "out": "IMPORTED 9: Suunto \"Run Pro\", 750 RON (logged)\nNEXT: next"},
     {"cmd": "next", "rc": 4, "out": "TARGET_REACHED: 2 of 2 imported this session\nNEXT: stop"},
     {"cmd": "stop", "rc": 0, "out": "SESSION: imported 2"}],
    [GOOD])
fin = [s for s in steps if s[0] == "finish"]
check(p.returncode == 0, "import run exits 0: %s %s" % (p.returncode, p.stdout))
check(fin and "model=Run Pro" in fin[0] and "new_model=true" in fin[0] and "is_bulk_lot=false" in fin[0]
      and "variant=null" in fin[0], "finish pairs: %r" % fin)
check(fin and not any(a.startswith("price=") for a in fin[0]), "a KEEP field is never passed: %r" % fin)
check(steps and steps[0][:4] == ["start", q, "--target", "2"] and steps[-1][0] == "stop",
      "start first, stop last: %r" % steps)
d = open(os.path.join(tmp, "harness/3ceasuri-import/.contracts/olx-9.description.txt")).read()
check(d.strip() == "Ceas Suunto Run, nou, sigilat.", "description file written: %r" % d)
check(prompts and "Write tool" not in prompts[0] and "NEXT:" not in prompts[0]
      and "THE SHEET:" in prompts[0], "the prompt is the framed sheet")
check("DONE: imported 1, skipped 0" in p.stdout, "summary: %r" % p.stdout)
check(not os.path.exists(os.path.join(tmp, ".olx-loop.lock")), "the lock is released")
runs = os.path.join(tmp, "harness/3ceasuri-import/.runs")
dec = json.load(open(os.path.join(runs, "olx-9-decision.json")))
check(len(dec) == 1 and dec[0]["outcome"] == "imported" and dec[0]["calls"] == 1
      and [e["type"] for e in dec[0]["events"]] == ["model", "driver"]
      and dec[0]["events"][0]["answer"]["fields"]["model"] == "Run Pro"
      and dec[0]["sheet"].startswith("AD 9"), "decision log: %r" % dec)
summ = [f for f in os.listdir(runs) if f.startswith("olx-loop-")]
check(summ and json.load(open(os.path.join(runs, summ[0])))["stats"] == {"imported": 1},
      "run summary file: %r" % summ)
check("$0.070 and 1.0 model calls per decided ad (1)" in p.stdout, "cost line: %r" % p.stdout)

# 2. FIX -> one retry; the retry leaves out new_model and keeps it (merged)
p, steps, prompts, tmp, q = run(
    [START, NEXT_SHEET,
     {"cmd": "finish", "rc": 0, "out": "FIX 9 - the gate named what to supply (you get ONE retry):\n"
                                       "  description_meta: description talks about the ad\nNEXT: finish"},
     {"cmd": "finish", "rc": 0, "out": "IMPORTED 9: Suunto \"Run Pro\", 750 RON (logged)"},
     {"cmd": "next", "rc": 3, "out": "QUEUE_EMPTY: {}"},
     {"cmd": "stop", "rc": 0, "out": "SESSION"}],
    [GOOD, {"action": "finish", "fields": {"variant": "Black"}, "description": "Ceas nou."}])
fin = [s for s in steps if s[0] == "finish"]
check(len(fin) == 2 and "new_model=true" in fin[1] and "model=Run Pro" in fin[1]
      and "variant=Black" in fin[1], "the retry is merged onto the first answer: %r" % fin)
check(len(prompts) == 2 and "THE DRIVER ANSWERED:" in prompts[1] and "description_meta" in prompts[1],
      "the retry prompt carries the FIX lines")
check(p.returncode == 0, "fix run exits 0: %s" % p.stdout)
check("FIX: description_meta 1" in p.stdout, "FIX codes counted: %r" % p.stdout)
dec = json.load(open(os.path.join(tmp, "harness/3ceasuri-import/.runs/olx-9-decision.json")))
check([e["type"] for e in dec[0]["events"]] == ["model", "driver", "model", "driver"]
      and dec[0]["calls"] == 2, "the retry is in the decision log")

# 3. a judgement skip, then OLX_BLOCKED: exit 2, the session is NOT stopped
p, steps, prompts, tmp, q = run(
    [START, NEXT_SHEET,
     {"cmd": "skip", "rc": 0, "out": "SKIPPED 9: bulk_lot (logged)"},
     {"cmd": "next", "rc": 2, "out": "OLX_BLOCKED 10: OLX answered 403 - the ad stays pending"}],
    [{"action": "skip", "skip_code": "bulk_lot", "fields": {"notes": "3 watches, one price"},
      "description": None}])
sk = [s for s in steps if s[0] == "skip"]
check(sk and sk[0][2:] == ["9", "bulk_lot", "3 watches, one price"], "skip argv: %r" % sk)
check(p.returncode == 2 and "OLX_BLOCKED" in p.stdout and not any(s[0] == "stop" for s in steps),
      "blocked: exit 2, no stop: %s %r" % (p.returncode, steps))
check("SKIP: bulk_lot 1" in p.stdout, "skip codes counted: %r" % p.stdout)

# 4. an unusable reply is re-asked once; a second one marks the ad `error`
p, steps, prompts, tmp, q = run(
    [START, NEXT_SHEET, {"cmd": "next", "rc": 3, "out": "QUEUE_EMPTY: {}"},
     {"cmd": "stop", "rc": 0, "out": "SESSION"}],
    ["no json here", {"action": "skip", "skip_code": "made_up"}])
check(len(prompts) == 2 and "could not be used" in prompts[1], "one corrective re-ask")
check(json.load(open(q))["candidates"][0]["status"] == "error", "no usable answer -> error")
check(not any(s[0] in ("finish", "skip") for s in steps), "nothing sent to the driver")

# 4b. the queue runs out: stop's ARCHIVED line is shown; a later run on the archived
#     queue is QUEUE_EMPTY at start: exit 0, nothing else run
p, steps, prompts, tmp, q = run(
    [START, {"cmd": "next", "rc": 3, "out": "QUEUE_EMPTY: {}"},
     {"cmd": "stop", "rc": 0, "out": "SESSION: imported 0\nARCHIVED: q.json -> done/q.json "
                                     "(nothing pending)"}], [])
check(p.returncode == 0 and "ARCHIVED: q.json -> done/q.json" in p.stdout,
      "stop's ARCHIVED line is printed: %s %r" % (p.returncode, p.stdout))
p, steps, prompts, tmp, q = run(
    [{"cmd": "start", "rc": 3, "out": "QUEUE_EMPTY: q.json is finished - archived to done/q.json"}],
    [])
check(p.returncode == 0 and [s[0] for s in steps] == ["start"] and not prompts,
      "start on an archived queue: exit 0, no next/stop/model: %s %r" % (p.returncode, steps))

# 5. three ERROR in a row stop the loop
p, steps, prompts, tmp, q = run(
    [START] + [{"cmd": "next", "rc": 0, "out": "ERROR %d: did not load" % i} for i in range(3)],
    [])
check(p.returncode == 2 and "three ERROR in a row" in p.stdout, "3 errors stop: %s" % p.stdout)

# decide.py units
check(decide.decide_fields(SHEET) == ["model", "variant", "is_bulk_lot", "connectivity"],
      "DECIDE fields: %r" % decide.decide_fields(SHEET))
check(decide.valid({"action": "skip", "skip_code": "bulk_lot"}) is None and
      decide.valid({"action": "skip", "skip_code": "x"}) and decide.valid(None),
      "valid() accepts the four skip codes only")
check(decide.finish_pairs({"fields": {"notes": "two\nlines"}}, ["notes"]) == ["notes=two lines"],
      "a value is one argv item on one line")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
