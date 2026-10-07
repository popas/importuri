# OLX import — session prompts

Paste ONE of these into a fresh session (`/clear` first). Prompt B is the import
loop; it is written for a cheap model at low effort (Sonnet, `/effort low`), because
`olx-step.py` does every step that used to need judgement about the harness and
prints the literal next command. Prompt A is discovery, only when no queue has
pending ids — it needs more judgement, so run it on the stronger model.

Queues on disk (2026-09-22) — `python3 harness/3ceasuri-import/scripts/olx-step.py counts <file>`:

| File | Profile | Region | Generated | Pending |
|---|---|---|---|---|
| `.candidates-olx-smart-bi.json` | smart | București + Ilfov | 09-20 | 6 |
| `.candidates-olx-smart.json` | smart | all | 09-19 | 218 |
| `.candidates-olx-watches.json` | classic | all | 09-19 | 179 |
| `.candidates-olx-watches-bi.json` | classic | București + Ilfov | 09-20 | 0 |

Old queues are fine: a gone ad skips itself as `not_active`, and an imported one as
`already_imported`.

---

## Prompt B — the import loop (paste once; it runs to the end)

```
Import OLX watches into 3ceasuri.ro. Target: <N> imports.
Queue: harness/3ceasuri-import/<queue file>

Work ONLY through the driver. Do not read the orchestrator, do not load skills, do
not explore the repo, do not run browser-use yourself. Every output ends with the
literal NEXT: command — run it. Only on PREFLIGHT_FAILED, BROWSER_FAILURE, or three
ERROR/NOT_SAVED in a row: stop and invoke the olx-troubleshooting skill.

  # run everything from the root of this repo
  S="python3 harness/3ceasuri-import/scripts/olx-step.py"; Q=harness/3ceasuri-import/<queue file>
  $S start $Q --target <N>        # once

Per watch:
  1. $S next $Q
     SKIPPED / ERROR  -> nothing to do, run `next` again.
     A sheet (AD ... DECIDE ... NEXT) -> step 2.
  2. Read the ONE photo the sheet names (Read tool). A second only for a caseback.
     Write the description (Write tool) to the .description.txt path the sheet's
     DESCRIPTION line names — the seller's text, lightly corrected, in their voice.
  3. $S finish $Q <id> 'field=value' ...
     - pass every field marked MUST ANSWER, plus any other field you change;
       an omitted field keeps the value shown. true/false/null bare, text in quotes.
     - IMPORTED -> next watch. Never run finish again for that id.
     - FIX      -> pass the field it names and run finish ONCE more. A second FIX
                   becomes a skip by itself.
     - SKIPPED  -> next watch.
     - NEW_BRAND ... THEN: git ... -> run that git command exactly.
  4. Stop at the target or QUEUE_EMPTY: run `$S stop $Q` and report its SESSION line.

Your own judgement skip (instead of filling the sheet):
  $S skip $Q <id> <code> 'short reason'
  codes: suspected_counterfeit | bulk_lot | not_a_watch | mismatched_photos
  Use it when the ad itself settles it: several watches for one price, an ad selling
  only a strap/charger/box, photos of two different watches, or a counterfeit.

Judging, in one place:
  - Counterfeit signs: a luxury brand at a fraction of its price; the classic replica
    designs (Rado Jubile "tungsten" two-tone, "Rolex" Submariner/Daytona, AP Royal
    Oak, Cartier Santos under a few thousand RON); a dial whose logo or text is off.
    The script already refuses what is below its price floors — you catch the rest.
  - A new watch still in its box or wrap IS a watch (is_wristwatch=true).
  - brand: the maker on the dial/caseback/box. No mark anywhere -> 'Fără marcă'.
    'Alt brand' is NEVER stored — unbranded is always 'Fără marcă'. OLX's 'Alt brand'
    and 'Swiss' are labels, not makers: find the real maker first.
  - model: the LINE on the dial or box, one of the sheet's MODELS when it is this
    watch's (exact spelling). None -> the defining trait, short ('Tachymetre 100M
    Automatic', 'Precision').
  - variant: what sets this watch apart from others of its model — dial, edition,
    nickname, strap ('Chronograph Panda', 'Pepsi', "anii '40"). Never size,
    GPS/Cellular, condition. Nothing -> null.
  - FIX unknown_model: the site has no such model for the brand. Pick one of the
    listed names as model (the rest goes in variant); only for a line the brand really
    makes, keep it and add 'new_model=true'.
  - movement: from the ad or dial; or inferred from a model you KNOW (a fashion or
    alarm chronograph is quartz; a 1960s Swiss Incabloc without 'automatic' is
    hand-wound) — then say so in notes. Unknown -> leave it null, the gate skips it.
  - year: one integer, only when stated. "între 1960 și 1970" -> year=null and the
    decade goes in variant.
  - notes: one sentence when the model or movement was inferred; otherwise null.
  - description: the SELLER's text, lightly corrected — it must read as if they wrote
    it and still look like the OLX ad. Keep their sentences, order, person and facts,
    defects included; fix only diacritics, typos, punctuation, ALL CAPS; drop price,
    negotiation, shipping, contact, sign-offs and copied filler. Add nothing but a
    brand/model they left out. Never write about the seller, the ad or the photos
    ("vânzătorul precizează", "fotografiile prezintă") — not even when they did.

The script, not you, refuses: suspiciously cheap listings, sellers whose account is
under 30 days old asking >= 1000 RON, one-photo ads, thin descriptions, repeats.
Never argue with a SKIPPED.
```

---

## Prompt C — gone listings (weekly; read-only until the endpoint exists)

```
Check which of 3ceasuri.ro's active OLX listings are gone from OLX. Do not load
skills or explore the repo. Chrome is on CDP 127.0.0.1:9222 with the admin signed in.
From the repo root, run in the background (a full sweep takes ~40 minutes):

  BU_CDP_URL=http://127.0.0.1:9222 browser-use < harness/3ceasuri-import/scripts/olx-check-active.py

Report the STATS: line and the REPORT: path. Only if I say so, re-run with APPLY=dry,
then APPLY=1. APPLY_UNAVAILABLE means the Django deactivate/ endpoint is not deployed
yet: report it and stop. A STATS "stopped" value means OLX blocked us: wait, never retry
in a loop.
```

---

## Prompt A — discovery (only when no queue has pending ids; stronger model)

```
Run OLX discovery for 3ceasuri.ro. Invoke `olx-session-setup`, then exactly ONE of
`olx-find-smartwatches` (category 1943) or `olx-find-watches` (category 1677) — ask
me which if I have not said. Report the STATS: line and the pending count, then stop.
Do not import anything.
```

---

## What the driver prints, for a reviewer

- `next` keeps the payload's raw output in `harness/3ceasuri-import/.runs/olx-<id>-pass1.log`
  and prints a ~2 KB sheet: the ad text, one photo path, each open field with its
  current value and a one-line rule, and the `finish` command.
- `finish` writes the answers into `.contracts/olx-<id>.json`, validates them BEFORE
  any browser call (`BAD_ANSWER:` runs nothing), runs pass 2 with `CONFIRM=1`, logs
  the outcome to `history.jsonl`/`state.json`, and — when the payload lost its
  `RESULT:` (a CDP timeout after the save) — asks the admin before declaring anything.
- Routing (`looks_smart`/`looks_classic`), resumes (a draft already on disk),
  fix-once, and the NEW_BRAND map edits are all inside the driver.
