#!/usr/bin/env python3
"""decide.py - the ONE model call of a per-ad import: the sheet in, a JSON decision out.

A plain module (python3, not a browser payload). `olx-loop.py` calls it for every
sheet, and `evals/per-ad/eval.py` builds its prompt with the same functions, so the
eval measures exactly what production sends (issue #2).

The rules are not here: they are the "The sheet" section of
`references/per-ad-agent.md` and the driver's sheet (`olx-step.py` HINTS/sheet()),
read at call time. This module only frames them and parses the answer.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
H = os.path.dirname(HERE)
AGENT_MD = os.path.join(H, "references/per-ad-agent.md")
SKIP_CODES = ("suspected_counterfeit", "bulk_lot", "not_a_watch", "mismatched_photos")

HEADER = """EVAL MODE. You are the per-ad import agent, but in this run you execute NO
command: no olx-step.py, no finish, no skip, no Write. You may only Read the photos the
sheet names. Decide exactly as the rules below say, then answer with ONE JSON object and
nothing else:

{"action": "finish" or "skip",
 "skip_code": null or one of suspected_counterfeit|bulk_lot|not_a_watch|mismatched_photos,
 "fields": {every DECIDE field except description: its value; plus "new_model": true if needed},
 "description": "the description you would write (finish only), else null"}

The rules the real agent follows:

"""


def build_prompt(sheet, full_text=None):
    """The decision prompt for one sheet (the text `olx-step.py next` printed)."""
    rules = open(AGENT_MD).read().split("## The sheet", 1)[1].split("## Answer", 1)[0]
    sh = re.sub(r"write it with the Write tool to \S+ \(plain text, no quotes\); finish picks it up\.",
                'put it in the answer\'s "description".', sheet)
    sh = "\n".join(l for l in sh.splitlines()
                   if not l.startswith(("NEXT:", "  Pass ONLY the fields")))
    if full_text and "[…]" in sh:
        sh += "\nFULL SELLER TEXT:\n" + full_text
    return HEADER + "## The sheet" + rules + "\n---\nTHE SHEET:\n" + sh + "\n"


def retry_prompt(prompt, first, driver_text):
    """The same prompt, the first answer and what the driver said about it."""
    said = "\n".join(l for l in driver_text.splitlines() if not l.startswith("NEXT:"))
    return (prompt + "\n---\nYOUR FIRST ANSWER:\n" + json.dumps(first, ensure_ascii=False)
            + "\n\nTHE DRIVER ANSWERED:\n" + said
            + "\n\nAnswer again with the COMPLETE JSON object: every field of your first "
              "answer, corrected where the driver says (a description fix: the whole "
              "corrected description).\n")


def parse_answer(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def valid(answer):
    """None when the answer can be acted on, else what is wrong with it."""
    if not isinstance(answer, dict):
        return "no JSON object"
    if answer.get("action") == "skip":
        return None if answer.get("skip_code") in SKIP_CODES else \
            "skip_code must be one of " + "|".join(SKIP_CODES)
    if answer.get("action") == "finish":
        return None if isinstance(answer.get("fields"), dict) else "finish needs a fields object"
    return 'action must be "finish" or "skip"'


def merge(first, second):
    """A retry answer on top of the first: a field the retry leaves out keeps the
    first answer's value, so a FIX can never drop `new_model=true` again."""
    out = dict(second)
    out["fields"] = dict(first.get("fields") or {}, **(second.get("fields") or {}))
    if not second.get("description"):
        out["description"] = first.get("description")
    return out


def decide_fields(sheet):
    """The field names of the sheet's DECIDE block."""
    block = sheet.split("DECIDE", 1)[1].split("\nKEEP", 1)[0] if "DECIDE" in sheet else ""
    return re.findall(r"^  (\w+)\s+= ", block, re.M)


def finish_pairs(answer, fields):
    """`field=value` argv items for `olx-step.py finish` (no shell: no quoting)."""
    allowed = set(fields) | {"new_model"}
    pairs = []
    for k, v in (answer.get("fields") or {}).items():
        if k not in allowed or k == "description":
            continue
        if v is None:
            v = "null"
        elif isinstance(v, bool):
            v = "true" if v else "false"
        else:
            v = " ".join(str(v).split())
        pairs.append("%s=%s" % (k, v))
    return pairs


def call(prompt, model="sonnet", effort="high", add_dirs=(), timeout=600):
    """One `claude -p` run. A temp cwd keeps the project CLAUDE.md and memory out;
    no --bare (it skips the keychain: "Not logged in"). CLAUDE_BIN overrides the
    binary (the offline tests use a fake)."""
    cmd = (os.environ.get("CLAUDE_BIN") or "claude").split() + [
        "-p", "--model", model, "--effort", effort, "--output-format", "json",
        "--allowedTools", "Read"]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    cwd = tempfile.mkdtemp(prefix="olx-decide-")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd,
                           timeout=timeout)
        out = json.loads(p.stdout)
    except Exception as e:                       # timeout, bad JSON, CLI failure
        out = {"is_error": True, "result": "%s: %s" % (type(e).__name__, e)}
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    return {"answer": parse_answer(out.get("result")), "raw": out.get("result"),
            "error": bool(out.get("is_error")), "cost_usd": out.get("total_cost_usd"),
            "served_by": list((out.get("modelUsage") or {}).keys()),
            "seconds": round(time.time() - t0, 1), "turns": out.get("num_turns")}
