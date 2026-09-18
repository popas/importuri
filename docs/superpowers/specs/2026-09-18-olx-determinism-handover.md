# Handover prompt — make the OLX harness deterministic enough for Haiku

**Date:** 2026-09-18 · **For:** a fresh Claude Code (Opus) session in
`/Users/stelian/.hermes/proiecte/3ceasuri` · **Status:** analysis done, nothing implemented.

Paste everything from "## THE PROMPT" down into the new session. Sections 1–6 below it are
the analysis that prompt refers to — the new session reads them from this file.

---

## THE PROMPT

```
You are picking up the 3ceasuri OLX import harness. Read CLAUDE.md first, then
docs/superpowers/specs/2026-09-18-olx-determinism-handover.md (this file) in full,
then OLX_Listing_Automation_Plan.md.

GOAL: make the OLX → 3ceasuri.ro import path deterministic enough that a Haiku-class
model can run a full 20-watch session end to end without a Sonnet/Opus babysitting it.
Today the scripts are deterministic and the SKILLS are not: the model still triages
snippets by prose judgement, retypes a 25-field contract (including the whole seller
description) into a single-quoted shell variable, decides on its own what a REVIEW:
line means, and hand-runs verification JS that the importer already ran. Every one of
those is a small-model failure mode. Section 3 lists them with file:line.

SCOPE: the OLX path only (categories 1677 and 1943). Do not touch the Facebook
scripts or skills. Do not build the Docker/local-LLM agent — that is a separate,
already-approved design in docs/superpowers/specs/2026-09-15-standalone-olx-agent-design.md.
This work is the step before it and must stay compatible with it: put every new rule
in the Python modules under harness/3ceasuri-import/scripts/ (portable), never in
skill prose (not portable).

HOW TO WORK:
- Start with superpowers:brainstorming with the user on section 5 ("The levers") before
  writing any code. Sections 5B, 5D and 5G change import semantics and are the user's
  call, not yours. Section 6 lists the questions to ask.
- Then superpowers:writing-plans, then execute.
- TDD: harness/3ceasuri-import/tests/ runs offline with stubbed browser-use
  (python3 tests/test_olx_import.py, test_olx_find.py — all 4 suites pass today).
  Every new deterministic rule gets a test there BEFORE it gets an implementation.
  That suite is the only reason this refactor is safe to do at all.
- Commit straight to main, no branches, no PRs (main is what Coolify deploys).
- The Django backend is a SEPARATE repo at ~/projects/anunturi/ceasuri. Prefer changes
  that need no backend deploy; if one is unavoidable, say so and stop for the user.

DEFINITION OF DONE: a Haiku session, given one pasted prompt per watch (the OLX
counterpart of archive/facebook/IMPORT_SESSION_PROMPT.md, which does not exist yet), can import a watch
with: no free-form JS, no hand-built shell JSON, no judgement call that is not a
written decision table, and no step whose correctness depends on remembering something
from before the last /clear. Measure it — do not assert it. Run one real Haiku session
against live OLX and report where it deviated.

HARD INVARIANTS — do not "simplify" these away:
1. Never import a suspiciously cheap listing. price_sanity.py is the single source of
   floors; CONFIRM=1 does not wave one through. (User directive 2026-08-09.)
2. Ground truth for "is this imported / how many" is the 3ceasuri.ro admin, never a
   local file.
3. movement must never silently default to quartz. An ad that states no movement stops
   for review.
4. Route by kind, not by category (a smartwatch in 1677 goes to the smartwatch importer).
5. Verify by page content / readback, never by a return value. Never retry on the
   "Inspected target navigated or closed" exception — that is the success path, and a
   retry double-imports.
6. Read OLX only from a page already on www.olx.ro (a plain GET is 403).
7. Whatever replaces the current contract semantics, it must stay impossible for a
   field to be half-authoritative — today "a field you omit is CLEARED" buys that, and
   any replacement has to buy it some other way (see 5B).
```

---

## 1. What the OLX path is today

