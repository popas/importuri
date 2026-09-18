# Reusable prompts — run the watch-import workflow

## Before you paste (one-time per session)

1. Quit Chrome fully (⌘Q), then relaunch with the debug port:
   `open -a "Google Chrome" --args --remote-debugging-port=9222`
2. Make sure you're logged into Facebook **and** the 3ceasuri.ro admin in that Chrome.
3. Open two tabs: the FB buy/sell group and `https://3ceasuri.ro/admin/`.
4. `browser-use` must be installed (`uv tool install browser-use`).

There are **two** prompts now. Paste A once, then paste B once per watch, doing `/clear`
in between. The split is what keeps each watch cheap: nothing from watch N is needed for
watch N+1, and `/clear` is a command only you can issue — the agent cannot clear itself.

If you'd rather not bother, pasting B repeatedly without `/clear` still works correctly;
it just costs more as the context grows.

---

## Prompt A — setup + discovery (paste once)

```
Run the 3ceasuri watch-import workflow, discovery phase only. Follow
Watch_Listing_Automation_Plan.md and invoke skills with the Skill tool — do NOT
improvise or write your own browser code instead of running the scripts.

Environment (my Mac, local Chrome — already running):
- CDP host is 127.0.0.1:9222 (Chrome launched with --remote-debugging-port=9222).
- browser-use is CLI 3.0. Run browser commands in bash like this:
  export PATH="$HOME/.local/bin:$PATH"; export BU_CDP_URL="http://127.0.0.1:9222"
- Reuse the Facebook and admin tabs that are already open. Do not open a fresh
  Chrome profile.

TARGET: 5 watches this session. Do not ask me for the target — it is 5.

1. watch-session-setup — connect browser-use, confirm the two tabs, read session state.
2. fb-find-posts — run find-posts.py ONCE (MAX_CANDIDATES=8). Do not hand-scroll the
   feed and do not run the script twice: re-running it costs a feed navigation and
   deepens FB throttling.
3. Triage the CANDIDATES: snippets it returns and tell me which ids you'd import and
   which you're dropping as bulk lots / non-watches / missing brand or model. Report
   STATS.admin_total as the real site count.

Then STOP. Do not import anything yet — I'll clear the context and paste the per-watch
prompt.
```

---

## Prompt B — import one watch (paste after each `/clear`)

```
Continue the 3ceasuri watch-import workflow: import the NEXT unimported candidate from
harness/3ceasuri-import/.candidates.json. Do not re-run discovery.

Environment: export PATH="$HOME/.local/bin:$PATH"; export BU_CDP_URL="http://127.0.0.1:9222"

1. admin-import-watch — POST_ID=<id> browser-use < harness/3ceasuri-import/scripts/import-post.py
   One call does dedup, extraction, inference, import, banner verification and readback.
   Do NOT run a DRY_RUN pass first.
   - On REVIEW: — read the reasons, fix them with OVERRIDES, re-run with CONFIRM=1.
     Judge the inference yourself: gold PLATING is not a gold case; leave a field unset
     rather than guessing an enum the post text doesn't support.
   - On NEW_BRAND: — add it to BOTH window.BRAND_IDS in import-watch.js AND
     references/brand-ids.md, then commit.
   - On SKIP: — record why and move to the next candidate.
2. import-verify-state — confirm by PAGE CONTENT (both green banners) or a successful
   readback, never by the return value. Append the outcome to history.jsonl and bump the
   session counters in state.json.
3. Report the watch briefly (brand, model, price, images saved) and tell me how many
   candidates remain. Then stop — I'll /clear and paste this again.
```

(end of prompts)

---

## Hard rules (unchanged — the scripts enforce most of them)

- One watch at a time. Never pre-collect images for multiple watches (FB image URLs expire).
  Batching post ids and dedup lookups is fine — that's what discovery does.
- Never modify image URLs (the signed `_nc_ohc` / `oh` / `oe` params are required).
- Re-inject the harness after every page navigation or form submit.
- Always fill description, sourceUrl, and fbListingId.
- **Never quote an import count from a local file.** The admin is ground truth; `state.json`
  is session bookkeeping and `history.jsonl` is a local log of activity.
- If the feed stalls or keeps returning the same posts, back off per watch-troubleshooting
  (pause, one gentle re-read, then stop) — do NOT hammer refresh or open new tabs.

## Model note

Discovery and extraction are now scripted, so the model's remaining job is judgment:
triaging candidate snippets, and handling `REVIEW:` (new brands, weak inference, plating
vs solid gold). Sonnet remains the safe floor for that. Haiku can drive the mechanical
steps but is likelier to mishandle exactly those judgment calls; if you use Haiku, watch
the first watch closely before trusting a full run.
