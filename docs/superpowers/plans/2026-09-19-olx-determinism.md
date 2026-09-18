# OLX Harness Determinism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OLX import loop deterministic enough that a Haiku-class model runs a full 20-watch session unattended, by moving every remaining judgement call into code or into a written decision table.

**Architecture:** The browser-use payload scripts stay the unit of work (one cold process per watch, marker lines on stdout). Three things change: the two 95%-identical importers collapse into one shared flow module; the extraction contract stops travelling through a shell variable and becomes a pre-filled JSON draft on disk that the model edits in place; and the `REVIEW:` gate stops being a prose judgement and starts emitting machine-readable reason codes each tagged `fix` or `skip`. The candidates file becomes a status-bearing work queue so a continuous loop never depends on the model's memory.

**Tech Stack:** Python 3.9+ (no third-party deps — the payloads run inside `browser-use`), plain-script offline tests (`check()` assertions, run with `python3`, no pytest), CDP-controlled Chrome via the `browser-use` CLI.

**Spec:** `docs/superpowers/specs/2026-09-18-olx-determinism-handover.md` (§5 levers, §6 decisions). Read §3 for why each change exists; read §6 before questioning a design choice — those were decided by the user on 2026-09-19.

## Global Constraints

Copied verbatim from the spec's "HARD INVARIANTS". Every task's requirements implicitly include this section.

1. Never import a suspiciously cheap listing. `price_sanity.py` is the single source of floors; `CONFIRM=1` does not wave one through.
2. Ground truth for "is this imported / how many" is the 3ceasuri.ro admin, never a local file.
3. `movement` must never silently default to quartz. An ad that states no movement stops for review.
4. Route by kind, not by category (a smartwatch in 1677 goes to the smartwatch importer).
5. Verify by page content / readback, never by a return value. Never retry on the "Inspected target navigated or closed" exception — that is the success path, and a retry double-imports.
6. Read OLX only from a page already on `www.olx.ro` (a plain GET is 403).
7. A field the model blanks in the draft is still CLEARED. The draft file is the whole contract — it removes retyping, not the clearing semantics.
8. The agent NEVER overrides a `REVIEW:` gate. It applies the fix the gate names, or logs a skip with the gate's reason code.
9. Scripts are **browser-use payloads**: `AD_ID=… browser-use < script.py`, never `python3 script.py`. The exceptions are the two new non-browser CLIs (`candidates.py`, `olx-log-result.py`), which ARE run with `python3`.
10. Tests are plain scripts using the existing `check(cond, msg)` helper and run as `python3 harness/3ceasuri-import/tests/test_x.py`. Do not introduce pytest.
11. Commit straight to `main`. No branches, no PRs.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `harness/3ceasuri-import/scripts/olx_import.py` | The shared per-ad import flow, both profiles. Everything that is today duplicated between the two importers. |
| `harness/3ceasuri-import/scripts/contract_draft.py` | Build / write / read the seeded contract draft. File I/O and `_todo` computation, kept out of `infer_fields.py` so that stays a pure schema+prompt+validator. |
| `harness/3ceasuri-import/scripts/candidates.py` | The candidates file as a work queue: `next_pending`, `mark`, plus a `python3 candidates.py` CLI. No browser. |
| `harness/3ceasuri-import/scripts/olx-log-result.py` | Appends a `RESULT:`/`SKIP:` payload to `history.jsonl` and bumps `state.json`. No browser. |
| `harness/3ceasuri-import/tests/test_contract_draft.py` | Unit tests for the draft module. |
| `harness/3ceasuri-import/tests/test_candidates.py` | Unit tests for the work queue. |
| `harness/3ceasuri-import/tests/test_review_codes.py` | Tests that every review reason carries a code and an action. |
| `OLX_IMPORT_SESSION_PROMPT.md` | The paste-per-session prompts (setup+discovery, then the continuous loop). |
| `harness/3ceasuri-import/eval/replay.py` | Offline replay of historical ads for measurement. |

**Modified files:**

| Path | Change |
|---|---|
| `harness/3ceasuri-import/scripts/olx-import-watch.py` | Collapses to a ~20-line wrapper calling `olx_import.run("classic", globals())`. |
| `harness/3ceasuri-import/scripts/olx-import-smartwatch.py` | Same, with `"smart"`. |
| `harness/3ceasuri-import/scripts/olx-find-watches.py` | New near-zero-FP drop rules; writes queue fields. |
| `harness/3ceasuri-import/scripts/olx-find-smartwatches.py` | Same. |
| `harness/3ceasuri-import/scripts/infer_fields.py` | `REQUIRED_BY_PROFILE`; prompt shrinks to the `_todo` rules. |
| `harness/3ceasuri-import/tests/test_olx_import.py` | Extended for the draft and review-code paths. |
| `harness/3ceasuri-import/tests/test_olx_find.py` | Extended for the new drop rules and queue fields. |
| `.claude/skills/*/SKILL.md` | Rewritten as imperative cores (Task 10). |
| `.gitignore` | Add `.contracts/`. |
| `.claude/settings.local.json` | Bash allowlist so an unattended run does not stall. |

---

## Task 1: Collapse the two importers into one shared flow

Doing this first means every later task is written once instead of twice. It is a pure refactor: no behaviour may change, and the existing suite is the proof.

**Files:**
- Create: `harness/3ceasuri-import/scripts/olx_import.py`
- Modify: `harness/3ceasuri-import/scripts/olx-import-watch.py` (replace lines 37-308 with a wrapper)
- Modify: `harness/3ceasuri-import/scripts/olx-import-smartwatch.py` (replace lines 37-290 with a wrapper)
- Test: `harness/3ceasuri-import/tests/test_olx_import.py`

**Interfaces:**
- Consumes: `olx_api`, `admin_import`, `infer_fields`, `price_sanity` (unchanged).
- Produces: `olx_import.run(profile, g)` where `profile` is `"classic"` or `"smart"` and `g` is the payload's `globals()` dict carrying the CDP helpers (`js`, `new_tab`, `close_tab`, `switch_tab`, `goto_url`, `list_tabs`). Returns `None`; exits via `SystemExit` like the scripts do today. Later tasks call this same entry point.

- [ ] **Step 1: Capture current behaviour as a golden test**

Append to `harness/3ceasuri-import/tests/test_olx_import.py`, just above the final `fails` report:

```python
# --- 16. the two profiles stay distinct after the collapse -------------------
_ov_c = {"brand": "Seiko", "model": "Prospex MM200", "price": 3500, "currency": "RON",
         "movement": "automatic", "is_wristwatch": True, "is_bulk_lot": False}
_ov_s = {"brand": "Garmin", "model": "Fenix 7X Solar", "price": 1700, "currency": "RON",
         "connectivity": "no_gsm", "compatibility": "both",
         "is_wristwatch": True, "is_bulk_lot": False}
m_c, _ = run(CLASSIC, CLASSIC_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov_c)})
m_s, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov_s)})
check(m_c["INFER"]["movement"] == "automatic", "16: classic movement %r" % m_c["INFER"].get("movement"))
check(m_s["INFER"]["movement"] == "smart", "16: smart profile must force movement=smart")
check(m_s["INFER"]["style"] == "smart" and m_s["INFER"]["displayType"] == "smart",
      "16: smart profile must force style/displayType")
check(m_c["INFER"].get("connectivity") is None, "16: classic must not invent connectivity")
check(m_c["RESULT"]["state_entry"]["category"] == "wrist", "16: classic state_entry carries category")
check("category" not in m_s["RESULT"]["state_entry"], "16: smart state_entry omits category")
```

