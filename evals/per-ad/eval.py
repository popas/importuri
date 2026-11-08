#!/usr/bin/env python3
"""Per-ad model eval: which model + effort can make the per-ad import decision.

    python3 evals/per-ad/eval.py build                  # once: cases.jsonl + photos/
    python3 evals/per-ad/eval.py run haiku low          # one config -> results/haiku-low.jsonl
    python3 evals/per-ad/eval.py run sonnet high --only 298522676   # re-run just these cases
    python3 evals/per-ad/eval.py score                  # every results/*.jsonl -> report.md
    python3 evals/per-ad/eval.py add <id> [--expect import|skip:<code>] [--set field=value ...]
                                                        # put one real (problem) ad in the set

Offline: no browser, no OLX, nothing written to the site. Each case is the sheet a
per-ad agent saw (rebuilt from .runs/ and .contracts/), sent through the SAME call
`olx-loop.py` makes in production (`scripts/decide.py`: prompt + `claude -p`).

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
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../.."))
H = os.path.join(ROOT, "harness/3ceasuri-import")
sys.path.insert(0, os.path.join(H, "scripts"))
import decide        # noqa: E402  - the production prompt + claude call (olx-loop.py)
import infer_fields  # noqa: E402
import olx_import    # noqa: E402

CASES = os.path.join(HERE, "cases.jsonl")
PHOTOS = os.path.join(HERE, "photos")
RESULTS = os.path.join(HERE, "results")

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

    added = [c for c in load_cases() if c.get("added")]          # `add`ed cases survive
    cases = [make_case(e["id"], "import" if e["event"] == "import" else "skip",
                       None if e["event"] == "import" else e["reason"].split(":")[0])
             for e in picked]
    ids = {c["id"] for c in cases}
    write_cases(cases + [c for c in added if c["id"] not in ids])
    print("built %d cases (+%d added kept) -> %s" % (len(cases), len(added), os.path.relpath(CASES, ROOT)))
    print(collections.Counter(c["expected"]["decision"] + ":" + (c["expected"]["skip_code"] or c["profile"])
                              for c in load_cases()))


def load_cases():
    return [json.loads(l) for l in open(CASES)] if os.path.exists(CASES) else []


def write_cases(cases):
    with open(CASES, "w") as out:
        for c in cases:
            out.write(json.dumps(c, ensure_ascii=False) + "\n")
    keep = {os.path.basename(p) for c in cases for p in c["photos"]}
    for f in os.listdir(PHOTOS):                                  # photos of dropped cases
        if f not in keep:
            os.remove(os.path.join(PHOTOS, f))


def make_case(ad_id, decision, skip_code=None, sets=()):
    """One case from an ad's local logs (.runs/ + .contracts/ + .photos/): the inputs of
    the sheet its agent saw, and what is expected. For an import the expected fields are
    the contract's (what production sent); `sets` ('field=value') corrects them."""
    for need in (".runs/olx-%s-pass1.log", ".runs/olx-%s.json", ".contracts/olx-%s.json"):
        if not os.path.exists(os.path.join(H, need % ad_id)):
            raise SystemExit("no %s - the ad was never through pass 1 on this machine"
                             % (need % ad_id))
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
    os.makedirs(PHOTOS, exist_ok=True)
    photos = []
    for i, p in enumerate((run.get("photos") or [])[:2]):
        dst = os.path.join(PHOTOS, "%s-%02d.jpg" % (ad_id, i + 1))
        shutil.copy(p, dst)
        photos.append(os.path.relpath(dst, HERE))
    imp = decision == "import"
    fields = {f: final.get(f) for f in todo if f != "description"} if imp else None
    if sets:
        if not imp:
            raise SystemExit("--set only applies to an expected import")
        parse = _step().parse_pair
        for pair in sets:
            k, v = parse(pair)
            fields[k] = v
    return {
        "id": ad_id, "profile": run["profile"], "extract": run.get("extract"),
        "models": run.get("models"), "photos": photos, "seed": seed,
        "seller_title": title, "seller_text": text,
        "expected": {"decision": "import" if imp else "skip",
                     "skip_code": None if imp else skip_code,
                     "fields": fields,
                     "description": final.get("description") if imp else None},
    }


def add(ad_id, expect=None, sets=()):
    """Put one real ad in the set - typically one that went wrong - with the right answer."""
    if expect is None:                           # default: what production did
        last = [e for e in map(json.loads, open(os.path.join(ROOT, "history.jsonl")))
                if str(e.get("id")) == str(ad_id)]
        if not last:
            raise SystemExit("%s is not in history.jsonl - pass --expect" % ad_id)
        e = last[-1]
        expect = "import" if e["event"] == "import" else "skip:" + e["reason"].split(":")[0]
    decision, _, code = expect.partition(":")
    if decision not in ("import", "skip") or (decision == "skip" and code not in decide.SKIP_CODES):
        raise SystemExit("--expect is import or skip:<%s>" % "|".join(decide.SKIP_CODES))
    case = make_case(str(ad_id), decision, code or None, sets)
    case["added"] = time.strftime("%Y-%m-%d")
    write_cases([c for c in load_cases() if c["id"] != case["id"]] + [case])
    print("added %s: expected %s" % (ad_id, json.dumps(case["expected"]["fields"] if decision == "import"
                                                        else expect, ensure_ascii=False)))
    if decision == "import":
        print("check the expected fields above; correct any with --set field=value and add again")
    print("not scored until the next `run` of each config")


# --- run -------------------------------------------------------------------------
def prompt_for(case, step):
    """The production prompt (decide.build_prompt) for the sheet this case's agent saw."""
    photos = [os.path.join(HERE, p) for p in case["photos"]]
    sh = step.sheet("evals/queue.json", case["id"], case["profile"], case["seed"],
                    case["extract"], photos, models=case["models"])
    return decide.build_prompt(sh, case["seller_text"])


def run_one(case, model, effort, step):
    r = decide.call(prompt_for(case, step), model, effort, [PHOTOS])
    return {"id": case["id"], "model": model, "effort": effort,
            "served_by": r["served_by"], "error": r["error"], "raw": r["raw"],
            "answer": r["answer"], "cost_usd": r["cost_usd"],
            "seconds": r["seconds"], "turns": r["turns"]}


def run(model, effort, jobs=6, limit=None, only=None):
    """Every case -> results/<model>-<effort>.jsonl. `only` (ids) re-runs just those
    and replaces their rows, keeping the rest - to check one fix on the case that needed it."""
    cases = load_cases()[:limit]
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "%s-%s.jsonl" % (model, effort))
    kept = []
    if only:
        cases = [c for c in cases if c["id"] in only]
        if os.path.exists(path):
            kept = [l for l in open(path) if json.loads(l)["id"] not in only]
    step = _step()
    with open(path, "w") as out, concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        out.writelines(kept)
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
        only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
        lim = a[3] if len(a) > 3 and a[3].isdigit() else None
        run(a[1], a[2], limit=int(lim) if lim else None, only=only)
    elif a[:1] == ["score"]:
        score()
    elif a[:1] == ["add"] and len(a) >= 2:
        exp = a[a.index("--expect") + 1] if "--expect" in a else None
        sets = [a[i + 1] for i, x in enumerate(a) if x == "--set"]
        add(a[1], exp, sets)
    else:
        print(__doc__)
        sys.exit(1)
