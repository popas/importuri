---
name: fb-extract-post
description: Invoke only when import-post.py cannot handle a post by itself — extraction and field inference normally run inside that script, not by hand.
---

# fb-extract-post

**Extraction is not a separate phase any more.** `import-post.py` (see `admin-import-watch`)
opens the post, gates on `pcb.<ID>`, collects the carousel, infers every field, and imports —
in one call. Do not hand-extract a post the script can handle: doing so costs ~8 round-trips
and re-derives rules the script already encodes.

Invoke this skill only for the cases the script does not cover:

- ~~commerce listings~~ — no longer a fallback case: run `import-post.py` with
  `LISTING_ID=<id>` instead of `POST_ID=<id>`. It reads the listing page (all images are in
  the DOM at once, no carousel) and strips the page chrome before inference — that chrome
  once turned the seller's "Joined in 2011" into the watch's year.
- **The script emitted `ERROR:`** — "never surfaced its pcb photo set", "carousel drifted",
  "collected 0 images". Diagnose with the same reference, then either fix the input or
  fall back to filling the form by hand (`watch-troubleshooting`).
- **You disagree with its inference** — don't re-extract; pass `OVERRIDES` (below).

## Correcting inference without re-extracting

The script emits `INFER:` with everything it derived, and stops at `REVIEW:` when it is
unsure. Correct it by re-running the same post id with overrides — overrides always win:

```bash
POST_ID=<id> CONFIRM=1 OVERRIDES='{"model":"Bambino Automatic","caseMat":"steel"}' \
  browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py
```

Override keys are the `importWatch` field names: `brand model price currency condition movement
type diameter caseMat braceletMat displayMat waterRes year reference phone location seller
description priceNote videoUrl`. Video-first posts import normally now; pass `videoUrl` only to
correct a clip permalink the script could not read off the post.

**Judgement to apply when reviewing `INFER:` output** — the script is deliberately conservative,
so check these rather than assume:

- **Gold plating is not gold.** "placat cu aur", "gold plated", "AU20", "dublé" describe a
  coating over a steel case. The script already maps these to `caseMat: "steel"`; if you
  override, keep it steel and mention the plating in the description.
- **An empty field is honest; a wrong one misrepresents the watch.** `movement`,
  `braceletMat`, `displayMat` and `waterRes` have no default on purpose. Don't fill them in
  from a guess the post text doesn't support.
- **Model quality.** The script takes the brand's line minus the brand words. If that yields a
  fragment or swallowed the whole post, override with a clean descriptive model.

The full RO→enum table, defaults, and the extraction methods live in
`harness/3ceasuri-import/references/post-extraction.md` — the script mirrors it, so change
both together or neither.

## Rules that still bind you

- **Never modify image URLs.** Signed params (`_nc_ohc`, `oh`, `oe`) are required; use the
  exact `img.src`. They expire within hours — extract and import in the same session.
- **Always verify the photo set belongs to the post you think you're extracting.** Cross-post
  image contamination is silent and survives into the import.
- Pass the **raw** FB post text as `description` — the harness formats it.

## Next

`admin-import-watch` → `import-verify-state`.
