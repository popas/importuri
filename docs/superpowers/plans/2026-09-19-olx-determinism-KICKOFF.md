# Kickoff prompt — execute the OLX determinism plan

Paste the block below into a fresh Claude Code session in
`/Users/stelian/.hermes/proiecte/3ceasuri`. Nothing else is needed; the session
reads the rest from the repo.

Edit the one bracketed line to pick your execution style before pasting.

---

```
Execute the implementation plan at
docs/superpowers/plans/2026-09-19-olx-determinism.md.

Read these three, in this order, before doing anything:
  1. CLAUDE.md
  2. docs/superpowers/specs/2026-09-18-olx-determinism-handover.md  -- §3 is why each
     change exists, §6 is the decisions the user already made
  3. docs/superpowers/plans/2026-09-19-olx-determinism.md  -- the eleven tasks

EXECUTION STYLE: [subagent-driven -- use superpowers:subagent-driven-development,
a fresh subagent per task, review between tasks]
  (swap for: [inline -- use superpowers:executing-plans, batched with checkpoints])

GOAL: make the OLX import loop deterministic enough that a Haiku-class model runs a
full 20-watch session unattended. The scripts are already deterministic; the
judgement calls left in the skills are what this removes.

WHAT NOT TO DO:
- Do not re-litigate §6 of the spec. Those seven decisions were made by the user on
  2026-09-19 and are folded into §5. If you think one is wrong, say so and stop --
  do not quietly implement the other option.
- Do not touch anything under archive/facebook/. That source is parked on purpose.
  Its two test suites must keep passing, because it shares admin_import.py,
  infer_fields.py and price_sanity.py with the live path.
- Do not build the standalone Docker/local-LLM agent. That is a different, not-yet-
  started design at docs/superpowers/specs/2026-09-15-standalone-olx-agent-design.md.
- Do not restructure beyond the plan's File Structure section.

HARD INVARIANTS (the plan's Global Constraints -- never soften these):
1. Never import a suspiciously cheap listing. price_sanity.py is the single source
   of floors; CONFIRM=1 does not wave one through.
2. Ground truth for "is this imported" is the 3ceasuri.ro admin, never a local file.
3. movement must never silently default to quartz.
4. Route by kind, not by category.
5. Verify by page content / readback, never a return value. Never retry on the
   "Inspected target navigated or closed" exception -- that is the success path, and
   a retry double-imports.
6. Read OLX only from a page already on www.olx.ro.
7. A field the model blanks in the contract draft is still CLEARED. The draft removes
   retyping, not the clearing semantics.
8. The agent NEVER overrides a REVIEW: gate -- it applies the fix the gate names, or
   logs a skip with the gate's reason code.

ENVIRONMENT FACTS THAT TRIP PEOPLE UP:
- The numbered olx-*.py scripts are browser-use PAYLOADS: `AD_ID=… browser-use <
  script.py`, never `python3 script.py`. The two new CLIs the plan adds
  (candidates.py, olx-log-result.py) ARE run with python3 -- that is the point of them.
- Tests are plain scripts using a check(cond, msg) helper, run as
  `python3 harness/3ceasuri-import/tests/test_x.py`. Do NOT introduce pytest.
- Tasks 1-8 and 10 need NO browser and NO network -- the test stubs fake CDP. Only
  task 11 needs Chrome, once, to snapshot ads. So you can do almost all of this with
  nothing running.
- Commit straight to main. No branches, no PRs. The plan gives a commit message per
  task; use them.
- Python 3.9+, no third-party dependencies anywhere in the harness.

AFTER EVERY TASK, run the whole suite, not just that task's test:

  for t in harness/3ceasuri-import/tests/test_*.py; do echo "== $t"; python3 "$t" || exit 1; done
  for t in archive/facebook/tests/test_*.py;        do echo "== $t"; python3 "$t" || exit 1; done

Every one must print ALL CHECKS PASSED. If a pre-existing check fails after your
change, the change is wrong -- fix the change, never the test. If you believe a test
itself is wrong, stop and ask.

STOPPING POINTS -- report and pause at each, do not run straight through:
- after Task 1 (the collapse): it is a pure refactor and the riskiest single diff
- after Task 8: tasks 1-8 are the deliverable; the harness is already better here
- after Task 10: this is the Haiku target
Task 11 (the replay eval) is splittable -- confirm with me before starting it.

Start by reading the three documents, then tell me your plan for Task 1 before
writing any code.
```
