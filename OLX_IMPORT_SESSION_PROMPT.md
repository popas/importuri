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

  cd ~/projects/anunturi/importuri
  S="python3 harness/3ceasuri-import/scripts/olx-step.py"; Q=harness/3ceasuri-import/<queue file>
  $S start $Q --target <N>        # once

Per watch:
  1. $S next $Q
     SKIPPED / ERROR  -> nothing to do, run `next` again.
     A sheet (AD ... DECIDE ... NEXT) -> step 2.
  2. Read the ONE photo the sheet names (Read tool). A second only for a caseback.
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
    Never 'Alt brand', never 'Swiss' — those are OLX labels, not makers.
  - model: the name on the dial or box. None -> the defining trait, short
    ('Tachymetre 100M Automatic', "Precision anii '40").
  - movement: from the ad or dial; or inferred from a model you KNOW (a fashion or
    alarm chronograph is quartz; a 1960s Swiss Incabloc without 'automatic' is
    hand-wound) — then say so in notes. Unknown -> leave it null, the gate skips it.
  - year: one integer, only when stated. "între 1960 și 1970" -> year=null and the
    decade goes in model.
  - notes: one sentence when the model or movement was inferred; otherwise null.

The script, not you, refuses: suspiciously cheap listings, sellers whose account is
under 30 days old asking >= 1000 RON, one-photo ads, thin descriptions, repeats.
Never argue with a SKIPPED.
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
