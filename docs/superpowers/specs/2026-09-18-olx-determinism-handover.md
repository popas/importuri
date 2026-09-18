# Handover prompt — make the OLX harness deterministic enough for Haiku

**Date:** 2026-09-18 · **For:** a fresh Claude Code (Opus) session in
`/Users/stelian/.hermes/proiecte/3ceasuri` · **Status:** analysis done; §6 decisions answered 2026-09-19; nothing implemented yet.
Next step: superpowers:writing-plans against §5.

Paste everything from "## THE PROMPT" down into the new session. Sections 1–6 below it are
the analysis that prompt refers to — the new session reads them from this file.

> **Updated 2026-09-19.** Commit `d772c3d` archived the Facebook source (`archive/facebook/`)
> and fixed two of the findings below outright — **3.5** (`import-verify-state` was
> Facebook-shaped and duplicated the importer's own verification) and **3.6** (the
> `series` field that does not exist). Both are marked RESOLVED in place rather than
> deleted, because the next session needs to know they were real. Everything else in §3
> still stands. Always-on context dropped 11,097 → 6,997 bytes, all of it now OLX.

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
- Section 6 is ANSWERED (2026-09-19) — do not re-litigate it. The decisions are folded
  into section 5, and 5B/5C/5D/5G are settled. Go straight to
  superpowers:writing-plans, then execute. Brainstorm only if you hit something
  section 6 did not cover.
- Four rules the decisions impose, which you must not soften:
  (a) the seeded draft file is the whole contract — a field the model blanks is still
      cleared;
  (b) the agent NEVER overrides a REVIEW: gate — it fixes what the gate named, or skips
      and logs the reason code;
  (c) the agent MAY add a brand, blocklist an OLX seller, and skip on its own judgement,
      each with a logged reason;
  (d) the run is ONE continuous session, so the candidates work queue is mandatory and
      per-watch context is the binding constraint.
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
`olx-import-watch.py:184-188`: any `SCHEMA_FIELDS` key absent from `OVERRIDES` is
popped from the baseline. `description` is in `SCHEMA_FIELDS` but is deliberately
excluded from the "Known from OLX" block (`:158-159`, `k != "description"`), so the model
has to copy the entire cleaned seller description out of the prompt's ad-text section
and back into the JSON, verbatim, every time. That is the single largest transcription
surface in the loop and it is on the critical path of a shell argument. Same trap for
`phone`: it is in `SCHEMA_FIELDS`, so omitting it clears it, and `:215` then pays a
second page navigation (+~25 s) to re-reveal it.

**3.3 Candidate triage is unbounded prose judgement.**
`olx-find-watches/SKILL.md` and `olx-find-smartwatches/SKILL.md` hand the model ~8
snippets and a bulleted essay: spot amanet relists, "bulk in disguise", run-on ads with
several prices and no currency word, activation lock ("iCloud", "nu stiu parola"),
stock photos and renders, inflated generation claims. No output format, no decision
table, no threshold. Several of these are regex-able and are not regexed.

**3.4 `REVIEW:` has no decision table, and `CONFIRM=1` is a skeleton key.**
The review gate (`olx-import-watch.py:229-248`) raises 8 different reasons — new brand,
model/price/movement not inferred, wall clock without case material, <2 images, thin
description, mis-routing to the wrong importer. `CONFIRM=1` passes *all* of them plus
the `is_wristwatch`/`is_bulk_lot` skip gates at once. A small model that learns
"REVIEW → add CONFIRM=1" will bulldoze a mis-routed smartwatch and a bulk lot with the
same reflex it uses for a legitimately-thin description.

**3.5 `import-verify-state` is Facebook-shaped and redundant for OLX.** — **RESOLVED
2026-09-19 (`d772c3d`)**: it now reads `RESULT:` first via a decision table and keeps the
manual JS only for when `RESULT:` is missing or `ok: false`. Described below as it was.
It tells the model to hand-run three JS snippets for banners, change-link and readback.
The OLX importers already ran exactly that inside `admin_import.verify()` and returned
`banners`, `readback`, `readback_ok` on the `RESULT:` line (`olx-import-watch.py:298-301`).
A literal reader does the work twice, on whatever tab it happens to be on. What is
actually left for OLX is: append `RESULT.state_entry` to `history.jsonl` and bump
`state.json` — two mechanical writes, currently expressed as a hand-assembled
`python3 -c` one-liner.

**3.6 Doc/code drift that breaks a literal reader.** — **RESOLVED 2026-09-19 (`d772c3d`)**
for the two instances found; the audit itself is still worth repeating.
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
`.claude/settings.local.json` still has an empty allowlist, so an unattended run stalls on
permission prompts for every `browser-use` call — **still open**. There is still no OLX
counterpart of `archive/facebook/IMPORT_SESSION_PROMPT.md` — **still open** (lever I).
Session target and source are still asked interactively.
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