- [ ] **Step 2: Run it to confirm it passes against today's code**

Run: `python3 harness/3ceasuri-import/tests/test_olx_import.py`
Expected: `ALL CHECKS PASSED`. This is a characterisation test — it must pass BEFORE the refactor, and still pass after.

- [ ] **Step 3: Commit the golden test**

```bash
git add harness/3ceasuri-import/tests/test_olx_import.py
git commit -m "test: pin the classic/smart profile differences before collapsing the importers"
```

- [ ] **Step 4: Create the shared flow module**

Create `harness/3ceasuri-import/scripts/olx_import.py`. Move the body of `olx-import-watch.py` (lines 37-308) into `def run(profile, g):`, indenting it, and replace every bare CDP helper with a lookup from `g`. The profile-specific parts — currently the only real differences — become conditionals. The complete profile-divergence list, taken from `diff olx-import-watch.py olx-import-smartwatch.py`:

```python
PROFILES = {
    "classic": {
        "category_const": "CATEGORY_WATCHES",
        "script_name": "olx-import-watch.py",
        "brand_from_description": True,   # classic also matches the brand in the body
        "forced": {},                     # nothing is forced
        "regex_baseline": True,           # diameter + reference + year + movement regexes
        "state_entry_category": True,
    },
    "smart": {
        "category_const": "CATEGORY_SMARTWATCH",
        "script_name": "olx-import-smartwatch.py",
        "brand_from_description": False,
        "forced": {"movement": "smart", "style": "smart",
                   "displayType": "smart", "category": "wrist"},
        "regex_baseline": False,          # only the diameter regex
        "state_entry_category": False,
    },
}
```

Keep every comment from the original — they are the record of why each line exists (the `referință` capture bug, the `wrong_page` phone guard, the Poljot movement default). Losing them is a regression even though no test catches it.

- [ ] **Step 5: Reduce the two payloads to wrappers**

Replace `harness/3ceasuri-import/scripts/olx-import-watch.py` entirely with:

```python
#!/usr/bin/env python3
# =============================================================================
# olx-import-watch.py — one-shot importer for a single OLX classic-watch ad
# (category 1677, moda/ceasuri). The flow lives in olx_import.py; this file only
# picks the profile, so the classic and smart paths cannot drift apart.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   AD_ID=266008409 browser-use < .../olx-import-watch.py            # pass 1
#   AD_ID=266008409 CONFIRM=1 browser-use < .../olx-import-watch.py  # pass 2
#
# Env and marker lines: see olx_import.py.
# =============================================================================
import os, sys

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import olx_import

olx_import.run("classic", globals())
```

And `olx-import-smartwatch.py` identically, with `olx_import.run("smart", globals())` and the category-1943 header.

- [ ] **Step 6: Run the full suite**

Run: `python3 harness/3ceasuri-import/tests/test_olx_import.py && python3 harness/3ceasuri-import/tests/test_olx_find.py`
Expected: `ALL CHECKS PASSED` from both, with check 16 among them. If any check fails, the refactor changed behaviour — fix the refactor, never the test.

- [ ] **Step 7: Commit**

```bash
git add harness/3ceasuri-import/scripts/
git commit -m "harness: collapse the two OLX importers onto one shared flow

95% of olx-import-watch.py and olx-import-smartwatch.py was identical, so every
rule change had to be made twice and drift between them was a silent correctness
bug. The flow now lives in olx_import.run(profile, globals()); the two payloads
are wrappers that pick a profile. No behaviour change -- the profile differences
are pinned by check 16."
```

---

## Task 2: The contract draft module

Pure logic, no browser, no wiring. Lever B, first half.

**Files:**
- Create: `harness/3ceasuri-import/scripts/contract_draft.py`
- Create: `harness/3ceasuri-import/tests/test_contract_draft.py`
- Modify: `harness/3ceasuri-import/scripts/infer_fields.py` (add `REQUIRED_BY_PROFILE`)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `infer_fields.SCHEMA_FIELDS`, `infer_fields.validate`.
- Produces:
  - `infer_fields.REQUIRED_BY_PROFILE: dict[str, list[str]]`
  - `contract_draft.draft_path(project_root: str, ad_id: str) -> str`
  - `contract_draft.todo_fields(data: dict, profile: str) -> list[str]`
  - `contract_draft.build(data: dict, profile: str) -> dict` — the full contract plus `"_todo"`
  - `contract_draft.write(path: str, draft: dict) -> None`
  - `contract_draft.read(path: str, profile: str) -> tuple[dict, list[str]]` — `(payload, problems)`; `payload` has `_todo` stripped; `problems` is empty when usable.

- [ ] **Step 1: Write the failing tests**

Create `harness/3ceasuri-import/tests/test_contract_draft.py`:

```python
#!/usr/bin/env python3
"""Offline tests for the seeded contract draft (no browser, no network)."""
import json, os, sys, tempfile

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import contract_draft, infer_fields

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

BASE = {"brand": "Apple", "condition": "good", "gender": "unisex",
        "price": 1150, "currency": "RON", "description": "Vand Apple Watch, stare buna.",
        "phone": "0722333444", "caseMat": "aluminium"}

# 1. the draft carries the whole contract, not just the open fields
d = contract_draft.build(BASE, "smart")
check(d["brand"] == "Apple" and d["price"] == 1150, "1: mapped params missing from the draft")
check(d["description"] == BASE["description"], "1: description must be pre-filled, never retyped")
check(d["phone"] == "0722333444", "1: phone must be pre-filled")
for f in infer_fields.SCHEMA_FIELDS:
    check(f in d, "1: draft is not a whole contract, missing %s" % f)

# 2. _todo names what the model must decide, and nothing it already has
check("model" in d["_todo"], "2: model must always be asked")
check("connectivity" in d["_todo"] and "compatibility" in d["_todo"],
      "2: smart facets must be asked")
check("brand" not in d["_todo"], "2: a field the baseline filled must not be asked")
check("movement" not in d["_todo"], "2: smart forces movement, it is not the model's call")

dc = contract_draft.build(BASE, "classic")
check("movement" in dc["_todo"], "2: classic must always ask movement (never default quartz)")
check("connectivity" not in dc["_todo"], "2: classic must not ask smart facets")

# 3. a field the baseline could not fill is asked; one it filled is not
check("gender" not in contract_draft.todo_fields(BASE, "smart"), "3: gender was known")
check("gender" in contract_draft.todo_fields({k: v for k, v in BASE.items() if k != "gender"},
                                             "smart"), "3: empty gender must be asked")

# 4. round-trip: write, edit as the model would, read back
path = os.path.join(tempfile.mkdtemp(), "olx-1.json")
contract_draft.write(path, d)
edited = json.load(open(path))
edited.update({"model": "Watch Series 9", "connectivity": "no_gsm",
               "compatibility": "ios", "is_wristwatch": True, "is_bulk_lot": False})
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(problems == [], "4: clean draft rejected: %s" % problems)
check("_todo" not in payload, "4: _todo must be stripped before the merge")
check(payload["model"] == "Watch Series 9", "4: edit lost")
check(payload["description"] == BASE["description"], "4: description lost on read")

# 5. clearing semantics survive -- a field the model BLANKS is cleared
edited["gender"] = None
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(problems == [], "5: blanking a field is legal: %s" % problems)
check(payload["gender"] is None, "5: a blanked field must stay null, not be restored")

# 6. an unanswered REQUIRED field is a problem, not a silent null
edited["model"] = None
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(any("model" in p for p in problems), "6: null model must be reported: %s" % problems)

# 7. nullable-by-design fields are never required
edited["model"] = "Watch Series 9"
edited["reference"] = None
edited["notes"] = None
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(problems == [], "7: reference/notes are legitimately null: %s" % problems)

# 8. an illegal enum is caught on read, by infer_fields.validate
edited["connectivity"] = "LTE"
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(any("connectivity" in p for p in problems), "8: illegal enum not caught: %s" % problems)

# 9. a key outside the contract is rejected (the `series` class of mistake)
edited["connectivity"] = "no_gsm"
edited["series"] = "Series 9"
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(any("series" in p for p in problems), "9: unknown key not rejected: %s" % problems)

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 harness/3ceasuri-import/tests/test_contract_draft.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'contract_draft'`.

