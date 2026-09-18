# OLX lore — why the rules are the rules

The skills are the execution path: numbered steps, literal commands, decision
tables. This file is the *why* behind them — every dated finding, measurement and
regression that produced a rule. Read it when troubleshooting or when changing a
rule, not while running the loop.

Nothing here is new. It was moved out of the seven `SKILL.md` files so a small
model reading them meets imperatives instead of anecdotes.

## Index

1. [Why a browser at all](#1-why-a-browser-at-all)
2. [Suspiciously cheap = fake](#2-suspiciously-cheap--fake)
3. [Triage: what stays a judgement call, and why](#3-triage-what-stays-a-judgement-call-and-why)
4. [The contract and its clearing semantics](#4-the-contract-and-its-clearing-semantics)
5. [Seller phone numbers](#5-seller-phone-numbers)
6. [Verification and the double-import trap](#6-verification-and-the-double-import-trap)
7. [Admin element ids](#7-admin-element-ids)
8. [Ground truth and the counter that drifted](#8-ground-truth-and-the-counter-that-drifted)
9. [Regression log](#9-regression-log)

---

## 1. Why a browser at all

OLX answers a plain HTTP GET with **403** — there is bot protection in front of the
site. The same request issued from a page already on `olx.ro` succeeds, because it
carries the browser's cookies and headers. So every OLX read in these scripts is a
`fetch()` executed in the page context.

What that buys: no feed scrolling, no hydration waits, no carousel walking, and
**photo URLs that do not expire**. Ad metadata comes back as JSON with the seller's
own structured attributes already filled in.

`login.olx.ro` contains "olx.ro" but is a **different origin**, so a relative
`/api/v1/` fetch from there 404s. A logged-out click on the phone button lands
exactly there, which used to leave the tab poisoned for every later run
(2026-08-09: three ads in a row failed to load before the tab was steered back).
`olx_api._is_api_origin()` exists for this.

Every `browser-use` invocation is a cold process (several seconds of overhead),
which is why each script does its whole job in ONE call. Do not reimplement their
steps as individual `js()` calls.

## 2. Suspiciously cheap = fake

Standing user directive (2026-08-09): **a suspiciously cheap listing is not a
bargain, it is a fake.** A replica seldom says "replica"; the price is what gives
it away. Discovery drops these as `suspiciously_cheap`, and the importers refuse
them outright — before the photos are fetched, and `CONFIRM=1` does **not** wave
one through.

The floors live in one place, `scripts/price_sanity.py`: a per-brand table
(Rolex 6000 RON, Omega 1500, Breitling 2500 …) plus model-family floors for
smartwatches (any Watch Ultra 1200, Apple Watch Series 9-11 700 …). They are the
lowest price a GENUINE used example plausibly trades at, set generously so the rule
catches obvious fakes rather than shaving the honest market. Tune them there and
every script follows.

The brand is matched against the ad's own words as well as the marketplace's brand
field, because that field is unreliable — **OLX offered "Swiss" for a Christophe
Duchamp**. A listing that calls itself a Rolex is judged as one.

Cases the floors were calibrated against (2026-08-12), all legitimately imported:
Rolex Datejust 36 aur 18k at 21000 RON, Apple Watch Ultra 2 at 2000, Apple Watch 9
45mm at 1100, Apple Watch S7 steel at 999, Breitling Avenger Seawolf at 9000,
Christophe Duchamp L'envie at 950, Police Timepieces at 300, Omega Seamaster
vintage at 400 EUR.

## 3. Triage: what stays a judgement call, and why

§6 decision 2 (2026-09-19) allows a hard drop **only** for wording a regex gets
right every time. Today that is: activation lock, explicit shop stock, and the
objective filters discovery already had (inactive, no price, below floor, explicit
replica wording, accessories, price ranges, blocklisted sellers, already-imported).

These are deliberately **flags, not drops**, because the false-positive cost is
real:

- **Stock photos and renders.** A "brand new sealed" ad with a press image is
  usually a dropshipper — but not always, and the photos arrive at import time
  anyway, so the call can be deferred to pass 1.
- **Inflated generation claims.** Ads routinely call a Series 6 a "Series 9". The
  photos settle it at import time.
- **Amanet and reseller stock.** Business sellers are kept by user directive and
  flagged `business: true`. They relist the same watch under fresh ad ids
  constantly; the importer's seller+model dedup catches most of it.
- **Multi-price run-on ads.** "Vand ceas Certina … 450, vand ceas Nixon … preț 300"
  reads like one post but is several items. `is_stock_listing` only catches ≥3
  prices carrying an explicit currency word right next to them, so a paragraph that
  omits the unit on some prices slips through as a single candidate. **Seen
  2026-08-11**: a 3-classic-watch post landed in the *smartwatch* sweep, and the
  brand happened to match a category-1677 brand — so brand/category agreement is
  **not** a source-routing signal. Read the snippet whichever sweep found it. Too
  few photos to attribute to individual watches → skip the whole ad, don't guess a
  split.
- **`looks_smart` / `looks_classic` / `looks_wall`.** Flagged and routed, never
  dropped — dropping them was how good listings got lost. Route by kind, not by
  category.

Two counter-examples the activation-lock regex must NOT fire on, because both are
the honest opposite claim: "icloud deconectat" and "contul sters". Likewise the
stock regex must not fire on "ultima bucata" or "1 bucata". Both are asserted in
`tests/test_olx_find.py`.

## 4. The contract and its clearing semantics

A contract field left out of the answer is **CLEARED**, not kept from the OLX
params. That is not an accident: two half-authoritative sources is how fields go
silently wrong. `infer_fields.py`'s docstring records the original failure — on
2026-08-04 the same class of decision was made four times with nothing guaranteeing
tomorrow's answer would match today's.

Since 2026-09-19 the contract travels as a **seeded draft file** rather than an
`OVERRIDES='{…}'` shell variable. Two things went wrong with the shell variable and
neither was the model's fault:

- Romanian ad text routinely contains apostrophes ("anii '70", "Cœur d'Or"), which
  terminate the single-quoting and produce a shell error the model then "fixes"
  creatively.
- Because omission clears, the model had to retype the entire cleaned seller
  description into the JSON, verbatim, every time — the single largest
  transcription surface in the loop, on the critical path of a shell argument.

The draft removes the retyping, **not** the rule: the file is the whole contract,
so a field the model blanks is still cleared. `OVERRIDES` still works and still
wins, for a human patching one field from the shell.

What genuinely needs a model, and should not be automated away:

- `model` — the ad usually does not name it; the dial does. Vision work.
- `movement` for a classic watch when the ad does not state it.
- `reference` — read from a caseback or papers photo, **never** derived from design.
- A photo set that cannot be attributed to one watch (the 2026-09-13 two-Huawei
  ad), and obvious miscategorisation (the Hisense projector filed as a smartwatch).

`movement` must never silently default to quartz. The harness fills the gap with
`quartz` because the DB column is not optional, and that guess **mislabelled a
1970s Poljot**. An ad that never states its movement stops for review.

Wall clocks import (since 2026-08-09): `is_wristwatch: false` **plus**
`category: "wall"`. Unbranded ones use brand `Fără marcă`, `caseMat` is usually
`wood`, and `diameter` is in MILLIMETRES — a 30 cm clock is `300`. Pocket, mantel,
table and alarm clocks are still out: `is_wristwatch: false` with `category` null.

## 5. Seller phone numbers

OLX masks the number in its JSON and answers `/api/v1/offers/<id>/phones/` with
400, so the importer clicks the page's show-phone button — the one place it reads
the ad's HTML rather than its JSON. It costs a page navigation (~25 s), which is
why pass 1 does it once and ships the number with the contract.

Measured live 2026-08-09, on the ad the user pointed at:

- OLX renders the reveal control **twice** (sidebar + sticky bar) and the first in
  DOM order has width 0, so `querySelector(...)` clicked the hidden one and the
  number never appeared. The click filters on
  `getBoundingClientRect().width > 0`.
- A synthetic `MouseEvent` did not trigger the handler. It must be a native
  `.click()`.
- The login wall must be checked **before** any click: on a private ad the click
  navigates to `login.olx.ro` and poisons the tab for every later API call.
- `goto_url` returns before the navigation settles, so the PREVIOUS ad can still be
  in the DOM with its number already revealed. A private seller in Berceni was
  about to be saved with an amanet's number from the ad imported moments earlier.
  The reveal confirms `location.pathname` first and reports `wrong_page` otherwise.

Signed in, both private and business sellers give up their number; signed out,
private ads show a login wall. Everything else (discovery, ad JSON, photos) works
either way — only the phone is lost, and `phone_status` records why. A missing
phone never fails an import.

A phone is marketplace metadata, not a claim in the ad text, so leaving it out of
the answer re-reveals it rather than clearing it. Same for the seller's city.

## 6. Verification and the double-import trap

The form submit navigates the tab out from under CDP, so `importWatch` raising
`{'code': -32000, 'message': 'Inspected target navigated or closed'}` or
`Runtime.evaluate timed out` is **the normal path, not a failure**. On 2026-07-17
it fired 5/5 times and all 5 had both banners; every CDP timeout in session 19 was
likewise a false negative.

**Never retry the import on that exception — verify first, or you double-import.**

`admin_import.verify()` already checks both banners, follows the saved record's
change link and reads the fields back, and puts all of it on the `RESULT:` line.
Re-running that verification by hand on whatever tab you happen to be on is how a
good import gets reported as a failure.

The `added successfully` banner is flaky on multi-image saves. `readback_ok: true`
with `banners.added_ok: false` is a success. Missing images are never a reason to
skip a watch — note the count and move on.

## 7. Admin element ids

The ids are non-obvious and reading the wrong one returns null and fakes a bug
(happened 2026-07-24):

| Field | Element id |
|---|---|
| reference | `id_reference_number` — **not** `id_reference` |
| diameter | `id_case_diameter_mm` — **not** `id_diameter` |
| listing id | `id_external_listing_id` — renamed from `id_facebook_listing_id` on 2026-08-09 |
| brand | `id_brand` — the numeric brand ID, not the name |

A readback showing `MISSING:id_external_listing_id` means the deployed admin still
has the pre-2026-08-09 names; read `id_facebook_listing_id` instead. The harness
writes through the same fallback, so nothing is lost either side of that deploy.

Provenance has been source-agnostic since 2026-08-09: `source` (`facebook`|`olx`),
`external_listing_id`, `seller_id`, `seller_name`.

Image URLs are rewritten **on purpose** on OLX: its links are unsigned and
templated, so the importer rewrites `{width}x{height}` to `1000x1000`. The archived
Facebook path forbade touching image URLs — its signed CDN params were required.
That rule is FB-only and does not apply here.

## 8. Ground truth and the counter that drifted

**Ground truth for "is this imported / how many are there" is the 3ceasuri.ro
admin, never a local file.** On 2026-07-27 the tracker claimed 33 imports while the
site held 80+ — a hand-maintained counter had drifted for weeks.

- *Is this ad on the site?* → admin `?q=<ad_id>` (both importers do this
  automatically, as dedup stage 1)
- *How many watches are on the site?* → `STATS.admin_total`, reported once per
  session by discovery

Two local files, each with one job:

- **`history.jsonl`** — append-only, one JSON object per line, never read back in
  bulk. An append cannot drift the way a counter does. Skips are worth appending
  too: the admin records what *was* imported, only this records what was rejected
  and why. Volume as of 2026-09-19: 995 imports and 332 skips, 935/288 of them OLX.
- **`state.json`** — session bookkeeping only: `session_date`, `target`,
  `session_imported`, `session_skipped`, `status`, `note`. It holds no cumulative
  totals **by design**; do not reintroduce them.

Since 2026-09-19 both writes are done by `scripts/olx-log-result.py`, not by a
hand-assembled `python3 -c` one-liner. An unverified `RESULT:` (`ok: false`) logs
nothing, so history can never claim more than the admin holds.

## 9. Regression log

| Date | What broke | The rule it produced |
|---|---|---|
| 2026-07-17 | `importWatch` raised "Inspected target navigated or closed" 5/5 times, all 5 succeeded | never retry on that exception; verify instead |
| 2026-07-24 | readback used `id_reference` / `id_diameter`, got null, faked a bug | the element-id table in §7 |
| 2026-07-26 | an author relisted the same watch repeatedly | seller blocklist (`references/seller-blocklist.json`) |
| 2026-07-27 | local counter said 33, the site held 80+ | the admin is ground truth; `state.json` holds no totals |
| 2026-08-04 | the same extraction decision made four times, differently | `infer_fields.py`: a written contract plus a validator |
| 2026-08-09 | `erin[țt]a` never matched "referință" (it ends ț+ă), so a Rolex ad yielded reference "erin" | the reference regex must match the whole word and require a digit |
| 2026-08-09 | a logged-out phone click navigated to `login.olx.ro` and 404'd every later fetch | `_is_api_origin()`; check the wall before clicking |
| 2026-08-09 | a stale page's revealed number was about to be saved to a different seller | confirm `location.pathname` before reading; `wrong_page` |
| 2026-08-09 | OLX returned a padded brand label ("Samsung ") → a brand row with a mangled slug | strip the brand label |
| 2026-08-11 | a 3-watch run-on post surfaced as one candidate in the wrong sweep | brand/category agreement is not a routing signal; read the snippet |
| 2026-08-12 | price floors calibrated | the case list in §2 |
| 2026-09-13 | one ad, two different Huawei watches, photos unattributable | skip rather than guess a split |
| 2026-09-19 | `SKILL.md` claimed `series` was a required smartwatch field; `validate()` rejects it as not-in-contract, a hard ERROR in pass 2 | the skills must be audited against `SCHEMA_FIELDS`, not written from memory |
