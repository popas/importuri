# Per-ad agent — the instructions for ONE ad

The import loop runs one fresh subagent per ad (user directive 2026-11-07). The
orchestrating session never sees a sheet or a photo: it spawns an agent of type
`olx-per-ad` (`.claude/agents/olx-per-ad.md`, pinned to Sonnet) with the prompt

    QUEUE=<queue file>  TARGET=<N>

waits for its one-line answer, logs it, and spawns the next agent — strictly one at
a time (all agents share one Chrome, one OLX tab and one `state.json`).

Everything below is addressed to the agent.

---

You import ONE OLX watch ad into 3ceasuri.ro through the driver. Work from the repo
root. Do not read other repo files, do not load skills, do not run browser-use
yourself.

## Setup

    S="python3 harness/3ceasuri-import/scripts/olx-step.py"; Q=<QUEUE>
    $S start $Q --target <TARGET>     # resumes the running session
    $S next $Q

`next` output:
- `SKIPPED` / `ERROR` → run `$S next $Q` again (at most 6 times). Three `ERROR` in
  a row → answer `BLOCKED: <last error>`.
- `TARGET_REACHED` or `QUEUE_EMPTY` → answer that word.
- `CLEAR_CHECKPOINT` → run `$S start $Q --target <TARGET>` once, then `next` again.
- `PREFLIGHT_FAILED` / `BROWSER_FAILURE` → answer `BLOCKED: <line>`.
- A sheet (`AD … DECIDE … NEXT: … finish …`) → handle that ONE ad, then answer.

## The sheet

1. The full seller text is `description` in
   `harness/3ceasuri-import/.contracts/olx-<id>.json` when the sheet truncates it.
   Read the ONE photo the sheet names (Read tool) when the text does not settle the
   brand, model or dial colour, or the price/brand smells of a replica. A second
   photo only for a caseback.
2. Write the description to the `.description.txt` path the sheet names: the
   SELLER's text, lightly corrected (diacritics, typos, punctuation, ALL CAPS).
   Keep their sentences, order, person and facts (defects too); English stays
   English. Drop price, negotiation, shipping, delivery, contact, phone, shop
   address/hours/advertising, sign-offs, and every sentence about the ad, the seller
   or the photos ("vezi poze", "conform pozelor", "poze reale"). Add nothing but a
   missing brand/model. Never "vânzătorul …" / "fotografiile …".
3. Run the sheet's `finish` command with every MUST ANSWER field plus any field you
   can fill. `true/false/null` bare, text in single quotes.
   - `model`: the line; one of the sheet's MODELS when it is this watch's (exact
     spelling). A real line the site lacks → keep it and add `new_model=true`
     on the FIRST finish — a model not in MODELS without it is refused, and the
     one retry is often already spent on the description. A generic family
     ("G-Shock") is not a model: name the exact one or reuse a listed one.
   - `variant`: dial/edition/colour/nickname; never size, GPS/Cellular, condition.
   - Baume & Mercier (also "Baume et Mercier", "B&M") → always
     `brand='Baume & Mercier'` (site id 298); never create a new brand for it.
   - No maker mark → `brand='Fără marcă'`; never `Alt brand`. Check the brand the
     draft guessed against the text/photo — pass 1 sometimes picks a wrong one.
   - Enums: movement `automatic|manual|quartz|smart`; category `wrist|pocket`;
     gender `women|men|unisex|kids`; braceletMat
     `titanium|carbon|aluminium|steel|gold|silver|plastic|rubber|leather|nylon|other`;
     displayColor `black|white|silver|gold|other`. Smart: connectivity `gsm|no_gsm`;
     compatibility `ios|android|both` (Apple → ios; Galaxy Watch 4+ and Pixel →
     android; the rest → both).
4. `IMPORTED` → done. `FIX` → supply the named field (or rewrite the description)
   and run `finish` ONCE more, repeating every field of the first finish
   (model, `new_model=true`, …) — the retry is a full answer, not a patch. `NEW_BRAND … THEN: git …` → run that git command
   exactly (commit only; the orchestrator pushes).

Judgement skip instead of finishing:
`$S skip $Q <id> <code> 'reason'`, code `suspected_counterfeit | bulk_lot |
not_a_watch | mismatched_photos` — several watches for one price or shop stock
("am câte 3 buc", two boxes in the photo), not a watch (strap, microphone, clock,
service), photos of different watches, an obvious replica.

## Answer

ONE line: `IMPORTED <id> <brand> <model> <price> <cur>` | `SKIPPED <id> <code>` |
`TARGET_REACHED` | `QUEUE_EMPTY` | `BLOCKED: …`, followed by `; driver skipped:
<id> <reason>, …` when `next` skipped any. Add `; NEW_BRAND <name>` if one was made.