A browser-automation runbook. Per watch, a `browser-use` payload script does the whole
flow in one cold process, printing marker lines (`EXTRACT:`, `EXTRACT_PROMPT:`, `INFER:`,
`REVIEW:`, `SKIP:`, `NEW_BRAND:`, `RESULT:`, `ERROR:`). The model in the loop reads those
lines, fills an extraction contract, and re-runs the same script with `CONFIRM=1
OVERRIDES='{…}'`.

```
olx-session-setup ─ once ─┐
olx-find-{watches,smartwatches}.py ─ once ─→ .candidates-olx-*.json
                          └─ per watch (fresh context each):
   pass 1  AD_ID=… browser-use < olx-import-*.py     → EXTRACT_PROMPT + photos, writes nothing
   MODEL   reads prompt + ≥1 photo, fills the contract
   pass 2  AD_ID=… CONFIRM=1 OVERRIDES='{…}' …       → validate → dedup → import → verify
   import-verify-state → history.jsonl + state.json → /clear
```

Volume so far: `history.jsonl` holds 995 imports and 332 skips (935/288 of them OLX).
Sessions run ~20 classic + ~20 smart watches. The offline test suite (4 files) passes.

## 2. What is already deterministic — leave it alone

These are the good parts and the reason the goal is reachable at all:

- `olx_api.map_params()` — seller dropdown params → DB enums (condition, caseMat,
  braceletMat, displayType, gender, style, waterRes, price/currency/negotiable).
  Deliberately conservative: an unknown value stays null rather than guessing.
- `olx_api._split_location()` / `admin_import.COUNTY_SPELLING` — județ/localitate,
  including the "Bucuresti - Ilfov" split (202 of ~560 ads sampled).
- `price_sanity.py` — brand floors, family floors, new/sealed floors, model→brand
  implication, homage/mod exemption, misspelling normalisation. Hard skip.
- `admin_import.already_imported()` (stage 1) and `find_repost()` (stage 2, seller
  match = strong, model-only = weak/REVIEW).
- `admin_import.ensure_brand()` — look before creating, search by NAME not slug.
- `admin_import.verify()` — banners **and** readback of the saved record, with the
  pre/post-2026-08-09 field-name fallback.
- `infer_fields.validate()` — rejects illegal enums before the admin form silently
  drops them.
- Discovery filters in `olx-find-*.py` — inactive, no price, below floor, replica
  wording, accessories, bulk/stock, blocklist, already-imported.

## 3. Where the non-determinism actually is

Ordered by how badly it hurts a Haiku run.

**3.1 The contract answer travels through a single-quoted shell variable.**
`OVERRIDES='{…}'` (`olx-import-watch.py:16`, and every skill). Romanian ad text
routinely contains apostrophes ("anii '70", "Cœur d'Or"), which terminate the quoting
and produce a shell error the model then "fixes" creatively. There is no
`OVERRIDES_FILE`. Confirmed: `grep -n OVERRIDES *.py` — env var only.

**3.2 Omission deletes data, and the model must retype the whole description.**
`olx-import-watch.py:184-189`: any `SCHEMA_FIELDS` key absent from `OVERRIDES` is
popped from the baseline. `description` is in `SCHEMA_FIELDS` but is deliberately
excluded from the "Known from OLX" block (`:160`, `k != "description"`), so the model
has to copy the entire cleaned seller description out of the prompt's ad-text section
and back into the JSON, verbatim, every time. That is the single largest transcription
surface in the loop and it is on the critical path of a shell argument. Same trap for
`phone`: it is in `SCHEMA_FIELDS`, so omitting it clears it, and `:216` then pays a
second page navigation (+~25 s) to re-reveal it.

**3.3 Candidate triage is unbounded prose judgement.**
`olx-find-watches/SKILL.md` and `olx-find-smartwatches/SKILL.md` hand the model ~8
snippets and a bulleted essay: spot amanet relists, "bulk in disguise", run-on ads with
several prices and no currency word, activation lock ("iCloud", "nu stiu parola"),
stock photos and renders, inflated generation claims. No output format, no decision
table, no threshold. Several of these are regex-able and are not regexed.

