# MASTER PROMPT — Refactor the Watch-Import Runbook into Small Skills

You are Claude Fable 5 running in Claude Code, in the repo `/Users/stelian/.hermes/proiecte/3ceasuri/`.
Execute this prompt top to bottom. This file is the single source of truth for the task.
If anything in the conversation contradicts this file, this file wins. If you discover this
file is wrong about the codebase, fix the file first, then continue.

## Goal (do not drift from this)

Replace the monolithic `Watch_Listing_Automation_Plan.md` with **small, single-purpose skills**
(the "many small skills, one orchestrator" pattern from
https://bogdanripa.substack.com/i/198939937/one-big-prompt-or-many-small-skills), so that a
future import session loads **only the skill for the phase it is in**, never the whole runbook.

Non-goals (explicitly out of scope — do not do these):
- Do NOT redesign the import harness (`import-watch.js`) beyond the one-line BRAND_IDS fix listed below.
- Do NOT import watches, except in the optional final validation phase.
- Do NOT invent new automation capabilities, new tools, or new phases the current runbook doesn't have.
- Do NOT rewrite technical facts (selectors, regexes, URLs, pitfalls) — only relocate, dedupe, and de-contradict them.

## Roles

- **Fable 5 (you) = brain and orchestrator.** You make every decision: skill boundaries,
  contradiction resolutions, final review of every file. You never rubber-stamp subagent output.
- **Opus = hands.** Delegate mechanical work via the Agent tool with `model: "opus"`:
  drafting a skill file from a content map you specify, deduplicating snippets, mechanical
  find/replace across files. Give each Opus agent a narrow, self-contained brief with exact
  source line ranges and the acceptance checklist for its file. Anything requiring judgment
  (resolving contradictions, deciding what is stale) stays with Fable.
- If the Agent tool or Opus is unavailable, do the work yourself — do not stall.

## Context-budget & pause protocol (anti context-rot)

- **Everything must be reconstructible from disk.** Record every decision and every completed
  step in `REFACTOR_PROGRESS.md` (created in Phase 0) **at the moment it happens**, not at the end.
  Assume the session can die at any point.
- When your context is roughly **300–400k tokens full** (or you notice summarization has occurred),
  finish the file you are on, update `REFACTOR_PROGRESS.md` (done / in-progress / next / open
  decisions), commit everything with message `refactor checkpoint: <phase>`, then STOP and tell
  the user: "Checkpoint saved. Start a new session with: *Read SKILLS_REFACTOR_PROMPT.md and
  REFACTOR_PROGRESS.md, then continue.*"
- **On resume:** read ONLY this file + `REFACTOR_PROGRESS.md` + the specific files the progress
  log names as in-progress. Do not re-read finished skills, do not re-audit, do not re-open
  decisions marked resolved. Trust the log.

## Phase 0 — Orientation (keep it under ~10 minutes of work)

1. Read: `CLAUDE.md`, `Watch_Listing_Automation_Plan.md`, both `SKILL.md` files,
   `skills/3ceasuri-import/references/brand-ids.md`. Skim `import-watch.js` headers only.
   Do NOT read the `references/*.md` session logs unless a specific step needs them.
2. Create `REFACTOR_PROGRESS.md` with sections: `## Done`, `## In progress`, `## Next`,
   `## Decisions`, `## Deferred`. Copy the Locked Decisions below into `## Decisions`.
3. `git checkout -b skills-refactor` and commit the progress file.

## Locked decisions (pre-audited 2026-07-17 — do not re-litigate; flag in `## Deferred` only if the code proves one wrong)

1. **Scroll contradiction** → HTML/regex extraction from the loaded feed is PRIMARY; limited
   scrolling (max ~3 attempts) is a fallback; navigating main-group ↔ buy/sell refreshes the feed.
   Delete "Golden Rule: Scroll, Don't Search" and "Scroll aggressively" wording. Keep "never use
   group search" as a user preference.
2. **browser-use CLI contradiction** → the CLI IS the tool for FB tab management/eval (per
   CLAUDE.md tool policy). Delete the "`browser-use` CLI: Unnecessary" bullet in
   `skills/browser-use/SKILL.md` ("What DOESN'T Work") — it is stale.
3. **Individual post pages** → NOT a primary extraction method. Order: commerce listing page →
   feed HTML regex → individual post page (last resort, 8-10s wait, expect notifications).
   Remove the "PRIMARY extraction method" claim.
4. **Duplicate check** → query admin `?q=POST_ID` first (exact match on facebook_listing_id),
   fall back to brand+model search if 0 results feel suspicious. In a separate tab, never the
   add-watch tab.
5. **Paths** → all skill content uses the placeholder `$PROJECT_ROOT` with one line defining it
   (`/Users/stelian/.hermes/proiecte/3ceasuri` here; `/opt/data/proiecte/3ceasuri` in the old
   container env). Same for CDP host: `$CDP_HOST` (default `192.168.65.254:9222`, verify with
   `curl -s http://$CDP_HOST/json/version` at setup). Define both ONLY in the setup skill.
6. **Harness version** → it is v5. Remove every "v3" mention.
7. **BRAND_IDS bug** → add `"Saint Honoré":34` to `window.BRAND_IDS` in
   `skills/3ceasuri-import/scripts/import-watch.js`. This is the only harness edit allowed.
8. **Legacy symlink** → delete `skills/3ceasuri/` (the symlink dir) after grepping that nothing
   else references it.
9. **`skill_view(...)`** → does not exist in Claude Code. Skills are invoked via the Skill tool.
10. **Skill location** → new skills live in `.claude/skills/<name>/SKILL.md` so Claude Code
    auto-lists them. Heavy assets stay where they are: the harness script and `brand-ids.md`
    remain under `skills/3ceasuri-import/` and are POINTED TO by skills, never inlined.

## Phase 1 — Target architecture (create these 6 skills, in this order)

Each skill: YAML frontmatter (`name`, `description` that says exactly when to invoke it),
then **≤ ~120 lines** of body. One purpose per skill. A skill may say "invoke X next" but must
never duplicate another skill's content — link/point instead. Every fact from the old files
lands in exactly ONE skill (or is deleted as stale per the decisions above).

| # | Skill | Single purpose | Main content sources |
|---|-------|----------------|----------------------|
| 1 | `watch-session-setup` | Env vars ($PROJECT_ROOT, $CDP_HOST), browser-use connect (browser-level WS URL), open admin + FB tabs, load `state.json`, decide target | Plan SETUP; import-skill "browser-use CLI — Connection & Usage" |
| 2 | `fb-find-posts` | Discover qualifying posts: HTML regex extraction, qualifying filters (≥500 RON / ≥100 EUR, no replica/bulk), post-ID sources (commerce > pcb > gm), feed-refresh trick | Plan PHASE 0; browser-use skill discovery sections |
| 3 | `fb-extract-post` | Extract fields + ALL image URLs from ONE post: Method A commerce page, Method B group post/carousel, never-modify-URL rule, field extraction table | Plan PHASE 2; browser-use carousel/photo sections; import-skill image collection |
| 4 | `admin-import-watch` | Duplicate check, harness re-injection, `importWatch({...})` call shape, brand direct-injection, quality-gate checklist, new-brand procedure (incl. BRAND_IDS + brand-ids.md sync rule) | Plan PHASES 1+3; import-skill harness/brand sections |
| 5 | `import-verify-state` | Two-green-banners check, CDP-timeout-means-recheck rule, partial-image handling, `state.json` update schema | Plan PHASE 4; import-skill verification bits |
| 6 | `watch-troubleshooting` | ONLY failure modes & fallbacks: UTF-8 crash, WS drops, harness size limit / manual field filling, raw CDP Python fallback, retry table, DB outages | Plan pitfalls/retry tables; both skills' pitfall sections — deduped, one entry per pitfall |

**Orchestrator:** rewrite `Watch_Listing_Automation_Plan.md` down to **≤ 60 lines**: the loop
(SETUP once → per watch: find → extract → import → verify → update state → repeat), which skill
to invoke at each step, the 5 iron rules (one watch at a time; never modify image URLs; verify by
page content; re-inject harness after navigation; always fill description/sourceUrl/fbListingId),
and nothing else. No JS snippets in the orchestrator.

**Per-skill workflow (repeat 6× — this is the drift guard):**
1. Fable writes a content map: which source file+line ranges feed this skill, what gets dropped as stale.
2. Dispatch ONE Opus agent to draft the skill file from that map.
3. Fable reviews the draft against: single purpose? ≤120 lines? no duplication with already-written skills? every locked decision respected? all technical facts (selectors/regex/URLs) byte-identical to source?
4. Fix, commit (`skill: <name>`), tick it in `REFACTOR_PROGRESS.md`, then move to the next skill.

Delegate at most 2 Opus drafts in parallel; review them one at a time.

## Phase 2 — Cutover & cleanup

1. Apply decision 7 (BRAND_IDS) and decision 8 (delete symlink dir).
2. Rewrite the orchestrator plan file as specified above.
3. Replace the two old `SKILL.md` files with 3-line tombstones pointing at the new skills
   (or delete them if nothing references them — grep first).
4. Update `CLAUDE.md`: new architecture map, new read-order (orchestrator + invoke skills
   per phase), remove the path-discrepancy workaround note (now solved by $PROJECT_ROOT),
   remove the Saint Honoré known-bug note (now fixed).
5. Reset `state.json`: keep `imported`/`skipped` history, set `"status": "idle"`, remove or
   null the stale `target` — the setup skill now asks the user for a target each run.

## Phase 3 — Verification (all must pass before you claim done)

- [ ] `grep -ri "scroll aggressively\|Golden Rule\|skill_view\|Harness v3\|/opt/data" --include="*.md" .` → only hits allowed: this prompt file, REFACTOR_PROGRESS.md, and the single `/opt/data` old-container mention in `watch-session-setup` that Locked Decision 5 itself mandates.
- [ ] `grep -rn "Saint Honoré" skills/3ceasuri-import/scripts/import-watch.js` → 1 hit.
- [ ] Every new SKILL.md ≤ ~120 lines; orchestrator ≤ 60 lines; each has valid frontmatter.
- [ ] No JS snippet appears in more than one file (spot-check: carousel collect(), brand injection, feed regex).
- [ ] Each pitfall from BOTH old pitfall lists appears exactly once somewhere (build a checklist in REFACTOR_PROGRESS.md and tick them off).
- [ ] `ls skills/3ceasuri` → gone.
- [ ] Simulate one session on paper: using ONLY the new orchestrator + skills, write the exact sequence of skill invocations for importing one watch into `REFACTOR_PROGRESS.md`. If any step needs information that no skill contains, fix that skill.
- [ ] Commit everything; leave the branch for the user to review (do not merge to main, do not push, unless the user says so).

## Phase 4 — OPTIONAL live validation (only if the user confirms the browser env is up)

Ask the user first. If yes: follow the NEW orchestrator + skills verbatim to import 1 watch
end-to-end. Any point where you had to improvise = a skill defect; fix the skill, note it in
`REFACTOR_PROGRESS.md`, commit.

## Final report to the user

Summarize: skills created, contradictions resolved (list them), files deleted, verification
results, and anything parked in `## Deferred`. Plain sentences, no jargon.
