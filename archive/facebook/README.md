# Facebook import path — ARCHIVED 2026-09-19

The Facebook source is no longer part of the live runbook. It was archived so that an
OLX session pays no context for it: the five FB skills used to sit in `.claude/skills/`,
where their descriptions load into every session whether or not you import from Facebook.

Nothing here is broken — it is parked. The code still runs; only the read-path changed.

## What moved where

| Was | Now |
|---|---|
| `Watch_Listing_Automation_Plan.md` | `archive/facebook/Watch_Listing_Automation_Plan.md` |
| `IMPORT_SESSION_PROMPT.md` | `archive/facebook/IMPORT_SESSION_PROMPT.md` |
| `.claude/skills/{watch-session-setup,fb-find-posts,fb-extract-post,admin-import-watch,watch-troubleshooting}/` | `archive/facebook/skills/…` |
| `harness/3ceasuri-import/scripts/{find-posts,import-post}.py` | `archive/facebook/scripts/` |
| `harness/3ceasuri-import/references/{feed-dom,post-extraction}.md` | `archive/facebook/references/` |
| `harness/3ceasuri-import/tests/test_{find_posts,import_post}.py` | `archive/facebook/tests/` |
| FB session logs, carousel/post-id lore | `archive/facebook/references/` |

## What did NOT move — it is shared with OLX

`harness/3ceasuri-import/scripts/{admin_import,infer_fields,price_sanity}.py`,
`scripts/import-watch.js`, `references/{brand-ids.md,seller-blocklist.json,django-backend.md}`.
The FB scripts still import them by their original paths, which is why they keep working
from here. `seller-blocklist.json` keeps both keys (`authors` = FB, `olx_sellers` = OLX).

The DB is source-agnostic since 2026-08-09 (`source` = `facebook`|`olx`,
`external_listing_id`, `seller_id`, `seller_name`), so archived FB rows stay valid and
`import-watch.js` still writes them correctly.

## Still works from here

```bash
python3 archive/facebook/tests/test_find_posts.py     # ALL CHECKS PASSED
python3 archive/facebook/tests/test_import_post.py    # ALL CHECKS PASSED
```

## To reactivate

1. `git mv archive/facebook/skills/* .claude/skills/` — that alone restores the
   Skill-tool entry points and the FB read-order.
2. Move `Watch_Listing_Automation_Plan.md` back to the repo root, and re-add the
   Facebook rows to the root `CLAUDE.md` router.
3. The scripts do **not** need moving — the skills here already invoke them at their
   archived paths, and their imports of the shared modules still resolve. If you do move
   them back, repoint both the skills and `SRC` in the two tests.
4. `import-verify-state` was rewritten OLX-only on 2026-09-19 (it now reads the
   `RESULT:` line the OLX importers emit instead of hand-running verification JS).
   The FB importer emits a compatible `RESULT:` with a `state_entry`, so §1 and §3 of
   that skill still apply; §2's fallback commands query by OLX ad id and would need a
   post id instead. Read it with that substitution, or restore the pre-2026-09-19
   version from git history:
   `git show 5d1e628:.claude/skills/import-verify-state/SKILL.md`

## Why it was archived rather than deleted

`docs/superpowers/specs/2026-09-15-standalone-olx-agent-design.md` decision **D3**:
OLX only; Facebook stays on the existing Claude Code runbook or is dropped. Archiving
keeps the runbook intact and recoverable while taking it off the always-on read-path.
`history.jsonl` still holds the 3 FB imports and 6 FB skips, tagged `"source":"facebook"`.