- [ ] **Step 3: Add the required-field table to infer_fields.py**

Insert after the `SCHEMA_FIELDS` definition (currently line 66):

```python
# Fields the filled contract MUST answer non-null, per profile. Everything else in
# SCHEMA_FIELDS may legitimately be null — a watch with no reference, no year and no
# notes is the common case, and demanding those would turn honest silence into a gate.
REQUIRED_BY_PROFILE = {
    "classic": ["brand", "model", "price", "movement", "is_wristwatch"],
    "smart":   ["brand", "model", "price", "connectivity", "compatibility", "is_wristwatch"],
}

# What the model decides, per profile. ALWAYS_ASK is asked even when a regex guessed a
# value, because copying a guess is how `movement` silently became quartz on a 1970s
# Poljot. ASK_IF_EMPTY is asked only when the deterministic baseline came up empty.
ALWAYS_ASK = {
    "classic": ["model", "movement", "reference", "is_wristwatch", "is_bulk_lot", "notes"],
    "smart":   ["model", "connectivity", "compatibility", "is_wristwatch", "is_bulk_lot", "notes"],
}
ASK_IF_EMPTY = ["category", "year", "diameter", "gender", "condition",
                "caseMat", "braceletMat", "displayColor"]
```

- [ ] **Step 4: Write the draft module**

Create `harness/3ceasuri-import/scripts/contract_draft.py`:

```python
#!/usr/bin/env python3
"""The seeded contract draft — the contract as a file the model edits in place.

Before this, pass 2 took the filled contract through OVERRIDES='{…}', a single-quoted
shell variable. Two things went wrong with that and neither was the model's fault:
Romanian ad text contains apostrophes ("anii '70"), which terminate the quoting; and
because a field omitted from the answer is CLEARED, the model had to retype the entire
seller description to avoid deleting it.

So pass 1 now writes the WHOLE contract to disk, pre-filled with everything the
deterministic baseline knows, with the open fields null and named in `_todo`. The model
edits those and nothing else.

The clearing semantics are unchanged and deliberately so: the file IS the contract, so a
field the model blanks is still cleared. What disappears is the retyping, not the rule —
two half-authoritative sources is how fields go silently wrong (see infer_fields).
"""

import json
import os

import infer_fields

DRAFT_SUBDIR = "harness/3ceasuri-import/.contracts"

# Null is a legitimate answer for these, so `read` never demands a value.
NULLABLE = {"reference", "year", "notes", "priceNote", "seller", "phone", "location"}


def draft_path(project_root, ad_id):
    return os.path.join(project_root, DRAFT_SUBDIR, "olx-%s.json" % ad_id)


def todo_fields(data, profile):
    """The fields this ad's model must decide. Deterministic — the script chooses.

    ALWAYS_ASK is asked even when the baseline guessed a value, because copying a
    guess is how `movement` silently became quartz on a 1970s Poljot. ASK_IF_EMPTY is
    asked only when the baseline came up empty. A field the profile FORCES (smart:
    movement/style/displayType/category) appears in neither list — it is the
    category's own answer, and asking would invite a routing mistake.
    """
    todo = list(infer_fields.ALWAYS_ASK[profile])
    for f in infer_fields.ASK_IF_EMPTY:
        if f not in todo and data.get(f) in (None, ""):
            todo.append(f)
    return todo


def build(data, profile):
    """A complete contract, pre-filled, with `_todo` naming what is left to decide."""
    draft = {f: data.get(f) for f in infer_fields.SCHEMA_FIELDS}
    draft["_todo"] = todo_fields(data, profile)
    return draft


def write(path, draft):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(draft, f, ensure_ascii=False, indent=1, sort_keys=True)


def read(path, profile):
    """(payload, problems). `problems` empty means usable; `_todo` is stripped."""
    try:
        with open(path) as f:
            payload = json.load(f)
    except Exception as e:
        return {}, ["could not read the contract draft %s: %s" % (path, e)]
    if not isinstance(payload, dict):
        return {}, ["the contract draft must be a JSON object"]

    payload.pop("_todo", None)
    problems = infer_fields.validate(payload)
    for f in infer_fields.REQUIRED_BY_PROFILE[profile]:
        if payload.get(f) is None:
            problems.append("%s is required and was left null in the draft" % f)
    return payload, problems
```

- [ ] **Step 5: Run the tests**

Run: `python3 harness/3ceasuri-import/tests/test_contract_draft.py`
Expected: `ALL CHECKS PASSED`.

- [ ] **Step 6: Ignore the draft directory**

Append to `.gitignore`:

```
# per-ad contract drafts, written by pass 1 and consumed by pass 2
harness/3ceasuri-import/.contracts/
```

- [ ] **Step 7: Commit**

```bash
git add harness/3ceasuri-import/scripts/contract_draft.py harness/3ceasuri-import/scripts/infer_fields.py harness/3ceasuri-import/tests/test_contract_draft.py .gitignore
git commit -m "harness: the contract as a seeded draft file the model edits in place

Pass 1 will pre-fill the whole contract on disk with the open fields null and
named in _todo. Clearing semantics are unchanged -- the file IS the contract, so
a blanked field is still cleared -- but nothing gets retyped, which removes both
the shell-quoting failures and the description transcription surface.

Module only; wiring is the next commit."
```

---

## Task 3: Wire the draft into pass 1 and pass 2

Lever B, second half.

**Files:**
- Modify: `harness/3ceasuri-import/scripts/olx_import.py` (the pass-1 emit block and the OVERRIDES merge)
- Modify: `harness/3ceasuri-import/scripts/infer_fields.py` (`build_prompt` gains `todo=`)
- Test: `harness/3ceasuri-import/tests/test_olx_import.py`

**Interfaces:**
- Consumes: `contract_draft.build/write/read/draft_path`, `infer_fields.build_prompt`.
- Produces: pass 1 emits `EXTRACT_PROMPT: {ad_id, prompt, draft, todo, photos, photos_failed, phone_status, rerun}` where `draft` is the absolute path. Pass 2 reads that path when `OVERRIDES` is empty. `OVERRIDES` keeps working and wins over the draft, for human one-off fixes.