## 5. The levers

**§6 was answered by the user on 2026-09-19** — the decisions are folded in below
and recorded in full in §6. B, C, D, G are now settled; the rest were never contested.

**A. Move the answer off the command line** — **subsumed by B.** The seeded draft file
*is* the transport, so a separate `OVERRIDES_FILE` is not needed. Keep the `OVERRIDES`
env var working for one-off human fixes; the agent path stops using it entirely.

**B. Seeded draft file — DECIDED.** Pass 1 writes a complete pre-filled contract to
`.contracts/olx-<id>.json`: every mapped param, the cleaned description, the phone, the
location — with the genuinely-open fields as `null` and a `"_todo"` array naming them.
The model edits that file in place; pass 2 reads it and needs no `OVERRIDES` env var.

Clearing semantics survive untouched, because **the file is the whole contract** — a
field the model blanks is still cleared, it just never has to retype the ones it isn't
deciding. The transcription surface goes to zero and the answer shrinks from ~25 fields
to the `_todo` list (typically `model`, `movement`, `reference`, `is_wristwatch`,
`is_bulk_lot`, `notes`; for smart, `connectivity` + `compatibility` instead of
`movement`).

Merge-with-explicit-clear was rejected: it reintroduces the two-half-authoritative-
sources problem `infer_fields.py`'s docstring was written to kill, and OLX's own params
are demonstrably unreliable (it offered "Swiss" for a Christophe Duchamp).

Implementation notes:
- `_todo` is computed by the script, not chosen by the model: a field is open when the
  deterministic baseline could not fill it.
- Validate on read that no key outside `SCHEMA_FIELDS` was introduced, and that every
  `_todo` entry is now non-null — an unanswered `_todo` is a `REVIEW:`, not a silent null.
- Strip `_todo` before merging into `data`.
- Because the draft carries the rules' answers already, **the `EXTRACT_PROMPT` can shrink
  to the rules for the `_todo` fields only**. That matters more than it looks: see the
  context note under G.

**C. Triage: near-zero-false-positive rules only — DECIDED.** New automatic DROPs are
limited to wording a regex gets right every time. Start with: activation lock
(`iCloud`, `cont Apple`, `nu stiu parola`, `blocat`), explicit stock language
(`peste N bucati`, `disponibile pe stoc`, `lichidari de stoc`), and obvious non-watch
categories. Everything else that today lives in skill prose becomes a **flag on the
candidate**, not a drop — and the model answers a numbered checklist with a fixed output
shape (`KEEP <id>` / `DROP <id> <reason-code>`), never prose.

Explicitly NOT auto-dropped, because the false-positive cost is real: stock photos and
renders, inflated generation claims, amanet relists, and the multi-price run-on ads (the
currency-word heuristic already misfires both ways — see the 2026-08-11 notes in the
discovery skills). Those stay flags.

Every new drop rule ships with a test in `tests/` asserting it does NOT fire on a named
historical listing that was legitimately imported.

**D. `REVIEW:` is never overridable by the agent — DECIDED, and simpler than planned.**
The per-gate acknowledgement scheme is dropped. The agent may not pass a review gate at
all, so `CONFIRM=1` stops being an agent-facing flag (it stays for a human re-run).

Because the run is a continuous loop (§6 Q5) and the agent *may* skip on its own
judgement (§6 Q3), the rule that keeps the loop moving without weakening a gate is:

> **`REVIEW:` → fix it if the fix is mechanical and named by the gate; otherwise log a
> skip with the gate's reason code and take the next candidate. Never override.**

"Mechanical and named" means the gate told the model exactly which field to supply and
the answer is already in hand — e.g. a missing `connectivity` the photos settle. A gate
that reflects genuine doubt (`movement not stated`, `possible repost`, `description
looks thin`) is a skip, logged, not a judgement call.

`price_sanity` remains a hard skip that nothing waives, as it already is.

**Cost to measure before trusting it:** this converts some importable watches into
skips, and nothing in `history.jsonl` records how often `REVIEW:` fired historically, so
the rate is currently unknown. Instrument it in the replay eval (K) and report the
would-be skip rate before running a long unattended session.

**E. Collapse the two importers into one** (`PROFILE=classic|smart`), keeping the two
filenames as three-line wrappers so the skills and muscle memory still work.

**F. Make bookkeeping a script.** `olx-log-result.py` (or a `--log` flag) that takes the
`RESULT:` JSON, appends to `history.jsonl` with `event`/`ts`, and bumps `state.json`.
Rewrite `import-verify-state` so the OLX branch is: "the importer already verified;
read `RESULT.ok`/`readback_ok`; run the log command; done."

**G. Candidate file as a work queue — MANDATORY, not optional.** §6 Q5 chose a single
continuous session, so nothing external tracks progress: per-candidate `status`
(`pending` / `imported` / `skipped` / `error`) plus `reason` and `ts`, written by the
importer itself, and a `next-candidate` command that prints the next pending id. "Which
watch is next" must be a command, not a memory.

