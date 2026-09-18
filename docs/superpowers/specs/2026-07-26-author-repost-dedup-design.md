# Author-based repost dedup — design

Date: 2026-07-26
Status: IMPLEMENTED (f580729) as `admin_import.find_repost()`. Superseded in part on
2026-08-20: a model-only match is now weak/REVIEW, not a strong auto-skip — see the
comment in `find_repost` for why. Kept as the rationale record.

## Problem

Duplicate detection today (`admin-import-watch` Step 1) keys only on
`facebook_listing_id` — the FB post id. It reliably catches *re-processing the exact
same post*, but it does **not** catch the same physical watch **reposted under a new
post id** (sellers bump/relist; FB assigns a fresh id). Post-id dedup sees the repost
as new and we import a second copy.

Seller identity alone cannot be the key: the same seller legitimately lists many
different watches (in `state.json`, author "Timofeevich Vasilovich" appears 4× with 4
genuinely different watches). Dedup on identity alone would wrongly reject real
listings.

## Chosen approach (A): admin-side, DB-backed author fields

Store the FB post **author** on each `Watch` row, and add a second, author-scoped
dedup stage that compares the candidate's watch fingerprint (brand + model, price as a
tiebreaker) against the author's already-imported watches. The live Django admin is the
source of truth (authoritative, cross-session, cross-machine).

Rejected alternatives:
- **B (local `state.json` fingerprint):** self-contained but drifts from the
  authoritative admin and only as complete as we backfill.
- **C (both):** unnecessary now; A alone is authoritative. Can layer B later as a cheap
  pre-check if round-trips become a concern.

## Scope

Two repos change:

1. **Django backend** — `/Users/stelian/projects/anunturi/ceasuri`
   (see `harness/3ceasuri-import/references/django-backend.md`).
2. **Harness runbook** — this repo (`~/.hermes/proiecte/3ceasuri`).

## 1. Django backend changes

### 1.1 Model (`watches/models.py`, `Watch`)

Add two fields near `facebook_listing_id`:

```python
facebook_author_id   = models.CharField(max_length=64, blank=True, db_index=True)
facebook_author_name = models.CharField(max_length=255, blank=True)
```

- `facebook_author_id` — the **dedup key**: the stable FB profile identifier from the
  post author's link (numeric profile id, or vanity username slug when that is what the
  link exposes). Indexed for `?q=` search.
- `facebook_author_name` — human-readable display name, for eyeballing in the admin and
  in skip-log messages. Not a dedup key (names change / collide).
- Both `blank=True`: legacy rows and posts where the author cannot be captured still
  save.

### 1.2 Migration

`0009_watch_facebook_author` (linear after `0008_watch_phone`). Additive, nullable/blank
— no data migration required.

### 1.3 Admin (`watches/admin.py`, `WatchAdmin`)

- `search_fields` += `"facebook_author_id"`, `"facebook_author_name"` so
  `?q=<author_id>` returns that author's watches. **This is the change that makes Stage
  2 possible.**
- `list_display` += `"facebook_author_name"` (visibility; optional but recommended).
- No `fieldsets` is defined, so both fields auto-render on the add/change form at DOM
  ids `id_facebook_author_id` / `id_facebook_author_name` — the harness sets them the
  same way it sets `id_facebook_listing_id`. No template changes.

## 2. Harness changes (this repo)

### 2.1 `harness/3ceasuri-import/scripts/import-watch.js`

- Accept `data.fbAuthorId` and `data.fbAuthorName`.
- `set('id_facebook_author_id', data.fbAuthorId)` and
  `set('id_facebook_author_name', data.fbAuthorName)` alongside the existing
  `id_facebook_listing_id` set (~line 229).
- Add `data.fbAuthorId && 'author'` to the `optionalFields` log line.

### 2.2 `.claude/skills/fb-extract-post/SKILL.md`

Capture the post author during extraction:
- `fbAuthorId` — parsed from the author's profile link in the post. Most reliable from
  the **feed HTML** (`fb-find-posts` capture) or the individual post permalink, where the
  author anchor is present; the commerce listing page (Method A) may not expose the group
  author. Exact selector / URL-parse to be pinned during implementation (FB DOM is
  volatile — treat as a small spike).
- `fbAuthorName` — the author anchor's display text.
- Both flow into the `importWatch({...})` payload.

### 2.3 `.claude/skills/admin-import-watch/SKILL.md` — Step 1 becomes two-stage

```
Stage 1 (unchanged): ?q=<POST_ID>
    hit ⇒ skip (exact: already imported)

Stage 2 (new):       ?q=<AUTHOR_ID>        # skip Stage 2 if no author id captured
    returns all watches by this author
    for each returned row:
        if brand matches AND normalized model matches
           (AND price within ~15% — tiebreaker, not required):
            ⇒ REPOST ⇒ hard-skip, log
              "skip: repost of <brand> <model> by <author_name> (id <existing_id>)"
    else (author has only different watches, or none):
        proceed to extraction + import
```

- **Match action: hard-skip** (consistent with Stage 1). Log the matched existing
  watch so a wrong skip is auditable in the session log / `state.json` `skipped`.
- **Fallback:** when `facebook_author_id` is absent (legacy / uncapturable author), run
  Stage 2 as `?q=<PHONE>` instead when a phone is available; otherwise Stage 2 is
  skipped and only Stage 1 applies (status quo for that post).
- Batch Stage-2 queries with the cached candidate IDs, same as the existing Stage-1
  batching note.

### 2.4 `harness/3ceasuri-import/scripts/import-post.py`

Thread `fbAuthorId` / `fbAuthorName` through extraction → `importWatch`, and apply the
same two-stage dedup gate before importing.

## 3. Model-normalization rule (Stage 2 matching)

To decide "same watch", normalize `model_name` before comparing: lowercase, collapse
whitespace, strip punctuation/diacritics. Brand match is exact (FK). Price within ~15%
is a soft confirmation only — a repost with a dropped price is still a repost, so price
must **not** be required for a match. Keep the rule small and readable; refine only if
false skips appear.

## 4. Non-goals / deferred

- **Backfill of the ~22 existing author-less rows.** With hard-skip + forward-only
  capture, Stage 2 protects watches imported from here on; older rows stay post-id-only.
  Acceptable. An optional one-time backfill (re-read author from each `source_url`) can
  be a separate task later.
- Local `state.json` fingerprint pre-check (approach B / C) — deferred.
- Fuzzy image-hash matching — out of scope.

## 5. Success criteria

1. A watch imported with an author populates `facebook_author_id` /
   `facebook_author_name` (verified via readback, like the existing
   `id_reference_number` check).
2. `?q=<author_id>` in the admin returns that author's watches.
3. Re-running the loop on a **reposted** watch (same author + brand + model, new post
   id) is hard-skipped at Stage 2, with a log line naming the existing record.
4. A **different** watch by the same author still imports (no false skip) — the
   Timofeevich case.
