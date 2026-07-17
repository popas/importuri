# Skills Refactor — Progress Log

Master prompt: `SKILLS_REFACTOR_PROMPT.md` (single source of truth).
Branch: `skills-refactor`. Update this file at the moment anything completes.

## Done

- Skill 1 `watch-session-setup` — drafted (Opus), reviewed (Fable: added P12 cross-ref for FB tab-new notifications), committed.
- Skill 2 `fb-find-posts` — drafted (Opus), reviewed (Fable: clean; JS byte-identical, max-3 scroll respected), committed.
- Skill 3 `fb-extract-post` — drafted (Opus), reviewed (Fable: clean; A→B→C order, JS + field table byte-identical), committed.
- Skill 4 `admin-import-watch` — drafted (Opus), reviewed (Fable: compressed quality-gate triplication; ~136 body lines, overage accepted — see Deferred), committed.
- Skill 5 `import-verify-state` — drafted (Opus), reviewed (Fable: clean; banner JS + state schema byte-identical, 60 body lines), committed.
- Skill 6 `watch-troubleshooting` — drafted (Opus), reviewed (Fable: fixed retry-table row that pointed at the tombstoned 3ceasuri-import skill), committed.
- Phase 2 cutover complete: Saint Honoré:34 added to harness BRAND_IDS; `skills/3ceasuri/` deleted (grep: no functional refs); orchestrator rewritten (≤60 lines, no JS); both old SKILL.md replaced with tombstones; CLAUDE.md rewritten (new architecture/read-order, path-discrepancy + Saint Honoré notes removed); state.json reset (history kept, target=null, status=idle).
- Phase 0 orientation: read CLAUDE.md, plan, both SKILL.md, brand-ids.md, harness header. Confirmed: harness BRAND_IDS missing Saint Honoré (line 4, ends at Oris:33); `skills/3ceasuri/` symlink dir exists; state.json has stale target=7/status=complete.

## In progress

- (nothing — Phases 0-4 complete)

## Phase 4 live validation (2026-07-17, Mac env, browser-use 3.0)

Ran a real session with the new skills; 1 watch imported end-to-end (Luch Export Ultra-thin 2209, 100 EUR, 4/4 images, new brand Luch:35 created via the new-brand procedure). Skill defects found and FIXED:

1. `watch-session-setup`: browser-use CLI ≥3.0 changed interface — `BU_CDP_URL` env var with the **HTTP** endpoint (ws:// rejected) + Python-heredoc helpers (`list_tabs()`, `js()`, …) instead of `--cdp-url`/subcommands. Skill updated to document 3.0 as current with the old CLI kept as a container-era note; also added install hint and "reuse existing tabs" guidance.
2. `import-verify-state`: the admin renders the success banner in Romanian ("a fost adăugat cu succes"), so the banner-check JS's `added_ok: t.includes('added successfully')` was a false negative on a successful import. JS now accepts either language.
3. Not a defect but noted: the carousel JS in `fb-extract-post` uses `await` inside a snippet — with browser-use 3.0's synchronous `js()`, run the loop from Python (collect → click Next → sleep 3s), reusing the skill's selectors verbatim. Covered by the new wording in `watch-session-setup`.

## Next

1. Optional Phase 4 live validation (import 1 watch end-to-end via new skills) — only if the user confirms the browser env is up.
2. Branch `skills-refactor` left for user review — not merged, not pushed.

Phase 3 verification results (all pass):
- Grep for stale terms: hits only in prompt, this log, and the decision-5-mandated `/opt/data` note in watch-session-setup.
- `Saint Honoré` in harness: exactly 1 hit.
- Line counts: orchestrator 45; skills 92/120/124/139/60/120 total lines (admin-import-watch overage logged in Deferred). All 6 have valid frontmatter.
- JS spot-check: carousel loop, brand injection, feed regex, harness wrapper, payload-push snippet each appear in exactly one new skill.
- `skills/3ceasuri/` gone.
- All 36 pitfalls ticked (each in exactly one skill — see table).
- Paper simulation written below — no missing information found.

## Decisions (locked — copied from SKILLS_REFACTOR_PROMPT.md, do not re-litigate)

1. Scroll contradiction → HTML/regex extraction PRIMARY; limited scrolling (max ~3) fallback; main↔buy/sell navigation refreshes feed. Delete "Golden Rule: Scroll, Don't Search" and "Scroll aggressively". Keep "never use group search" as user preference.
2. browser-use CLI IS the tool for FB tab management/eval. Delete stale "`browser-use` CLI: Unnecessary" bullet in browser-use SKILL.md.
3. Individual post pages NOT primary. Order: commerce listing → feed HTML regex → individual post page (last resort, 8-10s wait, expect notifications).
4. Duplicate check: admin `?q=POST_ID` first, brand+model fallback. Separate tab, never add-watch tab.
5. Paths → `$PROJECT_ROOT` placeholder (`/Users/stelian/.hermes/proiecte/3ceasuri` here; `/opt/data/proiecte/3ceasuri` old container). CDP host → `$CDP_HOST` (default `192.168.65.254:9222`, verify via `curl -s http://$CDP_HOST/json/version`). Both defined ONLY in setup skill.
6. Harness is v5. Remove every "v3" mention.
7. Add `"Saint Honoré":34` to `window.BRAND_IDS` in `skills/3ceasuri-import/scripts/import-watch.js` (only harness edit allowed).
8. Delete `skills/3ceasuri/` symlink dir after grep confirms nothing references it.
9. `skill_view(...)` doesn't exist — skills invoked via the Skill tool.
10. New skills → `.claude/skills/<name>/SKILL.md`. Heavy assets (harness, brand-ids.md) stay under `skills/3ceasuri-import/`, pointed to, never inlined.

## Pitfall checklist (each must land in exactly ONE new skill; tick in Phase 3)

Sources: plan "Known Pitfalls" (both lists, 16 unique) + retry table; browser-use SKILL Pitfalls + "What DOESN'T Work"; 3ceasuri-import SKILL Pitfalls. Deduped:

| # | Pitfall | Target skill | Done |
|---|---------|--------------|------|
| P1 | UTF-8 codec crash on FB (browser_navigate/snapshot); window.location.replace() workaround; resolves after leaving FB | troubleshooting | ✅ |
| P2 | FB feed scrolling doesn't load more posts; main↔buy/sell navigation refreshes feed | fb-find-posts | ✅ |
| P3 | Individual post pages slow (8-10s), show notifications instead of content | fb-extract-post | ✅ |
| P4 | Harness lost on every page navigation/submit — re-inject | admin-import-watch | ✅ |
| P5 | Never strip signed params (_nc_ohc, oh, oe) → "Bad URL hash" | fb-extract-post | ✅ |
| P6 | CDP timeout on image-heavy import usually = success; re-check page | import-verify-state | ✅ |
| P7 | importWatch returns success:false even on success — verify by page content | import-verify-state | ✅ |
| P8 | Brand Select2: direct <option> injection only; never browser_type/click | admin-import-watch | ✅ |
| P9 | browser_type unreliable for ALL fields (types into wrong element) — use .value + change event | admin-import-watch | ✅ |
| P10 | Admin DB outages (OperationalError, aivencloud host) — wait 30s, retry | troubleshooting | ✅ |
| P11 | FB CDN URLs expire — extract and import in same session | fb-extract-post | ✅ |
| P12 | `browser-use tab new` on FB shows notifications — navigate existing tab via window.location.href | troubleshooting | ✅ |
| P13 | Commerce listing pages often don't load in new tabs — eval on already-loaded tab or feed HTML | troubleshooting | ✅ |
| P14 | WS closes after window.location.href navigation — reconnect, short-lived connections per call | troubleshooting | ✅ |
| P15 | Description: pass RAW text — harness formatDescription/buildProfessionalDescription handles cleanup | admin-import-watch | ✅ |
| P16 | Phone numbers: extract via regex, strip spaces/dots | fb-extract-post | ✅ |
| P17 | FB proxy iframe (fbsbx.com maw_proxy_page) on buy/sell — cross-origin, DOM invisible; use main group URL or commerce pages | fb-find-posts | ✅ |
| P18 | document.title blocked for signed URLs — read img.src directly | fb-extract-post | ✅ |
| P19 | Commerce thumbnails all in DOM at once — single querySelectorAll, no clicking through | fb-extract-post | ✅ |
| P20 | browser_console expression size limit (~3KB; full harness too big for one call) → manual field filling fallback | troubleshooting | ✅ |
| P21 | New brand not in BRAND_IDS → create brand, note ID, sync harness + brand-ids.md | admin-import-watch | ✅ |
| P22 | browser-use needs browser-level WS URL (page-level → 404); "already running" → browser-use close | watch-session-setup | ✅ |
| P23 | Image injection one at a time if UTF-8 errors in browser_console expressions | troubleshooting | ✅ |
| P24 | Always fill description/sourceUrl/fbListingId — otherwise listing incomplete | admin-import-watch | ✅ |
| P25 | Image fetch failures (CORS/timeout/expired) — import proceeds with partial images, never skip watch solely for images | import-verify-state | ✅ |
| P26 | Virtualized feed removes off-screen posts (set=pcb links vanish) — collect before scrolling past | fb-find-posts | ✅ |
| P27 | Never use group search (/search/?q=) — user preference, scroll/extract feed instead | fb-find-posts | ✅ |
| P28 | Verify images_payload length (>500 real; ~200 with QmFkIFVSTCBoYXNo = all failed) | admin-import-watch | ✅ |
| P29 | Images/payload lost on form re-render — re-inject | admin-import-watch | ✅ |
| P30 | Currency values "RON"/"EUR" (value attr), not display text | admin-import-watch | ✅ |
| P31 | Feed text scope: [role="feed"], not document.body; dialogs: [role="dialog"] | fb-find-posts | ✅ |
| P32 | Timestamp links don't open dialogs in CDP (hrefs still carry post IDs); author-name click goes to profile | fb-extract-post | ✅ |
| P33 | mbasic.facebook.com redirects — unusable for plain-HTML scraping | troubleshooting | ✅ |
| P34 | set=gm. carousel gets stuck; set=pcb. carousel works; ArrowRight key doesn't work — click div[aria-label="Next photo"] | fb-extract-post | ✅ |
| P35 | Retry table (FB page load fail, skeletons, 0 images, injection fail, import fail max 2 retries) | troubleshooting | ✅ |
| P36 | images_payload entries must be {"data_url": "..."} objects, not plain strings | troubleshooting (manual-injection fallback) | ✅ |

## Paper simulation (Phase 3) — importing one watch using ONLY the new orchestrator + skills

1. Read `Watch_Listing_Automation_Plan.md` → says invoke `watch-session-setup`.
2. `watch-session-setup`: define $PROJECT_ROOT/$CDP_HOST; `curl $CDP_HOST/json/version` → browser WS URL; `browser-use close` if stale; connect; tab 0 = admin add form, tab 1 = FB buy/sell; load state.json (6 imported, 1 skipped); ask user for target. ✔ all commands present in skill.
3. `fb-find-posts`: FB tab active → run feed-HTML extraction JS → get texts + ids (`listing:...` or pcb/gm) → apply qualifying filter (≥500 RON, brand+model, no replica) → pick post ID. If nothing: ≤3 scrolls with DOM-reading JS, then main↔buy/sell refresh. ✔
4. Duplicate check per `admin-import-watch` Step 1: `browser-use tab new "https://3ceasuri.ro/admin/watches/watch/?q=POST_ID"` in separate tab → "0 watchs" → proceed. ✔
5. `fb-extract-post`: Method A commerce page → image-collection JS (complete URLs) + text; else Method B feed text + pcb carousel JS; else Method C post page (8-10s, last resort). Field table gives every regex (diameter, year, phone, reference). ✔
6. `admin-import-watch` Steps 2-3: re-inject harness (Python wrapper reading $PROJECT_ROOT/skills/3ceasuri-import/scripts/import-watch.js, expect "OK") → `importWatch({...})` with raw fields, raw description, complete image URLs, sourceUrl, fbListingId → quality gates. ✔
7. `import-verify-state`: wait 5s → banner-check JS → both `imagini salvate` + `added successfully` → update state.json (imported entry + total_imported), loop to step 3. ✔
8. Failure at any point → `watch-troubleshooting` (retry table covers each failure encountered in steps 2-7). ✔

No step required information missing from the skills; no fixes needed.

## Deferred

- Legacy deep-reference docs under `skills/browser-use/references/` and `skills/3ceasuri-import/references/` still contain old copies of some JS (e.g. carousel loop in `photo-carousel-collection.md`) and old-env details. They are historical archives (labelled as such in CLAUDE.md), were out of the mandated cleanup scope (only the two SKILL.md files were tombstoned), and nothing links to them from the new skills. Delete them if you want a stricter no-duplication guarantee.
- SKILLS_REFACTOR_PROMPT.md Phase-3 grep line contradicted its own Locked Decision 5 (the `/opt/data` old-container mention it mandates in `watch-session-setup`). Fixed the prompt file per its "fix the file first" rule.
- `admin-import-watch` body is ~136 lines (target ~120): the mandated byte-identical blocks (importWatch example ~25, field-value table ~18, quality gates, brand JS ~9, harness wrapper ~6) alone exceed the budget. Accepted as-is rather than deleting required facts.