**3.4 `REVIEW:` has no decision table, and `CONFIRM=1` is a skeleton key.**
The review gate (`olx-import-watch.py:230-249`) raises 8 different reasons — new brand,
model/price/movement not inferred, wall clock without case material, <2 images, thin
description, mis-routing to the wrong importer. `CONFIRM=1` passes *all* of them plus
the `is_wristwatch`/`is_bulk_lot` skip gates at once. A small model that learns
"REVIEW → add CONFIRM=1" will bulldoze a mis-routed smartwatch and a bulk lot with the
same reflex it uses for a legitimately-thin description.

**3.5 `import-verify-state` is Facebook-shaped and redundant for OLX.**
It tells the model to hand-run three JS snippets for banners, change-link and readback.
The OLX importers already ran exactly that inside `admin_import.verify()` and returned
`banners`, `readback`, `readback_ok` on the `RESULT:` line (`olx-import-watch.py:299-302`).
A literal reader does the work twice, on whatever tab it happens to be on. What is
actually left for OLX is: append `RESULT.state_entry` to `history.jsonl` and bump
`state.json` — two mechanical writes, currently expressed as a hand-assembled
`python3 -c` one-liner.

**3.6 Doc/code drift that breaks a literal reader.**
`.claude/skills/olx-import-smartwatch/SKILL.md:62` says "`series`, `connectivity` and
`compatibility` are required". `series` is **not** a contract field —
`infer_fields.validate({"series": …})` returns `['series is not a field in the
contract']`, which is a hard `ERROR` exit in pass 2. A model that follows the skill
literally fails the import. (The code checks only `connectivity`/`compatibility`.)
Audit the rest of the skills the same way.

**3.7 The candidate file is not a work queue.**
`.candidates-olx-*.json` has no per-candidate status. "Take the next unimported id"
depends on the model remembering across a `/clear`, which is exactly what `/clear`
destroys. The checked-in `.candidates-olx-smart.json` is dated 2026-08-09 while sessions
ran to 2026-09-13 — stale, with nothing marking it so.

**3.8 Two importers, 95 % identical.**
`diff olx-import-watch.py olx-import-smartwatch.py` is ~60 lines of real difference out
of ~300. Every rule change has to be made twice, and drift between them is a silent
correctness bug.

**3.9 Prose volume and lore density.**
~5,900 words across the six OLX skills, much of it dated rationale ("seen 2026-08-11…",
"measured 2026-08-09…"). Valuable as rationale, hostile as an instruction set for a
small model, which will either over-weight an anecdote or skip the imperative buried
next to it.

**3.10 Operational friction.**
`.claude/settings.local.json` has an empty allowlist, so an unattended run stalls on
permission prompts for every `browser-use` call. There is no OLX counterpart of
`archive/facebook/IMPORT_SESSION_PROMPT.md`. Session target and source are asked
interactively.
The scripts are `browser-use` payloads piped on stdin — a model that "corrects" this to
`python3 olx-import-watch.py` gets a confusing `NameError` on the CDP helpers.

## 4. What genuinely needs a model (do not try to automate these away)

- `model` — the ad usually does not name it; the dial does. This is vision work, and
  Haiku 4.5 has vision. Keep it, but make it the *only* open-ended question per watch.
- `movement` for a classic watch, when the ad does not state it.
- `reference` — read from a caseback/papers photo, never derived from design.
- Judging a photo set that cannot be attributed to one watch (the 2026-09-13 two-Huawei
  ad), and obvious miscategorisation (the Hisense projector filed as a smartwatch).

Everything else in sections 3.1–3.10 is transport, bookkeeping or a rule that has not
been written down yet.

## 5. The levers (brainstorm these with the user before building)

**A. Move the answer off the command line.** Add `OVERRIDES_FILE=<path>` to both
importers, preferred over `OVERRIDES`. Kills a whole class of failure with ~5 lines.
Cheap, safe, no semantic change — probably do this first regardless of the rest.

**B. Stop making the model retype what the script already knows.** Two candidate shapes;
the user picks, because this changes import semantics:
- *Seeded draft (recommended).* Pass 1 writes a complete pre-filled contract to
  `.contracts/olx-<id>.json` — every mapped param, the cleaned description, the phone,
  with the genuinely-open fields as `null` and a `"_todo"` list naming them. The model
  edits that file in place and pass 2 reads it. Clearing semantics survive untouched
  (the file *is* the whole contract), the transcription surface goes to zero, and the
  model's job shrinks to ~6 fields.
