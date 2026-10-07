# Handover (proposal): refuse a watch whose photos are already on the site

**For:** an agent working in the Django repo (`../app` next to this repo, GitHub `popas/ceasuri`).
**From:** the OLX import runbook (`../importuri`), 2026-10-07.
**Status:** IMPLEMENTED 2026-10-07, not yet deployed. Django: `Picture.content_sha256`
(migration `0027_picture_content_sha256`), `services.find_photo_repeat` /
`photo_repeat_groups`, `manage.py hash_pictures` / `photo_duplicates`, documented in
`docs/runbooks/2026-10-04-admin-import-api.md`. Runbook: § 3 done (`site_api.py`,
`olx_import.py`, `references/django-backend.md`), plus § 3b (shop cards). After the
deploy: run `manage.py hash_pictures` once on production, then `manage.py photo_duplicates`.

---

## 0. The problem, with numbers

The same watch comes back under a new ad id, and the photos are byte-identical files:

| When | What | Caught by |
|---|---|---|
| 2026-08-15 / 08-16 | Rolex Yacht-Master II 18k, 35 990 EUR, seller "Black Sea": OLX 300470478 and 299454774 | nothing — **both are live now** (pk 679 and 741), 7 identical photos |
| 2026-10-07 | Casio G-Shock, two seller accounts 50 min apart: 299247856 / 299246401 | the operator, by eye (5 identical photos) |
| 2026-10-07 | Apple Watch SE, same seller 3 min apart: 310205538 / 310205408 | the operator, by eye (4 identical photos) |

The importer's repost check matches seller + model, so it misses a second account and
anything whose model is not known yet. The runbook now hashes the photos it downloads
(`harness/3ceasuri-import/scripts/photo_dedup.py`) and skips a repeat in pass 1 — but
that only sees `.photos/` on the machine that ran the import. Imports from the other
machine, the Facebook era, and anything whose local photos were cleaned are invisible to
it. The site holds every picture; it is the only place this check can be complete.

## 1. What exists now

- `watches/models.py` → `Picture(watch, image, thumbnail, created_at)`; `save()` builds the thumbnail.
- `watches/admin_api.py` → `watch_import_json`: validates, then `_fetched_images(image_urls)`
  (the SERVER downloads from the OLX CDN, `remote_images.py`) or `_uploaded_images(files)`,
  then `save_pictures(watch, images)` inside `transaction.atomic()`.
- The server's bytes are not the runbook's bytes (different fetch, maybe a different size
  or WEBP), so hashes must be computed and compared **server-side**, on what is stored.

## 2. Proposal

1. **`Picture.content_sha256`** — `CharField(max_length=64, blank=True, db_index=True)`,
   set from the stored original's bytes when the picture is saved. One migration.
2. **`hash_pictures` management command** — fills the field for existing rows (reads each
   file from storage; idempotent; `--limit`). Run once after deploy.
3. **`import-json` refuses a repeat.** After the images are fetched and before the
   transaction: hash them; find ACTIVE watches with pictures sharing ≥ 2 of those hashes
   (or 1 when the new watch has a single photo), ignoring any hash found on ≥ 5 watches —
   those are pawn-shop banner cards (Zeus, NDP and TotalConvert put the same two logo
   images on every watch). On a hit answer **409**
   `{"error": "duplicate_photos", "duplicate_of": <pk>, "external_listing_id": "...", "shared": n}`
   and save nothing. `"allow_duplicate_photos": true` in the payload skips the check (a
   human's override). `dry_run` should run it too, so the runbook can ask before posting.
4. **`photo_duplicates` management command** — prints groups of active watches that share
   ≥ 2 non-banner hashes, with pk, source, external id, seller and price, so the existing
   repeats (the Rolex pair above, Facebook ↔ OLX cross-posts) can be ended by hand.

## 3. Runbook side, once deployed

- `site_api.import_json`: map the 409 to a `duplicate_photos` skip carrying `duplicate_of`
  (never a retry, never the DOM fallback — nothing was saved).
- Add the endpoint behaviour to `references/django-backend.md`.
- Keep the local check: it runs in pass 1, before anyone reads a photo or writes a description.

## 3b. Found while implementing: shop cards (user directive 2026-10-07)

Run over the 1648 downloaded ads, the rule flagged one pair that was two different
watches: TotalConvert's 304459760 / 304460733 (blue and orange Apple Watch Ultra, 2899
and 1429 RON), sharing three shop cards that were on only two ads — far under the
5-listing banner rule, which a refused import can never help it reach. 16 such files
were found, all advertising (TotalConvert, Express Credit Amanet, LuckyGold, BuyBack,
one with the shop's phone) or catalogue box shots. Decision: **they are never imported.**
`photo_dedup.shop_cards` drops them in both passes (a file in
`references/shop-cards.json`, or one beside two different watches — each ad with ≥ 2
photos the other lacks); the list is seeded with the 16 and learns. The server check is
unchanged. Cards already stored on older listings stay until someone removes them.

## 4. Not in scope

Perceptual hashing (the same photo re-encoded or cropped). Byte-identical files are what
OLX actually serves for a relisted upload, and they need no tuning; revisit only if the
409 is seen to miss re-uploads.