**The continuous loop makes per-watch context the binding constraint.** Today's design
assumed `/clear` between watches; ~20 watches in one context will not fit if each pays
a ~2,500-word `EXTRACT_PROMPT` plus photo reads. Mitigations, in order of value:
- shrink `EXTRACT_PROMPT` to the `_todo` rules only (see B);
- read ONE photo per watch by default — already the rule, now load-bearing;
- have the importer print a one-line result per watch, not the full `INFER:` dump, once
  the readback confirms;
- treat a context checkpoint as a first-class stop: the work queue means a fresh session
  resumes exactly where the last one stopped, so a long run can be several sessions
  without human bookkeeping.

**H. Split each skill into an executable core and a rationale appendix.** SKILL.md
becomes ≤150 lines of imperative steps with literal, copy-pasteable commands and
decision tables; the lore moves to `harness/3ceasuri-import/references/olx-*.md`, read
only when troubleshooting. Keep every fact — just move it off the execution path.

**I. Ship the session prompts.** Write `OLX_IMPORT_SESSION_PROMPT.md` (setup+discovery,
then one per-watch prompt), and add a `.claude/settings.local.json` allowlist for the
`browser-use`, `python3` and admin commands the loop actually uses.

**J. Extend the offline tests** to cover every new rule — especially B's seeded-draft
round-trip (including an unanswered `_todo` → `REVIEW:`), C's new drop rules not firing
on known-good historical listings, and D's skip-instead-of-override path. Tests run with no browser and no network; they are
the safety net for all of the above.

**K. Measure, do not assert.** Replay the last ~50 OLX ads from `history.jsonl` through
the new deterministic path and diff against what was actually saved; then run one live
Haiku session and log every deviation. The replay harness is also step 1 of the
standalone-agent eval in the other design doc — build it so both use it.

## 6. Decisions (answered by the user, 2026-09-19)

| # | Question | Answer |
|---|---|---|
| 1 | Contract transport & semantics | **Seeded draft file.** Pass 1 pre-fills `.contracts/olx-<id>.json`, the model edits only `_todo` fields, pass 2 reads it. Omission-clears semantics are preserved because the file is the whole contract. Merge-with-explicit-clear rejected. |
| 2 | How much triage becomes a hard drop | **Near-zero-false-positive rules only.** Activation lock, explicit stock language, obvious non-watch categories. Everything else becomes a flag plus a fixed `KEEP`/`DROP <reason-code>` checklist. |
| 3 | May the agent add a brand? | **Yes.** On `NEW_BRAND:` it edits `import-watch.js` + `references/brand-ids.md` and commits, mid-loop. |
| 4 | May the agent blocklist a seller? | **Yes.** It may add an OLX seller to `references/seller-blocklist.json`. (This differs from the standalone-agent design's human-only stance — see the note below.) |
| 5 | May the agent override a `REVIEW:` gate? | **No.** Never. `REVIEW:` always stops the watch; `CONFIRM=1` becomes a human-only flag. |
| 6 | May the agent skip a candidate on its own judgement? | **Yes**, provided it logs the reason to `history.jsonl`. |
| 7 | Session shape | **One continuous session**, the agent loops through the candidates file until the target is hit. No `/clear` per watch. |

### What follows from 5 + 6 + 7 together

The three interact, and the resolution is the rule in lever D: **`REVIEW:` stops the
watch, and the agent then skips it and logs the gate's reason code rather than stalling
the loop.** Without this, a non-overridable gate inside a continuous unattended loop
would halt the run on the first thin description.

Two consequences to carry into the plan:

- **Unknown skip rate.** Nothing in `history.jsonl` records how often `REVIEW:` fired,
  so we cannot say today what share of importable watches this converts into skips.
  Instrument it in the replay eval (lever K) and report the number before a long run.
- **Context is now the binding constraint**, not shell quoting. See the note under
  lever G.

### Divergence from the standalone-agent design — deliberate

`2026-09-15-standalone-olx-agent-design.md` §10 Q7 proposes that only a human adds
blocklist entries. Decision 4 here says the Haiku session may. These are different
trust models for different things: a Claude Code session is supervised and its commits
are reviewable in git, an unattended container is not. **Do not "fix" one to match the
other** — when the standalone agent is built, blocklist growth reverts to human-only per
that design, and this decision applies only to the Claude Code runbook.

### Still unconfirmed

**Does this work feed the standalone-agent design, or supersede it?** Assumed
throughout: it **feeds** it — every rule lands in the Python modules under
`harness/3ceasuri-import/scripts/` that `contract.py` / `checks.py` / `store.py` will be
ported from, and lever K's replay harness is step 1 of that design's §7 eval. Nothing in
the plan depends on the answer, but say so explicitly before Phase 1 of the other design
starts, so the two do not get built twice.