- [ ] **Step 1: Write the failing tests**

Append to `harness/3ceasuri-import/tests/test_olx_import.py`:

```python
# --- 17. pass 1 writes a seeded draft; pass 2 reads it -----------------------
import contract_draft
_dp = contract_draft.draft_path(ROOT, SMART_AD["id"])
if os.path.exists(_dp):
    os.remove(_dp)
m, st = run(SMART, SMART_AD)
check("EXTRACT_PROMPT" in m, "17: pass 1 must still emit the contract")
check(m["EXTRACT_PROMPT"]["draft"] == _dp, "17: pass 1 must report the draft path")
check(os.path.exists(_dp), "17: pass 1 must write the draft to disk")
_d = json.load(open(_dp))
check(_d["description"].startswith("Ceas in stare foarte buna"),
      "17: the draft must carry the cleaned description, so it is never retyped")
check(_d["brand"] == "Garmin" and _d["price"] == 1700, "17: draft missing mapped params")
check("model" in _d["_todo"] and "connectivity" in _d["_todo"], "17: _todo wrong: %s" % _d["_todo"])
check(st["imported"] is None, "17: pass 1 must still write nothing")

# the model edits the draft, then pass 2 runs with no OVERRIDES at all
_d.update({"model": "Fenix 7X Solar", "connectivity": "no_gsm", "compatibility": "both",
           "is_wristwatch": True, "is_bulk_lot": False, "notes": None})
json.dump(_d, open(_dp, "w"))
m2, st2 = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(m2.get("RESULT", {}).get("ok") is True, "17: pass 2 must import from the draft: %s" % m2.get("REVIEW"))
check(m2["INFER"]["model"] == "Fenix 7X Solar", "17: the edit did not reach the form")
check(m2["INFER"]["description"].startswith("Ceas in stare foarte buna"),
      "17: description lost between draft and form")

# --- 18. blanking a field in the draft still clears it -----------------------
_d["gender"] = None
json.dump(_d, open(_dp, "w"))
m3, _ = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(m3["INFER"].get("gender") is None,
      "18: a field blanked in the draft must be CLEARED, not restored from the params")

# --- 19. OVERRIDES still wins, for a human one-off fix -----------------------
m4, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps({"model": "Fenix 7"})})
check(m4["INFER"]["model"] == "Fenix 7", "19: OVERRIDES must override the draft")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 harness/3ceasuri-import/tests/test_olx_import.py`
Expected: FAIL on `17: pass 1 must report the draft path` (the `EXTRACT_PROMPT` payload has no `draft` key yet).

- [ ] **Step 3: Teach the prompt to target the open fields**

In `harness/3ceasuri-import/scripts/infer_fields.py`, change `build_prompt` to take `todo=None` and, when given, prepend a directive and list only those field lines:

```python
def build_prompt(text, brands=(), profile="classic", known=None,
                 source_noun="post text", todo=None):
    rules = PROFILES.get(profile)
    if rules is None:
        raise ValueError("unknown profile %r (have: %s)" % (profile, ", ".join(sorted(PROFILES))))
    if todo:
        fields = "\n".join(l for l in _field_lines().splitlines()
                           if l.split("`")[1] in todo)
        head = ("**Edit the draft file named above. Change ONLY these fields; everything\n"
                "else is already filled in and correct. A field you blank is CLEARED.**\n\n")
    else:
        fields, head = _field_lines(), ""
    return PROMPT.format(rules=rules,
                         fields=head + fields,
                         brands=", ".join(sorted(brands)) or "(none)",
                         known=_known_block(known),
                         source_noun=source_noun,
                         source_noun_title=source_noun[:1].upper() + source_noun[1:],
                         text=(text or "").strip())
```

- [ ] **Step 4: Write the draft in pass 1**

In `olx_import.py`, inside the pass-1 branch (the `if not OVERRIDES and not SKIP_PROMPT and not DRY_RUN:` block), after the photos and phone are collected and before `emit("EXTRACT_PROMPT", …)`:

```python
        draft = contract_draft.build(data, profile)
        dpath = contract_draft.draft_path(PROJECT_ROOT, AD_ID)
        contract_draft.write(dpath, draft)
        emit("EXTRACT_PROMPT", {
            "ad_id": AD_ID,
            "draft": dpath,
            "todo": draft["_todo"],
            "prompt": infer_fields.build_prompt(text, brand_ids.keys(), profile=profile,
                                                known=known, source_noun="OLX ad",
                                                todo=draft["_todo"]),
            "photos": photos, "photos_failed": failed, "phone_status": phone_status,
            "rerun": "AD_ID=%s CONFIRM=1 browser-use < .../%s" % (AD_ID, conf["script_name"])})
        raise SystemExit(0)
```

- [ ] **Step 5: Read the draft in pass 2**

Replace the start of the "filled contract is authoritative" section. `OVERRIDES` keeps precedence so a human can still patch one field from the shell:

```python
    # The draft file is the contract. OVERRIDES stays supported and WINS, because a
    # human fixing one field from the shell should not have to edit the file.
    dpath = contract_draft.draft_path(PROJECT_ROOT, AD_ID)
    filled, problems = ({}, [])
    if os.path.exists(dpath):
        filled, problems = contract_draft.read(dpath, profile)
        if problems and not OVERRIDES:
            emit("REVIEW", {"ad_id": AD_ID, "draft": dpath,
                            "reasons": [{"code": "draft_invalid", "action": "fix",
                                         "message": m} for m in problems]})
            raise SystemExit(0)
    if OVERRIDES:
        bad = infer_fields.validate(OVERRIDES)
        if bad:
            die("OVERRIDES are not valid DB values: " + "; ".join(bad))
        filled.update(OVERRIDES)

    IS_CONTRACT = bool(filled) and "is_wristwatch" in filled
    if IS_CONTRACT:
        for f in infer_fields.SCHEMA_FIELDS:
            if f not in filled:
                data.pop(f, None)
    data.update({k: v for k, v in filled.items() if k != "force"})
```

Every later reference to `OVERRIDES.get(...)` in the gates (the `is_wristwatch` and `is_bulk_lot` skip checks) becomes `filled.get(...)`.

Two ordering details that are easy to get wrong:
- This block **replaces** the old `problems = infer_fields.validate(OVERRIDES)` / `die(...)` pair at the top of the section. Do not leave both — the old one runs `validate({})` on an empty `OVERRIDES` and passes, which would mask a bad draft.
- `IS_CONTRACT` must be computed from `filled` **after** the `OVERRIDES` merge, not from `OVERRIDES` alone. A human patching one field with `OVERRIDES='{"model":"X"}'` on top of a full draft must still get the full-contract clearing behaviour, and checking `OVERRIDES` alone would silently downgrade it to a partial merge.

- [ ] **Step 6: Run the suite**

Run: `python3 harness/3ceasuri-import/tests/test_olx_import.py && python3 harness/3ceasuri-import/tests/test_contract_draft.py`
Expected: `ALL CHECKS PASSED` from both.

- [ ] **Step 7: Commit**

```bash
git add harness/3ceasuri-import/scripts/ harness/3ceasuri-import/tests/
git commit -m "harness: pass 1 seeds the contract draft, pass 2 reads it

