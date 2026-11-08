#!/usr/bin/env python3
"""Per-ad model eval: which model + effort can run the one-ad import agent.

    python3 evals/per-ad/eval.py build                  # once: cases.jsonl + photos/
    python3 evals/per-ad/eval.py run haiku low          # one config -> results/haiku-low.jsonl
    python3 evals/per-ad/eval.py score                  # every results/*.jsonl -> report.md

Offline: no browser, no OLX, nothing written to the site. Each case is the sheet a
per-ad agent saw (rebuilt from .runs/ and .contracts/), sent through `claude -p`
with the "The sheet" rules of per-ad-agent.md. The model answers in JSON instead of
running `finish`/`skip`.

The reference is what PRODUCTION did (Sonnet agents, 2026-11-07/08): the fields the
site accepted, or the judgement skip. So a Sonnet config measures how consistent
Sonnet is with itself, and the other configs are compared on the same footing; a
disagreement is not automatically a mistake - read the diffs.
"""
import collections
import concurrent.futures
import difflib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../.."))
H = os.path.join(ROOT, "harness/3ceasuri-import")
sys.path.insert(0, os.path.join(H, "scripts"))
import infer_fields  # noqa: E402
import olx_import    # noqa: E402

CASES = os.path.join(HERE, "cases.jsonl")
PHOTOS = os.path.join(HERE, "photos")
RESULTS = os.path.join(HERE, "results")
AGENT_MD = os.path.join(H, "references/per-ad-agent.md")

JUDGEMENT_SKIPS = {"not_a_watch": 4, "bulk_lot": 4, "suspected_counterfeit": 3,
                   "mismatched_photos": 1}
IMPORTS_PER_PROFILE = 12
SINCE = ("2026-11-07", "2026-11-08")


