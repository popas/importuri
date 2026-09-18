# OLX import — session prompts

Paste ONE of these into a fresh session. Prompt A runs once; prompt B is the
continuous loop and runs until the queue is empty or the target is hit.

The OLX counterpart of the archived `archive/facebook/IMPORT_SESSION_PROMPT.md`,
written for the single continuous session chosen in §6 decision 7 of
`docs/superpowers/specs/2026-09-18-olx-determinism-handover.md`.

---

## Prompt A — setup and discovery (once per session)

```
Run an OLX import session for 3ceasuri.ro.

Invoke the `olx-session-setup` skill and follow it. Then invoke exactly ONE of
`olx-find-smartwatches` (category 1943) or `olx-find-watches` (category 1677) —
ask me which if I have not said.

Report the STATS: line and how many candidates are pending, then stop. Do not
import anything yet.
```

---

## Prompt B — the import loop (paste once; it runs to the end)

```
Import OLX watches until the queue is empty or you have imported <N>.

Set up once:

  export PATH="$HOME/.local/bin:$PATH"; export BU_CDP_URL="http://127.0.0.1:9222"
  CAND=harness/3ceasuri-import/.candidates-olx-smart.json   # or -watches.json
  SCRIPT=harness/3ceasuri-import/scripts/olx-import-smartwatch.py   # or -watch.py

Then repeat this loop. Never invent a step; never write JS by hand.

  1. ID=$(python3 harness/3ceasuri-import/scripts/candidates.py next $CAND)
     If it prints QUEUE_EMPTY, stop and report.

  2. AD_ID=$ID CANDIDATES_FILE=$CAND browser-use < $SCRIPT

  3. Read EXTRACT_PROMPT.draft — that is a JSON file with the WHOLE contract
     already filled in. Read ONE photo from EXTRACT_PROMPT.photos. Edit only the
     fields named in EXTRACT_PROMPT.todo, in place, and save.

  4. AD_ID=$ID CANDIDATES_FILE=$CAND CONFIRM=1 browser-use < $SCRIPT

  5. Pipe that command's output to the logger:
     ... | python3 harness/3ceasuri-import/scripts/olx-log-result.py

  6. Next id.

RULES — these are not negotiable:

- A field you blank in the draft is CLEARED, not defaulted. The draft removes the
  retyping, not the clearing. Leave alone anything not in `todo`.
- You NEVER override a REVIEW: gate. Each reason carries `action`:

  | action | what you do |
  |--------|-------------|
  | `fix`  | supply the field named in `field` in the draft, re-run step 4. ONCE. |
  | `skip` | the candidate is already marked; log it and take the next id. |

  If a `fix` does not clear the gate on the second run, treat it as a skip.
- CONFIRM=1 is not a skeleton key. It is in step 4 because the draft is the
  answer; it does not let you past a gate you did not satisfy.
- Never import a suspiciously cheap listing. If the script says
  `suspiciously cheap`, that is final — it is a fake, not a bargain.
- "Is this imported?" is answered by the 3ceasuri.ro admin, never by a local file.
- Never re-run a step because of an "Inspected target navigated or closed"
  exception. That is the SUCCESS path; re-running double-imports.
- You may skip a candidate on your own judgement (a photo set that cannot be
  attributed to one watch, an obvious miscategorisation) — log the reason.
- On NEW_BRAND: add the brand to BOTH `window.BRAND_IDS` in
  `scripts/import-watch.js` and `references/brand-ids.md`, then commit.
- If something fails, invoke `olx-troubleshooting`. Do not improvise.

Report at the end: imported, skipped (by reason code), and what is still pending.
```

---

## Checking on a run

```bash
python3 harness/3ceasuri-import/scripts/candidates.py counts harness/3ceasuri-import/.candidates-olx-smart.json
```

`{"pending": 12, "imported": 6, "skipped": 2, "error": 0}` — the queue is the
progress report, so a session can be stopped and resumed at any point.