The contract no longer travels through OVERRIDES='{…}'. Pass 1 writes the whole
pre-filled contract to .contracts/olx-<id>.json with the open fields null and
listed in _todo; the model edits those and pass 2 reads the file. OVERRIDES still
works and still wins, for a human patching one field from the shell.

The prompt now lists only the _todo fields, which also shrinks what a continuous
session pays per watch."
```

---

## Task 4: REVIEW reason codes with a fix/skip action

Lever D. This is what turns "the model decides what a REVIEW means" into a table the script owns.

**Files:**
- Modify: `harness/3ceasuri-import/scripts/olx_import.py` (the confidence gate, currently around the `review = []` block)
- Create: `harness/3ceasuri-import/tests/test_review_codes.py`
- Test: `harness/3ceasuri-import/tests/test_olx_import.py`

**Interfaces:**
- Produces: `REVIEW: {ad_id, reasons: [{code, action, message, field}], …}` where `action` is `"fix"` (the gate names exactly what to supply, and the answer is already in hand) or `"skip"` (genuine doubt — log and move on). Consumed by the skills in Task 10 and by `olx-log-result.py` in Task 7.

- [ ] **Step 1: Write the failing test**

Create `harness/3ceasuri-import/tests/test_review_codes.py`:

```python
#!/usr/bin/env python3
"""Every review reason must be machine-readable: a code, and an action the runbook
can follow without judgement. Prose reasons are what made REVIEW: a coin flip."""
import os, re, sys

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
SRC = os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx_import.py")

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

src = open(SRC).read()

# 1. no bare-string review reasons survive
bare = re.findall(r"review\.append\(\s*[\"']", src)
check(not bare, "1: %d review.append() calls still push a bare string" % len(bare))

# 2. every review entry is built by the helper, with a legal action
codes = re.findall(r"_review\(\s*[\"']([a-z_]+)[\"']\s*,\s*[\"'](fix|skip)[\"']", src)
check(len(codes) >= 8, "2: expected >=8 coded review reasons, found %d" % len(codes))
check(len({c for c, _ in codes}) == len(codes), "2: duplicate review codes: %s" % codes)

# 3. the codes the runbook and the logger depend on all exist
for required in ("new_brand", "model_missing", "price_missing", "movement_missing",
                 "too_few_images", "thin_description", "misrouted_smart", "weak_repost"):
    check(any(c == required for c, _ in codes), "3: missing review code %r" % required)