def _step():
    spec = importlib.util.spec_from_file_location("olx_step", os.path.join(H, "scripts/olx-step.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --- build -----------------------------------------------------------------------
def _pass1(ad_id):
    for line in open(os.path.join(H, ".runs/olx-%s-pass1.log" % ad_id)):
        if line.startswith("EXTRACT_PROMPT:"):
            return json.loads(line[len("EXTRACT_PROMPT:"):])
    return None


def _known_and_text(prompt):
    """The OLX dropdown fields and the seller's (title, text) from the pass-1 prompt."""
    known = {}
    sec = prompt.split("## Known from OLX", 1)[1].split("\n## ", 1)[0]
    for m in re.finditer(r"^- `(\w+)`: (.+)$", sec, re.M):
        known[m.group(1)] = json.loads(m.group(2))
    ad = prompt.split("## OLX ad\n", 1)[1].strip()
    title, _, text = ad.partition("\n")
    return known, title.strip(), text.strip()


def build():
    events = [json.loads(l) for l in open(os.path.join(ROOT, "history.jsonl"))]
    events = [e for e in events if e.get("ts", "").startswith(SINCE)]
    pools = collections.defaultdict(list)
    for e in events:
        ad_id = e["id"]
        if not (os.path.exists(os.path.join(H, ".runs/olx-%s-pass1.log" % ad_id)) and
                os.path.exists(os.path.join(H, ".runs/olx-%s.json" % ad_id)) and
                os.path.exists(os.path.join(H, ".contracts/olx-%s.json" % ad_id))):
            continue
        if e["event"] == "import":
            prof = json.load(open(os.path.join(H, ".runs/olx-%s.json" % ad_id))).get("profile")
            pools["import:" + prof].append(e)
        else:
            code = e.get("reason", "").split(":")[0].split(" ")[0]
            if code in JUDGEMENT_SKIPS:
                pools["skip:" + code].append(e)

    rnd = random.Random(7)
    picked = []
    for prof in ("classic", "smart"):
        pool = pools["import:" + prof][:]
        rnd.shuffle(pool)
        seen = collections.Counter()
        pool.sort(key=lambda e: seen.update([e["brand"]]) or seen[e["brand"]])  # brands spread
        picked += pool[:IMPORTS_PER_PROFILE]
    for code, n in JUDGEMENT_SKIPS.items():
        pool = pools["skip:" + code][:]
        rnd.shuffle(pool)
        picked += pool[:n]

    shutil.rmtree(PHOTOS, ignore_errors=True)
    os.makedirs(PHOTOS)
    with open(CASES, "w") as out:
        for e in picked:
            ad_id = e["id"]
            run = json.load(open(os.path.join(H, ".runs/olx-%s.json" % ad_id)))
            final = json.load(open(os.path.join(H, ".contracts/olx-%s.json" % ad_id)))
            ep = _pass1(ad_id)
            known, title, text = _known_and_text(ep["prompt"])
            todo = final.get("_todo") or ep.get("todo") or []
            seed = dict(final)                       # fields nobody was asked keep their value
            for f in todo:
                seed[f] = known.get(f)
            seed["description"] = text
            seed["new_model"] = None
            photos = []
            for i, p in enumerate((run.get("photos") or [])[:2]):
                dst = os.path.join(PHOTOS, "%s-%02d.jpg" % (ad_id, i + 1))
                shutil.copy(p, dst)
                photos.append(os.path.relpath(dst, HERE))
            imp = e["event"] == "import"
            out.write(json.dumps({
                "id": ad_id, "profile": run["profile"], "extract": run.get("extract"),
                "models": run.get("models"), "photos": photos, "seed": seed,
                "seller_title": title, "seller_text": text,
                "expected": {"decision": "import" if imp else "skip",
                             "skip_code": None if imp else e["reason"].split(":")[0],
                             "fields": {f: final.get(f) for f in todo if f != "description"} if imp else None,
                             "description": final.get("description") if imp else None},
            }, ensure_ascii=False) + "\n")
    print("built %d cases -> %s" % (len(picked), os.path.relpath(CASES, ROOT)))
    print(collections.Counter(c["expected"]["decision"] + ":" + (c["expected"]["skip_code"] or c["profile"])
                              for c in map(json.loads, open(CASES))))


# --- run -------------------------------------------------------------------------
EVAL_HEADER = """EVAL MODE. You are the per-ad import agent, but in this run you execute NO
command: no olx-step.py, no finish, no skip, no Write. You may only Read the photos the
sheet names. Decide exactly as the rules below say, then answer with ONE JSON object and
nothing else:

{"action": "finish" or "skip",
 "skip_code": null or one of suspected_counterfeit|bulk_lot|not_a_watch|mismatched_photos,
 "fields": {every DECIDE field except description: its value; plus "new_model": true if needed},
 "description": "the description you would write (finish only), else null"}

The rules the real agent follows:

"""


def prompt_for(case, step):
    rules = open(AGENT_MD).read().split("## The sheet", 1)[1].split("## Answer", 1)[0]
    photos = [os.path.join(HERE, p) for p in case["photos"]]
    sh = step.sheet("evals/queue.json", case["id"], case["profile"], case["seed"],
                    case["extract"], photos, models=case["models"])
    sh = re.sub(r"write it with the Write tool to \S+ \(plain text, no quotes\); finish picks it up\.",
                'put it in the answer\'s "description".', sh)
    sh = "\n".join(l for l in sh.splitlines()
                   if not l.startswith(("NEXT:", "  Pass ONLY the fields")))
    if "[…]" in sh:
        sh += "\nFULL SELLER TEXT:\n" + case["seller_text"]
    return EVAL_HEADER + "## The sheet" + rules + "\n---\nTHE SHEET:\n" + sh + "\n"


def parse_answer(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def run_one(case, model, effort, step):
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--output-format", "json",
           "--allowedTools", "Read", "--add-dir", PHOTOS]
    cwd = tempfile.mkdtemp(prefix="per-ad-eval-")      # no project CLAUDE.md / memory
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt_for(case, step), capture_output=True, text=True,
                           cwd=cwd, timeout=600)
        out = json.loads(p.stdout)
    except Exception as e:                              # timeout, bad JSON, CLI failure
        out = {"is_error": True, "result": "%s: %s" % (type(e).__name__, e)}
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    return {"id": case["id"], "model": model, "effort": effort,
            "served_by": list((out.get("modelUsage") or {}).keys()),
            "error": bool(out.get("is_error")), "raw": out.get("result"),
            "answer": parse_answer(out.get("result")), "cost_usd": out.get("total_cost_usd"),
            "seconds": round(time.time() - t0, 1), "turns": out.get("num_turns")}


def run(model, effort, jobs=6, limit=None):
    cases = [json.loads(l) for l in open(CASES)][:limit]
    step = _step()
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "%s-%s.jsonl" % (model, effort))
    with open(path, "w") as out, concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        for i, r in enumerate(ex.map(lambda c: run_one(c, model, effort, step), cases), 1):
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            print("%d/%d %s %s" % (i, len(cases), r["id"],
                                   "ERROR" if r["error"] or not r["answer"] else
                                   r["answer"].get("action")), flush=True)
    print("-> " + os.path.relpath(path, ROOT))


# --- score -----------------------------------------------------------------------
def _norm(v):
    if isinstance(v, str):
        v = re.sub(r"[^a-z0-9]+", "", v.lower())
        return v or None
    return v