- *Merge + explicit clear.* Omission merges from the baseline; deliberate erasure needs
  `"clear": ["field", …]`. Simpler to implement, but it reintroduces exactly the
  two-half-authoritative-sources problem `infer_fields.py`'s docstring was written to
  kill. Recommend against unless the user wants it.

**C. Turn triage into code plus a fixed checklist.** Move to `olx-find-*.py` /
discovery flags everything regex-able: activation-lock wording, "peste N bucati"
stock language, multi-price run-ons with the currency word omitted, plural-title
stock ads, obvious non-watch categories. What remains goes in a numbered checklist with
a fixed output shape (`KEEP <id> / DROP <id> <reason-code>`), not prose.

**D. Replace `CONFIRM=1` with per-gate acknowledgement.** e.g.
`ACK=thin_description,new_brand` — the model must name the gate it is overriding, and
naming a gate it did not see is an error. Keep `price_sanity` unoverridable. Then give
each gate a one-line prescribed action in the skill: fix / skip with reason code /
acknowledge. A table, not a paragraph.

**E. Collapse the two importers into one** (`PROFILE=classic|smart`), keeping the two
filenames as three-line wrappers so the skills and muscle memory still work.

**F. Make bookkeeping a script.** `olx-log-result.py` (or a `--log` flag) that takes the
`RESULT:` JSON, appends to `history.jsonl` with `event`/`ts`, and bumps `state.json`.
Rewrite `import-verify-state` so the OLX branch is: "the importer already verified;
read `RESULT.ok`/`readback_ok`; run the log command; done."

**G. Make the candidate file a work queue.** Per-candidate `status` (`pending` /
`imported` / `skipped` / `error`) plus `reason` and `ts`, written by the importer
itself. Add a `next-candidate` command that prints the next pending id. Then "which
watch is next" is a command, not a memory.

**H. Split each skill into an executable core and a rationale appendix.** SKILL.md
becomes ≤150 lines of imperative steps with literal, copy-pasteable commands and
decision tables; the lore moves to `harness/3ceasuri-import/references/olx-*.md`, read
only when troubleshooting. Keep every fact — just move it off the execution path.

**I. Ship the session prompts.** Write `OLX_IMPORT_SESSION_PROMPT.md` (setup+discovery,
then one per-watch prompt), and add a `.claude/settings.local.json` allowlist for the
`browser-use`, `python3` and admin commands the loop actually uses.

**J. Extend the offline tests** to cover every new rule — especially B's seeded draft
round-trip and D's per-gate acks. Tests run with no browser and no network; they are
the safety net for all of the above.

**K. Measure, do not assert.** Replay the last ~50 OLX ads from `history.jsonl` through
the new deterministic path and diff against what was actually saved; then run one live
Haiku session and log every deviation. The replay harness is also step 1 of the
standalone-agent eval in the other design doc — build it so both use it.

## 6. Questions for the user (ask before planning)

1. **B: seeded draft or merge-with-explicit-clear?** This is the one decision that
   changes what "the contract is authoritative" means.
2. **How much triage judgement may become a hard drop?** Every regex added to discovery
   trades a missed good listing against an unattended run. Where is the line?
3. **Is a Haiku session allowed to add a brand** (edit `import-watch.js` +
   `references/brand-ids.md` + commit) mid-loop, or should `NEW_BRAND:` become a stop
   that queues for the user?
4. **Should a Haiku session be allowed to blocklist a seller**, or is that the user's
   call only? (The standalone-agent design says human-only; today Claude does it.)
5. **Does the Haiku run still get `/clear` between watches** (i.e. a human pasting a
   prompt per watch), or is the target one continuous session? That decides how much of
   G is mandatory.
6. **Does this supersede or feed the standalone-agent design?** Assumed: it feeds it —
   every rule lands in the Python modules that `contract.py` / `checks.py` / `store.py`
   will be ported from. Confirm.
