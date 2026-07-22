# Reusable prompt — run the watch-import workflow

## Before you paste (one-time per session)

1. Quit Chrome fully (⌘Q), then relaunch with the debug port:
   `open -a "Google Chrome" --args --remote-debugging-port=9222`
2. Make sure you're logged into Facebook **and** the 3ceasuri.ro admin in that Chrome.
3. Open two tabs: the FB buy/sell group and `https://3ceasuri.ro/admin/`.
4. `browser-use` must be installed (`uv tool install browser-use`).

Then paste the prompt below. Change **TARGET** to how many watches you want this run.

---

## The prompt (copy from here)

```
Run the 3ceasuri watch-import workflow. Follow Watch_Listing_Automation_Plan.md and
invoke each skill with the Skill tool in the given order — do NOT improvise, skip a
skill, or write your own browser code instead of following the skill.

TARGET: import 5 new watches this session (stop earlier if the group has no more
qualifying posts). Do not ask me for the target — it is 5.

Environment (my Mac, local Chrome — already running):
- CDP host is 127.0.0.1:9222 (Chrome launched with --remote-debugging-port=9222).
- browser-use is CLI 3.0. Run every browser command in bash like this:
  export PATH="$HOME/.local/bin:$PATH"; export BU_CDP_URL="http://127.0.0.1:9222"
  then a python heredoc using the helpers: list_tabs(), switch_tab(target_id),
  goto_url(url), js(code), scroll(x,y), new_tab(url), close_tab(target_id),
  wait_for_load(), page_info(). js() is synchronous — for multi-step flows
  (carousels, scrolling) loop in Python with time.sleep between js() calls.
- Reuse the Facebook and admin tabs that are already open. Do not open a fresh
  Chrome profile.

Loop, ONE watch at a time, until TARGET is reached:
  1. watch-session-setup — connect browser-use, confirm the two tabs, load state.json.
  2. fb-find-posts — find the next qualifying post: price >= 100 RON or >= 20 EUR,
     real brand + model in the text, has images, NOT replica/AAA+, NOT bulk, NOT a
     Vinted/ad link. Read the loaded feed HTML first, but the real watches are
     usually further down — SCROLL to reach them (Facebook has infinite scroll).
     Scroll with js('window.scrollBy(0, 1400)'), NOT the scroll(x, y) helper (it
     pages the feed the wrong way and loads nothing). A sparse initial feed is not
     an empty group — confirm scrollHeight grows before concluding "exhausted".
  3. admin-import-watch Step 1 — duplicate check with ?q=POST_ID in a SEPARATE tab,
     BEFORE extracting. If it already exists, mark it skipped and go to the next post.
  4. fb-extract-post — all fields + ALL image URLs from that one post.
  5. admin-import-watch — re-inject the harness, then call importWatch({...}). If the
     brand is not in the mapping, follow the new-brand procedure and update BOTH the
     harness and brand-ids.md.
  6. import-verify-state — confirm the import by PAGE CONTENT (both green banners),
     never by the return value, then update state.json.
  7. Repeat.

Hard rules (from the orchestrator — obey exactly):
- One watch at a time. Never pre-collect images for multiple watches (FB image URLs
  expire).
- Never modify image URLs (the signed _nc_ohc / oh / oe params are required).
- Re-inject the harness after every page navigation or form submit.
- Always fill description, sourceUrl, and fbListingId.
- If the feed stalls, shows notifications, or keeps returning the same posts, back off
  per watch-troubleshooting (pause, one gentle re-read, then stop) — do NOT hammer
  refresh or open new tabs. But first rule out a broken scroll (is scrollHeight
  growing?) and spend any post IDs you cached earlier — a throttled feed still lets
  you open posts/<ID>/ directly.

Report each watch briefly as you finish it (brand, model, price, images saved). Stop
when TARGET is reached, the group is exhausted, or you hit something only I can fix —
and tell me which.
```

(end of prompt)

---

## Model note

Sonnet is the safe "simple" floor for this — it involves multi-step browser
orchestration, JS extraction, and judgment (qualifying posts, RO→EN field mapping,
new-brand handling). Haiku can drive the mechanical steps but is more likely to
mis-handle the judgment calls and the browser-use heredoc flow; if you use Haiku,
watch the first watch closely before trusting a full run.