def _same(f, a, b):
    if f in infer_fields.NUMERIC and a is not None and b is not None:
        try:
            return abs(float(a) - float(b)) <= 0.5
        except (TypeError, ValueError):
            return False
    return _norm(a) == _norm(b)


def decision_of(ans):
    if not ans:
        return "no_answer"
    f = ans.get("fields") or {}
    if ans.get("action") == "skip" or f.get("is_bulk_lot") is True or f.get("is_wristwatch") is False:
        return "skip"
    return "import"


def score_file(path, cases):
    rows = [json.loads(l) for l in open(path)]
    s = collections.Counter()
    diffs = []
    for r in rows:
        c = cases[r["id"]]
        exp, ans = c["expected"], r["answer"]
        got = decision_of(ans)
        s["n"] += 1
        s["cost"] += r["cost_usd"] or 0
        s["secs"] += r["seconds"]
        s["no_answer"] += got == "no_answer"
        s["decision_ok"] += got == exp["decision"]
        if exp["decision"] == "skip":
            s["skips"] += 1
            s["skip_caught"] += got == "skip"
            if got != "skip":
                diffs.append("%s missed skip (%s)" % (r["id"], exp["skip_code"]))
            continue
        s["imports"] += 1
        if got != "import":
            s["false_skip"] += 1
            diffs.append("%s skipped a good ad: %s" % (r["id"], json.dumps(ans, ensure_ascii=False)[:160]))
            continue
        fields = ans.get("fields") or {}
        for f, want in exp["fields"].items():
            if f in ("notes", "new_model"):
                continue
            ok = _same(f, fields.get(f), want)
            key = f if f in ("model", "variant") else "other"
            s[key + "_n"] += 1
            s[key + "_ok"] += ok
            if not ok and f in ("model", "variant", "brand", "connectivity", "movement"):
                diffs.append("%s %s: %r (ref %r)" % (r["id"], f, fields.get(f), want))
        if c["models"] and fields.get("model") not in c["models"] and not fields.get("new_model"):
            s["unknown_model"] += 1
        merged = dict(c["seed"], **{k: v for k, v in fields.items() if k != "new_model"})
        merged["description"] = ans.get("description") or ""
        if infer_fields.validate({k: v for k, v in merged.items() if k != "_todo"}):
            s["invalid"] += 1
        gates = [g["code"] for g in olx_import.confidence_review(
            c["profile"], merged, [1, 2], {}, c["seller_text"], c["seller_title"])
            if g["code"].startswith(("description_", "thin_description"))]
        if gates:
            s["desc_gate"] += 1
            diffs.append("%s description gate: %s" % (r["id"], ",".join(gates)))
        s["desc_sim"] += difflib.SequenceMatcher(
            None, merged["description"].split(), (exp["description"] or "").split()).ratio()
    return s, diffs


def score():
    cases = {c["id"]: c for c in map(json.loads, open(CASES))}
    pct = lambda a, b: "%d%%" % round(100.0 * a / b) if b else "-"
    head = ("| config | decision ok | skips caught | good ads skipped | model | variant | "
            "other fields | unknown model | invalid | desc gate | desc ≈ ref | $/ad | s/ad |")
    lines = ["# Per-ad model eval", "",
             "Reference: production Sonnet answers (site-accepted fields / judgement skips). "
             "%d cases. Regenerate: `python3 evals/per-ad/eval.py score`." % len(cases), "",
             head, "|" + "---|" * (head.count("|") - 1)]
    details = []
    for path in sorted(p for p in os.listdir(RESULTS) if p.endswith(".jsonl")):
        s, diffs = score_file(os.path.join(RESULTS, path), cases)
        imp = s["imports"] - s["false_skip"]
        lines.append("| %s | %s | %d/%d | %d | %s | %s | %s | %d | %d | %d | %.2f | %.3f | %.0f |" % (
            path[:-6], pct(s["decision_ok"], s["n"]), s["skip_caught"], s["skips"], s["false_skip"],
            pct(s["model_ok"], s["model_n"]), pct(s["variant_ok"], s["variant_n"]),
            pct(s["other_ok"], s["other_n"]), s["unknown_model"], s["invalid"], s["desc_gate"],
            s["desc_sim"] / imp if imp else 0, s["cost"] / s["n"], s["secs"] / s["n"]))
        details += ["", "## " + path[:-6], ""] + ["- " + d for d in diffs]
    report = "\n".join(lines + details) + "\n"
    open(os.path.join(HERE, "report.md"), "w").write(report)
    print("\n".join(lines))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        build()
    elif a[:1] == ["run"] and len(a) >= 3:
        run(a[1], a[2], limit=int(a[3]) if len(a) > 3 else None)
    elif a[:1] == ["score"]:
        score()
    else:
        print(__doc__)
        sys.exit(1)