# 4. doubt is never a 'fix' -- these must stop the watch, not be patched
for code, action in codes:
    if code in ("movement_missing", "weak_repost", "thin_description", "misrouted_smart"):
        check(action == "skip", "4: %s must be action=skip, is %r" % (code, action))

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 harness/3ceasuri-import/tests/test_review_codes.py`
Expected: FAIL on check 1 (bare-string `review.append(` calls) and check 2 (no `_review(` helper).

- [ ] **Step 3: Replace the confidence gate**

In `olx_import.py`, replace the `review = []` block with the coded version. Keep every existing condition and message — only the shape changes:

```python
    # --- 6. confidence gate --------------------------------------------------
    # Each reason carries a code and an action. `fix` means the gate named exactly
    # what to supply and the answer is already in hand. `skip` means genuine doubt:
    # the runbook logs it and takes the next candidate. The agent never overrides a
    # gate -- see §6 decision 5 in the determinism spec.
    review = []
    def _review(code, action, message, field=None):
        review.append({"code": code, "action": action, "message": message, "field": field})

    if not data.get("brand"):
        _review("brand_missing", "fix", "brand not inferred", "brand")
    elif data["brand"] not in brand_ids:
        _review("new_brand", "fix",
                "NEW brand '%s' — will be created in the DB" % data["brand"], "brand")
    if not data.get("model"):
        _review("model_missing", "fix", "model not inferred", "model")
    if data.get("price") is None:
        _review("price_missing", "fix", "price not inferred", "price")
    if profile == "classic":
        # movement is NOT optional in the DB, so the harness fills the gap with
        # 'quartz'. That guess mislabelled a 1970s Poljot once already — an ad that
        # never states its movement must be judged, not defaulted, and judging it
        # from nothing is exactly the doubt this gate exists to stop.
        if not data.get("movement"):
            _review("movement_missing", "skip",
                    "movement not stated in the ad (harness would default it to quartz)",
                    "movement")
        if data.get("movement") == "smart":
            _review("misrouted_smart", "skip",
                    "this is a smartwatch — import it with olx-import-smartwatch.py instead")
        if data.get("category") == "wall" and not data.get("caseMat"):
            _review("wall_no_material", "fix",
                    "wall clock without a case material (usually wood)", "caseMat")
    else:
        for f in ("connectivity", "compatibility"):
            if not data.get(f):
                _review("%s_missing" % f, "fix",
                        "smartwatch without %s (fill it in the draft)" % f, f)
    if len(images) < 2:
        _review("too_few_images", "skip", "only %d image(s) on the ad" % len(images))
    if len((data.get("description") or "").strip()) < 40:
        _review("thin_description", "skip",
                "description looks thin (%d chars)"
                % len((data.get("description") or "").strip()))
```

And the weak-repost branch in the stage-2 dedup section:

```python
        if not CONFIRM:
            emit("REVIEW", dict(detail, reasons=[{
                "code": "weak_repost", "action": "skip", "field": None,
                "message": "possible repost: model '%s' is already on the site, but the "
                           "name is generic and the brand could not be confirmed"
                           % data.get("model")}]))
            raise SystemExit(0)
```

- [ ] **Step 4: Run both tests**

Run: `python3 harness/3ceasuri-import/tests/test_review_codes.py && python3 harness/3ceasuri-import/tests/test_olx_import.py`
Expected: `ALL CHECKS PASSED` from both. Existing checks that assert on review text (check 7 and 11 in `test_olx_import.py`) search the reasons list — update them to search `r["message"] for r in m["REVIEW"]["reasons"]`.

- [ ] **Step 5: Commit**

```bash
git add harness/3ceasuri-import/scripts/olx_import.py harness/3ceasuri-import/tests/
git commit -m "harness: REVIEW reasons carry a code and a fix/skip action

The gate raised 8 different prose reasons and CONFIRM=1 passed all of them at
once, so a small model that learned 'REVIEW -> CONFIRM=1' would bulldoze a
mis-routed smartwatch with the same reflex it used for a thin description.

Each reason is now {code, action, message, field}. action=fix means the gate named
what to supply; action=skip means genuine doubt -- the runbook logs it and takes
the next candidate. Per §6 decision 5 the agent never overrides a gate, so the
per-gate acknowledgement scheme in the spec is not needed."
```

---

## Task 5: The candidates work queue

Lever G, first half. Plain module plus CLI — no browser.

**Files:**
- Create: `harness/3ceasuri-import/scripts/candidates.py`
- Create: `harness/3ceasuri-import/tests/test_candidates.py`

**Interfaces:**
- Produces:
  - `candidates.load(path) -> dict`
  - `candidates.next_pending(path) -> dict | None` — the first candidate whose `status` is `pending` or absent
  - `candidates.mark(path, ad_id, status, reason=None) -> bool` — sets `status`, `reason`, `ts`; returns False when the id is not in the file
  - `candidates.counts(path) -> dict` — `{pending, imported, skipped, error}`
  - CLI: `python3 candidates.py next <file>` prints the id or exits 1; `python3 candidates.py counts <file>` prints JSON.

- [ ] **Step 1: Write the failing tests**

Create `harness/3ceasuri-import/tests/test_candidates.py`:

```python
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

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 harness/3ceasuri-import/tests/test_candidates.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'candidates'`.

- [ ] **Step 3: Write the module**

Create `harness/3ceasuri-import/scripts/candidates.py`:

```python
#!/usr/bin/env python3
"""The candidates file as a work queue.

§6 decision 7 made the Haiku run one continuous session with no /clear between
watches, so nothing external tracks progress and "take the next unimported id"
cannot mean "remember which ones you did". Each candidate carries its own status,
written by the importer, so the queue survives a crash, a context checkpoint and a
fresh session equally well.

Also usable from the shell, deliberately without a browser:
    python3 candidates.py next   harness/3ceasuri-import/.candidates-olx-smart.json
    python3 candidates.py counts harness/3ceasuri-import/.candidates-olx-smart.json
"""

import json
import sys
import time

STATUSES = ("pending", "imported", "skipped", "error")


def load(path):
    with open(path) as f:
        return json.load(f)


def _save(path, doc):
    with open(path, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def next_pending(path):
    """The first candidate still to do, or None. Absent status counts as pending —
    files written before the queue existed are still usable."""
    for c in load(path).get("candidates", []):
        if c.get("status", "pending") == "pending":
            return c
    return None


def mark(path, ad_id, status, reason=None):
    """Record an outcome. Returns False when the id is not in this file."""
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % (STATUSES,))
    doc = load(path)
    for c in doc.get("candidates", []):
        if str(c.get("id")) == str(ad_id):
            c["status"] = status
            c["reason"] = reason
            c["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save(path, doc)
            return True
    return False


def counts(path):
    out = dict.fromkeys(STATUSES, 0)
    for c in load(path).get("candidates", []):
        out[c.get("status", "pending")] = out.get(c.get("status", "pending"), 0) + 1
    return out


if __name__ == "__main__":
    cmd, target = sys.argv[1], sys.argv[2]
    if cmd == "next":
        c = next_pending(target)
        if not c:
            print("QUEUE_EMPTY")
            sys.exit(1)
        print(c["id"])
    elif cmd == "counts":
        print(json.dumps(counts(target)))
    else:
        print("usage: candidates.py next|counts <file>")
        sys.exit(2)
```

- [ ] **Step 4: Run the tests**

Run: `python3 harness/3ceasuri-import/tests/test_candidates.py`
Expected: `ALL CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add harness/3ceasuri-import/scripts/candidates.py harness/3ceasuri-import/tests/test_candidates.py
git commit -m "harness: the candidates file becomes a work queue

Per-candidate status/reason/ts, plus next_pending() and a no-browser CLI. A
continuous session has no /clear between watches, so 'which watch is next' has to
be a command rather than something the model remembers across a checkpoint."
```

---

## Task 6: Wire the queue into discovery and the importer

Lever G, second half.

**Files:**
- Modify: `harness/3ceasuri-import/scripts/olx-find-watches.py` (the `json.dump` around line 219)
- Modify: `harness/3ceasuri-import/scripts/olx-find-smartwatches.py` (same block)
- Modify: `harness/3ceasuri-import/scripts/olx_import.py` (mark on every terminal path)
- Test: `harness/3ceasuri-import/tests/test_olx_find.py`, `harness/3ceasuri-import/tests/test_olx_import.py`

**Interfaces:**
- Consumes: `candidates.mark`.
- Produces: every candidate written by discovery carries `"status": "pending"`. The importer marks `imported` / `skipped` / `error` on every exit path, with the review code as the reason where there is one.

- [ ] **Step 1: Write the failing tests**

Append to `harness/3ceasuri-import/tests/test_olx_find.py` (adapt the variable names to that file's existing `run()` helper):

```python
# --- queue: discovery seeds every candidate as pending -----------------------
_doc = json.load(open(OUT))
check(all(c.get("status") == "pending" for c in _doc["candidates"]),
      "queue: discovery must seed status=pending on every candidate")
```

Append to `harness/3ceasuri-import/tests/test_olx_import.py`:

```python
# --- 20. the importer marks the queue on every terminal path -----------------
# test_olx_import.py imports json/os/re/sys/io/contextlib/time but NOT tempfile --
# add it to the imports at the top of the file as part of this step.
import tempfile
import candidates as _q
_qp = os.path.join(tempfile.mkdtemp(), "q.json")
json.dump({"source": "olx", "profile": "smart", "candidates":
           [{"id": str(SMART_AD["id"]), "status": "pending"}]}, open(_qp, "w"))
_d = json.load(open(contract_draft.draft_path(ROOT, SMART_AD["id"])))
_d.update({"model": "Fenix 7X Solar", "connectivity": "no_gsm", "compatibility": "both",
           "is_wristwatch": True, "is_bulk_lot": False})
json.dump(_d, open(contract_draft.draft_path(ROOT, SMART_AD["id"]), "w"))
m, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "CANDIDATES_FILE": _qp})
check(m.get("RESULT", {}).get("ok") is True, "20: should import")
check(_q.load(_qp)["candidates"][0]["status"] == "imported",
      "20: a successful import must mark the queue")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 harness/3ceasuri-import/tests/test_olx_find.py`
Expected: FAIL on `queue: discovery must seed status=pending`.

- [ ] **Step 3: Seed the status in discovery**

In both `olx-find-*.py`, inside the `candidates[aid] = {…}` dict literal, add as the last key:

```python
        "status": "pending",
```

- [ ] **Step 4: Mark the queue from the importer**

In `olx_import.py`, read the queue path from the environment near the other env vars:

```python
    CANDIDATES_FILE = os.environ.get("CANDIDATES_FILE", "").strip()
```

and add a helper used by every terminal path:

```python
    def _mark(status, reason=None):
        """Record this ad's outcome in the work queue, when one was passed.

        Never fatal: a bookkeeping failure must not lose an import that succeeded.
        """
        if not CANDIDATES_FILE:
            return
        try:
            candidates.mark(CANDIDATES_FILE, AD_ID, status, reason)
        except Exception as e:
            emit("WARN", {"ad_id": AD_ID, "msg": "could not mark the queue: %s" % e})
```

Call it: `_mark("skipped", <reason>)` immediately before each `emit("SKIP", …); raise SystemExit(0)`; `_mark("error", msg)` inside `die()`; `_mark("imported")` after a `RESULT:` whose `ok` is true, and `_mark("error", "import not verified")` when it is not.

- [ ] **Step 5: Run the full suite**

Run: `for t in harness/3ceasuri-import/tests/test_*.py; do echo "== $t"; python3 "$t"; done`
Expected: `ALL CHECKS PASSED` from all five.

- [ ] **Step 6: Commit**

```bash
git add harness/3ceasuri-import/scripts/ harness/3ceasuri-import/tests/
git commit -m "harness: discovery seeds the queue, the importer marks it

Every candidate is written status=pending and the importer records imported /
skipped / error on every terminal path, with the review code as the reason. A
marking failure emits WARN and is never fatal -- bookkeeping must not lose an
import that already succeeded."
```

---

## Task 7: The bookkeeping script

Lever F. Removes the hand-assembled `python3 -c` one-liner from the loop.

**Files:**
- Create: `harness/3ceasuri-import/scripts/olx-log-result.py`
- Test: extend `harness/3ceasuri-import/tests/test_candidates.py`

**Interfaces:**
- Consumes: a `RESULT:` or `SKIP:` marker line on stdin (the whole line, tag included).
- Produces: appends one object to `history.jsonl` with `event` (`import`/`skip`) and `ts` added; bumps `session_imported` / `session_skipped` in `state.json`. Prints `LOGGED: {event, id}`.

- [ ] **Step 1: Write the failing test**

Append to `harness/3ceasuri-import/tests/test_candidates.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 harness/3ceasuri-import/tests/test_candidates.py`
Expected: FAIL — the script does not exist, so `returncode` is 2.

- [ ] **Step 3: Write the script**

Create `harness/3ceasuri-import/scripts/olx-log-result.py`:

```python
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
    line = line.strip()
    for tag, event in (("RESULT:", "import"), ("SKIP:", "skip")):
        if line.startswith(tag):
            payload = json.loads(line[len(tag):])
            if event == "import":
                rec = dict(payload.get("state_entry") or {})
                if not payload.get("ok"):
                    return None, None          # unverified: nothing to record yet
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

    event, rec = parse(sys.stdin.read())
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
```

- [ ] **Step 4: Run the tests**

Run: `python3 harness/3ceasuri-import/tests/test_candidates.py`
Expected: `ALL CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add harness/3ceasuri-import/scripts/olx-log-result.py harness/3ceasuri-import/tests/test_candidates.py
git commit -m "harness: olx-log-result.py replaces the hand-built logging one-liner

Takes a RESULT:/SKIP: marker line on stdin, appends to history.jsonl with event
and ts, bumps the session counter. An unverified RESULT (ok:false) logs nothing,
so a failed import cannot be recorded as a success."
```

---

## Task 8: Near-zero-false-positive triage rules

Lever C, per §6 decision 2. Each new rule ships with a test proving it does **not** fire on a listing that was legitimately imported.

**Files:**
- Modify: `harness/3ceasuri-import/scripts/olx-find-smartwatches.py` (the filters block)
- Modify: `harness/3ceasuri-import/scripts/olx-find-watches.py` (the filters block)
- Test: `harness/3ceasuri-import/tests/test_olx_find.py`

**Interfaces:**
- Produces: two new drop reasons in `STATS.dropped` — `activation_locked`, `explicit_stock`.

- [ ] **Step 1: Write the failing tests**

Append to `harness/3ceasuri-import/tests/test_olx_find.py`:

```python
# --- new drop rules: activation lock and explicit stock ---------------------
# These must be near-zero-false-positive (§6 decision 2): each assertion below that a
# rule does NOT fire is a real historical listing shape that was legitimately imported.
import re as _re
SRC_SMART = open(os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-find-smartwatches.py")).read()
_ns = {}
exec(_re.search(r"^ACTIVATION_LOCK = .*?\)\n", SRC_SMART, _re.S | _re.M).group(0), {"re": _re}, _ns)
exec(_re.search(r"^EXPLICIT_STOCK = .*?\)\n", SRC_SMART, _re.S | _re.M).group(0), {"re": _re}, _ns)
LOCK, STOCK = _ns["ACTIVATION_LOCK"], _ns["EXPLICIT_STOCK"]

for t in ["Apple Watch blocat icloud, vand pentru piese",
          "are cont apple si nu stiu parola",
          "Activation lock activ, nu il pot debloca"]:
    check(bool(LOCK.search(t)), "lock: should fire on %r" % t)
for t in ["Apple Watch Series 9, resetat din fabrica, fara cont",
          "Se vinde cu contul sters, icloud deconectat",
          "Garmin Fenix, functioneaza impecabil"]:
    check(not LOCK.search(t), "lock: FALSE POSITIVE on %r" % t)

for t in ["Peste 100 bucati disponibile", "lichidari de stocuri, desigilate",
          "avem 20 bucati pe stoc"]:
    check(bool(STOCK.search(t)), "stock: should fire on %r" % t)
for t in ["Vand 1 bucata, stare buna", "ultima bucata ramasa",
          "Ceas Seiko automatic, cutie si acte"]:
    check(not STOCK.search(t), "stock: FALSE POSITIVE on %r" % t)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 harness/3ceasuri-import/tests/test_olx_find.py`
Expected: FAIL with `AttributeError: 'NoneType' object has no attribute 'group'` — the regexes do not exist yet.

- [ ] **Step 3: Add the rules**

In both `olx-find-*.py`, after the existing `ACCESSORY` regex:

```python
# Activation lock: the watch is unusable to a buyer, so it is not stock we can list.
# Matched narrowly on purpose — "icloud deconectat" and "cont sters" are the honest
# opposite claim and must NOT fire, which is why the lock words need a lock CONTEXT.
ACTIVATION_LOCK = re.compile(
    r"\bblocat\s+(?:pe\s+)?(?:icloud|cont|id)\b|"
    r"\bcont\s+(?:apple|icloud|google|mi)\b[^.\n]{0,40}\bnu\s+(?:stiu|am|cunosc)\b|"
    r"\bnu\s+stiu\s+parola\b|\bactivation\s+lock\b|\bicloud\s+lock\b", re.I)

# Explicit shop stock: an ad offering many identical units is inventory, not a watch.
# "ultima bucata" and "1 bucata" are single-item ads and must NOT fire.
EXPLICIT_STOCK = re.compile(
    r"\bpeste\s+\d+\s+(?:buc|bucati|bucăți)\b|"
    r"\b\d{2,}\s+(?:buc|bucati|bucăți)\s+(?:disponibil|pe\s+stoc)|"
    r"\blichidar[ei]\s+de\s+stoc", re.I)
```

and in `consider()`, immediately after the `ACCESSORY` check:

```python
    if ACTIVATION_LOCK.search(text):
        drop("activation_locked", ad, snip); return
    if EXPLICIT_STOCK.search(text):
        drop("explicit_stock", ad, snip); return
```

- [ ] **Step 4: Run the tests**

Run: `python3 harness/3ceasuri-import/tests/test_olx_find.py`
Expected: `ALL CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add harness/3ceasuri-import/scripts/olx-find-watches.py harness/3ceasuri-import/scripts/olx-find-smartwatches.py harness/3ceasuri-import/tests/test_olx_find.py
git commit -m "harness: drop activation-locked and explicit-stock ads in discovery

The only two triage rules §6 decision 2 allows to become hard drops -- both are
wording a regex gets right every time. Each ships with false-positive assertions
against real listing shapes that were legitimately imported ('icloud deconectat',
'ultima bucata'). Stock photos, inflated generation claims and the multi-price
run-on ads stay flags, not drops."
```

---

## Task 9: Session prompts and the permission allowlist

Lever I. This is what makes an unattended run actually unattended.

**Files:**
- Create: `OLX_IMPORT_SESSION_PROMPT.md`
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Write the allowlist**

Replace `.claude/settings.local.json` with:

```json
{
  "permissions": {
    "allow": [
      "Bash(export BU_CDP_URL=*)",
      "Bash(browser-use:*)",
      "Bash(python3 harness/3ceasuri-import/scripts/candidates.py:*)",
      "Bash(python3 harness/3ceasuri-import/scripts/olx-log-result.py:*)",
      "Bash(python3 harness/3ceasuri-import/tests/:*)",
      "Bash(curl -s http://127.0.0.1:9222/json/version)",
      "Bash(cat harness/3ceasuri-import/.contracts/:*)",
      "Read(harness/3ceasuri-import/.photos/**)",
      "Edit(harness/3ceasuri-import/.contracts/**)",
      "WebFetch(domain:bogdanripa.substack.com)"
    ]
  }
}
```

- [ ] **Step 2: Verify the allowlist parses**

Run: `python3 -c "import json;d=json.load(open('.claude/settings.local.json'));print(len(d['permissions']['allow']),'rules')"`
Expected: `10 rules`.

- [ ] **Step 3: Write the session prompt**

Create `OLX_IMPORT_SESSION_PROMPT.md` with a setup+discovery prompt and a continuous-loop prompt. The loop prompt must state the four rules from the plan's Global Constraints 7–9 plus the `REVIEW:` action table, and must instruct the model to drive the queue with `candidates.py next` rather than from memory. Include the exact commands:

```
export PATH="$HOME/.local/bin:$PATH"; export BU_CDP_URL="http://127.0.0.1:9222"
CAND=harness/3ceasuri-import/.candidates-olx-smart.json

ID=$(python3 harness/3ceasuri-import/scripts/candidates.py next $CAND) || echo QUEUE_EMPTY
AD_ID=$ID CANDIDATES_FILE=$CAND browser-use < harness/3ceasuri-import/scripts/olx-import-smartwatch.py
# read EXTRACT_PROMPT.draft, read ONE photo, edit the draft's _todo fields
AD_ID=$ID CANDIDATES_FILE=$CAND CONFIRM=1 browser-use < harness/3ceasuri-import/scripts/olx-import-smartwatch.py
# then: pipe the RESULT:/SKIP: line to olx-log-result.py
```

- [ ] **Step 4: Commit**

```bash
git add OLX_IMPORT_SESSION_PROMPT.md .claude/settings.local.json
git commit -m "docs: OLX session prompts and a Bash allowlist for unattended runs

The allowlist was empty, so a continuous session stalled on a permission prompt
for every browser-use call. The prompt file is the OLX counterpart of the archived
Facebook one, written for the continuous loop chosen in §6 decision 7."
```

---

## Task 10: Rewrite the skills as imperative cores

Lever H. Do this last: the skills document the behaviour, so the behaviour must be final first.

**Files:**
- Modify: all seven `.claude/skills/*/SKILL.md`
- Create: `harness/3ceasuri-import/references/olx-lore.md`

- [ ] **Step 1: Move the rationale out**

Create `harness/3ceasuri-import/references/olx-lore.md` and move into it every dated anecdote currently inside the skills — the 2026-08-11 Amanet boilerplate finding, the 2026-08-09 phone-reveal measurement, the 2026-08-12 price-floor cases, the 2026-08-20 repost-dedup correction. Keep every fact; add a one-line index at the top. Nothing is deleted, only relocated off the execution path.

- [ ] **Step 2: Rewrite each SKILL.md as steps**

Each becomes ≤150 lines: numbered imperative steps, literal copy-pasteable commands, and decision tables instead of paragraphs. `olx-import-watch` and `olx-import-smartwatch` must carry the `REVIEW:` action table:

| `action` | What to do |
|---|---|
| `fix` | Supply the field named in `field` in the draft, re-run pass 2. Once. |
| `skip` | `candidates.py` is already marked; log the `code` via `olx-log-result.py` and take the next id. |

Each skill ends with one line pointing at `references/olx-lore.md` for the why.

- [ ] **Step 3: Verify the size drop**

Run: `wc -w .claude/skills/*/SKILL.md | tail -1`
Expected: under 3,000 words total (from 5,890).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/ harness/3ceasuri-import/references/olx-lore.md
git commit -m "skills: imperative cores, rationale moved to references/olx-lore.md

~5,900 words of lore-dense prose was hostile as an instruction set for a small
model, which either over-weights an anecdote or skips the imperative buried next
to it. Every fact is kept -- the dated findings move to olx-lore.md, read only
when troubleshooting, and each SKILL.md becomes numbered steps plus decision
tables."
```

---

## Task 11: The replay eval

Lever K. Measures whether any of this worked, and is also step 1 of the standalone-agent design's §7 eval — build it so both use it.

**Files:**
- Create: `harness/3ceasuri-import/eval/replay.py`

**Interfaces:**
- Consumes: `history.jsonl` (935 OLX imports, 288 skips), `olx_api`, `contract_draft`, `price_sanity`.
- Produces: `python3 harness/3ceasuri-import/eval/replay.py --limit 50` printing per-field agreement, the would-be skip rate by review code, and the count of ads no longer fetchable.

- [ ] **Step 1: Snapshot the dataset**

The ads must be re-fetched from a browser tab on olx.ro (Global Constraint 6) and cached to `harness/3ceasuri-import/eval/.snapshots/<id>.json`, because many historical ads are gone. Run it as a browser-use payload once; everything after that is offline.

- [ ] **Step 2: Report the numbers that matter**

Report, per §6's "unknown skip rate" note:
- **the would-be skip rate broken down by review code** — this is the number the decisions in §6 left unknown, and the reason this task exists;
- per-field agreement against the saved record for `brand`, `model` (normalised), `movement`, `price`, `connectivity`, `compatibility`;
- how many labels have a `model` that does not appear in the ad text (those were identified from photos, and must not count as text-path errors).

- [ ] **Step 3: Commit**

```bash
git add harness/3ceasuri-import/eval/
git commit -m "eval: offline replay of historical OLX ads

Reports the would-be skip rate by review code -- the number §6 left unknown when
it made REVIEW: non-overridable -- plus per-field agreement against what was
actually saved. Also step 1 of the standalone-agent design's §7 eval."
```

---

## Notes for the executor

**Run the whole suite after every task**, not just the task's own test:

```bash
for t in harness/3ceasuri-import/tests/test_*.py; do echo "== $t"; python3 "$t" || exit 1; done
```

All five must print `ALL CHECKS PASSED`. The archived Facebook suites (`archive/facebook/tests/`) must also keep passing — they share `admin_import.py`, `infer_fields.py` and `price_sanity.py`, so a change to any of those can break them.

**Tasks 1–8 are the deliverable.** 9 makes it runnable unattended, 10 makes it readable by a small model, 11 tells you whether it worked. Stop after 8 and you still have a working, better harness; stop after 10 and you have the Haiku target; 11 is what justifies trusting it for a long run.

**Task 11 could be its own plan.** It is a separate tool with a separate consumer (the standalone-agent design), and nothing in Tasks 1–10 depends on it. Split it out if this plan is being executed by subagents and you want the review boundary.

**Do not implement the standalone Docker/local-LLM agent here.** That is `docs/superpowers/specs/2026-09-15-standalone-olx-agent-design.md`, not started, and it has eight open questions of its own.
