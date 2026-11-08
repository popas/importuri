#!/usr/bin/env python3
"""olx-loop.py - the per-ad import loop as ONE script; a model only decides (issue #2).

Run with python3 from the repo root, in a terminal (no Claude Code session needed):

    python3 harness/3ceasuri-import/scripts/olx-loop.py <queue> --target 100
            [--model sonnet] [--effort high] [--push-every 10] [--no-push]

It sequences `olx-step.py` exactly as a per-ad agent did - start, next, finish /
skip, stop - and asks a model (`decide.py`: one `claude -p`) only what the sheet asks:
the fields, the description, or a judgement skip. Everything mechanical is code: the
`field=value` pairs, the description file, the FIX retry (merged onto the first answer,
so it can never drop a field), the NEW_BRAND commit, the push every N ads.

Stops on TARGET_REACHED / QUEUE_EMPTY (runs `stop`), on OLX_BLOCKED / BROWSER_FAILURE /
PREFLIGHT_FAILED / three ERROR in a row (the session stays running: run the same
command again to resume). One loop at a time: one Chrome, one OLX tab, one state.json.

Why: 2026-11-08, one Opus orchestrator + one Sonnet agent per ad cost ~40k agent
tokens per ad plus an orchestrator turn re-reading its whole context, for three
mechanical commands around one judgement. `evals/per-ad/` measures that judgement.

Exit: 0 done, 2 stopped (blocked / errors), 130 interrupted.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates      # noqa: E402
import contract_draft  # noqa: E402
import decide          # noqa: E402

ROOT = os.environ.get("PROJECT_ROOT") or os.path.abspath(os.path.join(HERE, "../../.."))
H = os.path.join(ROOT, "harness/3ceasuri-import")
STEP = os.environ.get("OLX_STEP") or os.path.join(HERE, "olx-step.py")
LOCK = os.path.join(ROOT, ".olx-loop.lock")
PHOTOS = os.path.join(H, ".photos")
RUNS = os.path.join(H, ".runs")
PUSH_FILES = ["history.jsonl", "harness/3ceasuri-import/scripts/import-watch.js",
              "harness/3ceasuri-import/references/brand-ids.md",
              "harness/3ceasuri-import/references/shop-cards.json"]
STOP_HEADS = ("OLX_BLOCKED", "BROWSER_FAILURE", "PREFLIGHT_FAILED", "NO_QUEUE")


def say(line):
    print(line, flush=True)


def step(*args):
    p = subprocess.run([sys.executable, STEP] + [str(a) for a in args], capture_output=True,
                       text=True, cwd=ROOT, env=dict(os.environ, PROJECT_ROOT=ROOT))
    out = (p.stdout or "").strip() or (p.stderr or "").strip()[-600:]   # a crash: its traceback
    return p.returncode, out, (out.splitlines() or [""])[0]


class Loop:
    def __init__(self, queue, target, model, effort, push_every, push):
        self.queue, self.target = queue, target
        self.model, self.effort = model, effort
        self.push_every, self.push_on = push_every, push
        self.stats = collections.Counter()
        self.cost = 0.0
        self.t0 = time.time()
        self.since_push = 0
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.fixes = collections.Counter()      # FIX / BAD_ANSWER codes this run
        self.skip_codes = collections.Counter()
        self.calls = 0                          # model calls
        self.ads = []                           # one summary per decided ad
        self.rec = None                         # the decision record of the ad in hand

    # --- the model ---------------------------------------------------------------
    def ask(self, prompt):
        """A valid decision, or None after one corrective re-ask."""
        for attempt in range(2):
            r = decide.call(prompt, self.model, self.effort, [PHOTOS])
            self.cost += r["cost_usd"] or 0
            self.calls += 1
            bad = decide.valid(r["answer"])
            if self.rec is not None:
                self.rec["events"].append({
                    "type": "model", "answer": r["answer"], "invalid": bad, "error": r["error"],
                    "raw": None if r["answer"] and not bad else (r["raw"] or "")[:4000],
                    "cost_usd": r["cost_usd"], "seconds": r["seconds"],
                    "served_by": r["served_by"], "turns": r["turns"]})
            if not bad:
                return r["answer"]
            prompt += ("\n---\nYour reply could not be used (%s). Reply with ONLY the JSON "
                       "object described at the top.\n" % bad)
        return None

    # --- one ad --------------------------------------------------------------------
    def handle(self, sheet):
        """Decide one sheet; every model answer and driver reply goes to
        .runs/olx-<id>-decision.json (a list: one record per time the ad was handled)."""
        ad_id = sheet.split()[1]
        self.rec = {"run": self.run_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model": self.model, "effort": self.effort, "sheet": sheet, "events": []}
        cost0, calls0, outcome = self.cost, self.calls, "error"
        try:
            outcome = self._handle(ad_id, sheet)
            return outcome
        finally:
            self.rec.update(outcome=outcome, cost_usd=round(self.cost - cost0, 4),
                            calls=self.calls - calls0)
            path = os.path.join(RUNS, "olx-%s-decision.json" % ad_id)
            try:
                old = json.load(open(path)) if os.path.exists(path) else []
            except ValueError:
                old = []
            os.makedirs(RUNS, exist_ok=True)
            with open(path, "w") as f:
                json.dump(old + [self.rec], f, ensure_ascii=False, indent=1)
            self.ads.append({"id": ad_id, "outcome": outcome, "cost_usd": self.rec["cost_usd"],
                             "calls": self.rec["calls"]})
            self.rec = None

    def drive(self, *args):
        """olx-step.py, with its reply kept in the decision record."""
        rc, out, head = step(*args)
        if self.rec is not None:
            self.rec["events"].append({"type": "driver", "cmd": args[0],
                                       "args": [str(a) for a in args[3:]], "rc": rc,
                                       "out": out[:3000]})
        if head.startswith("SKIPPED"):
            self.note_skip(head)
        elif head.startswith("FIX"):
            for code in re.findall(r"^  (\w+): ", out, re.M):
                self.fixes[code] += 1
        elif head.startswith("BAD_ANSWER"):
            self.fixes["BAD_ANSWER"] += 1
        return rc, out, head

    def note_skip(self, head):
        """'SKIPPED <id>: <code> …' -> the code, counted for the summary."""
        rest = head.split(":", 1)[1].strip() if ":" in head else ""
        self.skip_codes[(rest.split() or ["?"])[0].rstrip(":,")] += 1

    def _handle(self, ad_id, sheet):
        fields = decide.decide_fields(sheet)
        full = None
        if "[…]" in sheet:
            with open(contract_draft.draft_path(ROOT, ad_id)) as f:
                full = json.load(f).get("description")
        prompt = decide.build_prompt(sheet, full)
        answer = self.ask(prompt)
        rounds = 0
        while True:
            if answer is None:
                candidates.mark(self.queue, ad_id, "error", "decision: no valid answer")
                say("ERROR %s: the model gave no usable answer (the queue marked it `error`)" % ad_id)
                return "error"
            if answer.get("action") == "skip":
                note = (answer.get("fields") or {}).get("notes") or ""
                rc, out, head = self.drive("skip", self.queue, ad_id, answer["skip_code"], note)
                say(head)
                return "skipped"
            desc = answer.get("description")
            if desc:
                path = contract_draft.description_path(ROOT, ad_id)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(desc.strip() + "\n")
            rc, out, head = self.drive("finish", self.queue, ad_id,
                                       *decide.finish_pairs(answer, fields))
            if head.startswith("IMPORTED"):
                say(head)
                self.brand_commits(out)
                return "imported"
            if head.startswith("SKIPPED"):
                say(head)
                return "skipped"
            if head.startswith(("FIX", "BAD_ANSWER")) and rounds < 2:
                rounds += 1
                say("  %s -> asking again" % head)
                second = self.ask(decide.retry_prompt(prompt, answer, out))
                answer = None if second is None else (
                    second if second.get("action") == "skip" else decide.merge(answer, second))
                continue
            if head.startswith(STOP_HEADS):
                say(head)
                return "blocked"
            say(head or "ERROR %s: finish printed nothing" % ad_id)
            if head.startswith(("FIX", "BAD_ANSWER")):
                candidates.mark(self.queue, ad_id, "error", "decision: unfixed after retries")
            return "error"

    def brand_commits(self, out):
        for line in out.splitlines():
            if "THEN: git " in line:
                cmd = line.split("THEN: ", 1)[1]
                say("  NEW_BRAND commit: " + cmd)
                subprocess.run(cmd, shell=True, cwd=ROOT)    # the driver's own printed command

    # --- git -----------------------------------------------------------------------
    def push(self):
        self.since_push = 0
        if not self.push_on:
            return
        files = [f for f in PUSH_FILES if os.path.exists(os.path.join(ROOT, f))]
        subprocess.run(["git", "add"] + files, cwd=ROOT)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
            subprocess.run(["git", "commit", "-q", "-m", "history: OLX import loop (%s)"
                            % os.path.basename(self.queue)], cwd=ROOT)
        p = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT,
                           capture_output=True, text=True)
        if p.returncode:
            say("WARN: git push failed: %s" % (p.stderr or "").strip()[:200])

    def progress(self, final=False):
        mins = (time.time() - self.t0) / 60
        n = sum(self.stats.values())
        decided = len(self.ads)
        say("%s: imported %d, skipped %d, errors %d | %.1f ads/min | model $%.2f (%s %s)" % (
            "DONE" if final else "PROGRESS", self.stats["imported"], self.stats["skipped"],
            self.stats["error"], n / mins if mins else 0, self.cost, self.model, self.effort))
        top = lambda c: ", ".join("%s %d" % kv for kv in c.most_common()) or "-"
        say("  FIX: %s | SKIP: %s | $%.3f and %.1f model calls per decided ad (%d)" % (
            top(self.fixes), top(self.skip_codes), self.cost / decided if decided else 0,
            self.calls / decided if decided else 0, decided))
        if final:
            path = os.path.join(RUNS, "olx-loop-%s.json" % self.run_id)
            os.makedirs(RUNS, exist_ok=True)
            with open(path, "w") as f:
                json.dump({"run": self.run_id, "queue": self.queue, "model": self.model,
                           "effort": self.effort, "minutes": round(mins, 1),
                           "stats": self.stats, "fixes": self.fixes,
                           "skip_codes": self.skip_codes, "cost_usd": round(self.cost, 4),
                           "model_calls": self.calls, "ads": self.ads}, f, indent=1)
            say("  run summary: %s" % os.path.relpath(path, ROOT))

    # --- the loop ------------------------------------------------------------------
    def run(self):
        rc, out, head = step("start", self.queue, "--target", self.target, "--clear-every", "0")
        say(head)
        if rc != 0:
            return 2
        errors_in_row = 0
        while True:
            rc, out, head = step("next", self.queue)
            if rc in (3, 4) or head.startswith(("TARGET_REACHED", "QUEUE_EMPTY")):
                say(head)
                step("stop", self.queue)
                return 0
            if rc == 5:                    # CLEAR_CHECKPOINT of a session started elsewhere
                step("start", self.queue, "--target", self.target)
                continue
            if head.startswith("AD "):
                outcome = self.handle(out)
            elif head.startswith("SKIPPED"):
                say(head)
                self.note_skip(head)
                outcome = "skipped"
            elif head.startswith("ERROR"):
                say(head)
                outcome = "error"
            else:
                say(head or "STOPPED: next printed nothing")
                return 2
            if outcome == "blocked":
                return 2
            self.stats[outcome] += 1
            errors_in_row = errors_in_row + 1 if outcome == "error" else 0
            if errors_in_row >= 3:
                say("STOPPED: three ERROR in a row - invoke the olx-troubleshooting skill")
                return 2
            self.since_push += 1
            if self.push_every and self.since_push >= self.push_every:
                self.push()
                self.progress()


def lock():
    if os.path.exists(LOCK):
        try:
            pid = int(open(LOCK).read().strip())
            os.kill(pid, 0)
            say("STOPPED: another olx-loop is running (pid %d) - one Chrome, one OLX tab" % pid)
            return False
        except (ValueError, OSError):
            pass                                   # a stale lock
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    return True


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("queue")
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--push-every", type=int, default=10)
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    if not lock():
        return 2
    loop = Loop(a.queue, a.target, a.model, a.effort, a.push_every, not a.no_push)
    rc = 130
    try:
        rc = loop.run()
    except KeyboardInterrupt:
        say("INTERRUPTED: the session stays running; run the same command to resume")
    finally:
        loop.push()
        loop.progress(final=True)
        if os.path.exists(LOCK):
            os.remove(LOCK)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
