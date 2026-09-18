# Standalone OLX import agent — design & handover

**Date:** 2026-09-15
**Status:** brainstormed, decisions below approved by the user; NOT yet implemented.
Next step: turn this into an implementation plan (superpowers:writing-plans), starting
with the spikes in §9.

---

## 0. Read this first (handover)

You are picking this up in a fresh Claude Code session with no memory of the
brainstorm. Everything decided is in this file. Before planning:

1. Read `CLAUDE.md` and `OLX_Listing_Automation_Plan.md` (how the project runs today).
2. Read these scripts — they are the logic being ported, not rewritten from scratch:
   - `harness/3ceasuri-import/scripts/olx-import-watch.py` and `olx-import-smartwatch.py`
     (the per-ad flow, gates, merge rules)
   - `olx-find-watches.py` / `olx-find-smartwatches.py` (discovery filters)
   - `olx_api.py`, `admin_import.py`, `infer_fields.py`, `price_sanity.py`
3. The Django backend is a separate repo: `~/projects/anunturi/ceasuri`
   (`watches/models.py`, `watches/admin.py`).

Do not implement anything the user has not approved. The open questions in §10
need the user's answer before the plan is final.

---

## 1. Goal

Today the OLX → 3ceasuri.ro import is a **runbook executed by Claude Code (Sonnet)**:
skills in `.claude/skills/`, browser-use payload scripts, and the model orchestrating
every step, filling the extraction contract, triaging and troubleshooting.

The user wants a **standalone agent**:

- packaged as a **Docker container**, runnable unattended (e.g. on a schedule);
- using a **small/local LLM** (target: Mac Studio M1 Ultra, 64 GB) instead of Claude;
- **reliable** — the user's core concern is that a small local LLM is unreliable.

## 2. Decisions made (with the user)

| # | Decision | Choice |
|---|---|---|
| D1 | Publishing policy | **Hybrid**: high-confidence watches publish automatically; anything uncertain goes to a human review queue. |
| D2 | Where the container runs | **Home network** (Mac Studio or another box at home) — residential IP, same as today. |
| D3 | Sources | **OLX only.** Facebook stays on the existing Claude Code runbook (or is dropped). |
| D4 | Browser | The container talks **CDP to a Chrome running on the host** (dedicated agent profile, logged into OLX). |
| D5 | Orchestration | **A plain Python script** (deterministic pipeline / state machine). **No LangChain or agent framework.** |
| D6 | LLM role | **Exactly one LLM call per ad**: map the OLX ad (text + OLX params) to the DB schema. The LLM never orchestrates, never chooses tools, never troubleshoots. |
| D7 | Photos | **Text only now; vision later** (a later phase, gated by the eval in §7). |

## 3. Key findings from the brainstorm

### 3.1 Why a small LLM can be reliable *in this design*

Small models fail at long agentic loops (tool choice, recovery, long context) and at
free-form output. This design removes both:

1. **Orchestration is code, not the LLM.** Everything Sonnet does today besides
   filling the contract (running scripts, parsing marker lines, retries, state,
   `/clear` between watches) becomes deterministic Python.
2. **Schema-constrained decoding.** Ollama / llama.cpp / LM Studio / MLX can force the
   output to a JSON schema (`response_format` with a JSON schema, or a grammar).
   Every response parses and every enum is legal — the biggest small-model failure
   mode disappears by construction. *(Verify the chosen backend's support in a spike.)*
3. **Most fields never reach the LLM's judgement.** `olx_api.map_params()` already
   maps condition, case material, display type, water resistance, gender, style,
   price/currency/negotiable and location from the seller's dropdown params. The LLM
   mainly decides `model`, `movement`, `reference`, `is_wristwatch`, `category`,
   `is_bulk_lot`, `notes`, and for smartwatches `connectivity` / `compatibility`.
4. **Deterministic cross-checks after the call** catch hallucination (see §6).
5. **It is measurable before trusting it**: `history.jsonl` holds ~935 OLX imports and
   ~288 skips decided by Sonnet, and the saved records are in the admin DB. Replay them
   (§7).

### 3.2 What fits on a Mac Studio M1 Ultra 64 GB

- macOS lets the GPU wire ~70–75 % of unified memory by default → **~45–48 GB** for
  weights + KV cache. Raisable with `sudo sysctl iogpu.wired_limit_mb=<MB>`.
- Candidate classes (check what is current at build time — the landscape moves fast):

| Class (examples) | RAM | Rough speed on M1 Ultra | Notes |
|---|---|---|---|
| ~30B MoE (e.g. Qwen3-30B-A3B), Q8 | ~32 GB | fast, ~50+ tok/s | good baseline for structured extraction |
| ~27–32B dense (e.g. Qwen3-32B, Gemma 3 27B), **Q8** | ~30–35 GB | ~12–18 tok/s | **recommended sweet spot**; Gemma 3 also has vision for phase 2 |
| ~70B dense (e.g. Llama 3.3 70B), Q4 | ~40–43 GB | ~7–9 tok/s | tight fit, text only |

- Prefer **Q8 over Q4** for extraction accuracy when it fits.
- A call is ~3–4 k tokens in (prompt + ad) and a few hundred tokens of JSON out →
  roughly **30–60 s per ad**. Plenty for ~40 ads per session; latency is not a concern.
- Speeds above are estimates; measure in the eval spike.
- Pick the model by the replay eval (§7), not by benchmarks.

### 3.3 Docker on macOS

Docker Desktop runs Linux in a VM with **no GPU passthrough**. The LLM therefore runs
**on the host** (Ollama / LM Studio / llama.cpp server / MLX server), and the container
calls it over HTTP at `http://host.docker.internal:<port>/v1`. This is a feature: the
agent container stays small and the model is swappable by URL + model name.

### 3.4 CDP from the container to host Chrome (known gotchas)

Feasible, with these gotchas to resolve in spike S1:

1. Chrome binds DevTools to `127.0.0.1`. The container cannot reach that directly.
   Put a tiny forwarder on the host (e.g. `socat` listening on an address the Docker
   VM can reach → `127.0.0.1:9222`). Do not rely on
   `--remote-debugging-address=0.0.0.0` (ignored by headful Chrome).
2. DevTools HTTP endpoints reject a `Host` header that is not `localhost` or an IP —
   `host.docker.internal` gets refused. Send `Host: localhost`, connect by IP, or let
   the forwarder handle it.
3. `/json/version` returns `ws://127.0.0.1:9222/...` — the client must rewrite the
   host part. Chrome may also need `--remote-allow-origins=*` for the WebSocket.
4. Recent Chrome (136+) refuses remote debugging on the **default** profile — launch
   with a dedicated `--user-data-dir`. That is the desired design anyway: **a separate
   agent Chrome**, logged into OLX once, never the user's everyday browser.
5. Security: port 9222 = full control of a logged-in browser. Expose it to the Docker
   network only, never the LAN.
6. Launch agent Chrome automatically on host login (launchd). The agent checks CDP at
   startup and fails loudly (alert) if Chrome is down.

Playwright's `chromium.connect_over_cdp()` is the suggested client (it is the only
heavy dependency, and it is for the browser, not the LLM). Headless Chrome inside the
container is a **later fallback mode**, not the default.

### 3.5 Why the browser is still needed at all

- OLX answers a plain HTTP GET with **403**; its JSON API answers from a page already
  on `olx.ro` (the current `olx_api._fetch_json` does an in-page `fetch()`).
- Phone numbers are masked in the JSON and `/api/v1/offers/<id>/phones/` returns 400;
  the importer clicks the page's show-phone button (`olx_api.reveal_phone`), and it
  only works when the browser is **logged into OLX**.
- Worth a cheap probe (S1): does a TLS-impersonating HTTP client (e.g. `curl_cffi`)
  pass the 403? If yes, the browser is only needed for the phone reveal.

### 3.6 Known problem the redesign should remove

Session 19: a genuine Rolex GMT was dropped because `fetch()` of its photos **from
the admin tab's origin** hit a deterministic CORS block on one
`frankfurt.apollo.olxcdn.com` shard. Photos must be fetched **outside a browser page
origin** (agent-side HTTP download, or server-side) — see §5.6.

## 4. Architecture

```
┌──────────────────────── host (Mac Studio, home network) ────────────────────────┐
│                                                                                   │
│  Agent Chrome (dedicated profile, logged into OLX)  ◄── CDP via forwarder ──┐     │
│  LLM server (Ollama / LM Studio / llama.cpp / MLX)  ◄── HTTP /v1 ───────────┤     │
│                                                                              │     │
│  ┌──────────────── Docker container: olx-agent ───────────────────────────┐ │     │
│  │ orchestrator.py ─ discover → per ad: fetch → gate → llm_fill → checks  │─┘     │
│  │                   → decide (publish | review | skip) → publish → log   │       │
│  │ SQLite volume (state, run log, review queue)                           │       │
│  └────────────────────────────────────────────────────────────────────────┘       │
└───────────────────────────────────────────────────────────────┬───────────────────┘
                                                                │ HTTPS + token
                                                   3ceasuri.ro  ▼  Django import API
```

### 4.1 Modules (suggested; plain Python, small focused files)

| Module | Responsibility | Ported from |
|---|---|---|
| `orchestrator.py` | CLI entry; runs one session: discovery then the per-ad state machine; target count; stops cleanly | the orchestrator MD + skills |
| `config.py` | env-based config (CDP URL, LLM URL/model, API token, targets, thresholds) | `olx-session-setup` |
| `browser.py` | CDP connection to host Chrome, tab management, in-page `fetch`, startup health check | `olx_api.bind/ensure_tab/_fetch_json` |
| `olx_client.py` | search pages, single offer, `map_params`, `clean_description`, `photo_urls`, `reveal_phone`, seller, location | `olx_api.py` (logic kept, browser-use `bind(globals())` replaced by an injected `browser` object) |
| `discovery.py` | objective filters: inactive, no/low price, replica / accessory / bulk wording, blocklist, `looks_smart` / `looks_classic` routing flags | `olx-find-watches.py`, `olx-find-smartwatches.py` |
| `contract.py` | Pydantic models for the contract (classic + smart profiles), JSON schema generation, the prompt builder, `validate()` | `infer_fields.py` |
| `llm.py` | OpenAI-compatible chat call, `response_format` = JSON schema, one retry with the validation error fed back, timeouts | new (~50 lines) |
| `checks.py` | `price_sanity` + cross-checks (§6) + confidence scoring | `price_sanity.py` + review gate in the importers |
| `publisher.py` | client for the new Django import API (dedup query, create watch, upload photos) | replaces `admin_import.py` + `import-watch.js` |
| `store.py` | SQLite: runs, per-ad outcome, review queue, raw LLM I/O for debugging | replaces `state.json`, `history.jsonl`, `.candidates-*.json` |
| `eval/replay.py` | offline replay of historical ads against a chosen model (§7) | new |
| `notify.py` | alert on hard failures (Chrome down, LLM down, API auth failure, OLX 403 storm) | new |

Optional library: `instructor` (Pydantic + retries on any OpenAI-compatible backend).
Hand-rolled is equally fine. **No LangChain / LlamaIndex / CrewAI.**

## 5. Per-ad pipeline (the state machine)

Order matters: every cheap deterministic rejection happens **before** the LLM call.

1. **Stage-1 dedup** — ask the backend whether `external_listing_id=<ad id>` exists →
   `skip: already imported`.
2. **Fetch the ad** — `GET /api/v1/offers/<id>/` in page context. Missing → `error`;
   `status != active` → `skip`.
3. **Blocklist** — `user.id` in `seller-blocklist.json` (`olx_sellers`) → `skip`.
4. **Price sanity (hard skip)** — `price_sanity.implausible_price(price, currency,
   brand_param, text)` → `skip: suspiciously cheap`. Never overridable automatically
   (standing user directive 2026-08-09).
5. **Deterministic mapping** — `map_params`, brand match (`brand param → title →
   description`), `clean_description`, regex hints (diameter/year/movement/reference)
   → the `known` block. Route profile: `classic` vs `smart` by category **and**
   `looks_smart` / `looks_classic` (iron rule 7: route by kind, not category).
6. **LLM fill** — one call, text only (§5.1). Output = the full contract, validated by
   Pydantic. Invalid → one retry with the error text → still invalid → `review`.
7. **Merge rules** (keep today's semantics, see `olx-import-watch.py` §4–5):
   - the filled contract is authoritative; a contract field it leaves null is cleared;
   - OLX **metadata** (location, county, city, phone, source URL, seller id/name,
     images) is restored, never cleared;
   - `is_wristwatch=false` and `category != wall` → `skip`; `is_bulk_lot=true` → `skip`
     (or `review`, see §10);
   - contract-only keys (`is_wristwatch`, `is_bulk_lot`, `notes`) are not saved.
8. **Checks + confidence** (§6) → decision `publish | review`.
9. **Stage-2 dedup (repost)** — same seller + model already on site → strong match
   `skip`, weak (model-only) → `review`. Port `admin_import.find_repost` semantics.
10. **Phone reveal** — only for ads that will be published or queued (it costs a page
    navigation). `phone_status` recorded; a missing phone never fails an import.
11. **Publish** — call the import API with the record and photos (§5.6). Publish means
    live; review means saved but not live (§10 Q1).
12. **Verify + log** — read the created record back through the API (replaces banner
    checks), store the outcome in SQLite.

### 5.1 The prompt (text-only phase)

Reuse `infer_fields.RULES_CLASSIC` / `RULES_SMART`, **but they must be edited**: they
repeatedly instruct the model to LOOK AT THE PHOTOS, read the dial/caseback, and
describe Facebook-specific cleanup. For the text-only phase:

- remove all photo instructions; state that only the ad text and OLX params exist;
- `model`: take it only from the ad text; if the text does not name one, return null
  (→ review), do **not** infer from design knowledge;
- `reference`: only a string present in the ad text;
- `movement`: may be inferred from brand + model knowledge (e.g. well-known quartz or
  automatic families) but must set a `movement_inferred: true` flag so the gate can
  treat it as lower confidence;
- `description`: **do not ask the LLM to rewrite it** — use `clean_description()`
  output verbatim (saves tokens, removes a hallucination surface). Drop it from the
  LLM schema.
- keep the prompt short: small models follow fewer, sharper rules better. Put enums in
  the schema, not the prose.

Consider adding explicit per-field evidence to the schema, e.g. `model_evidence`: the
exact substring of the ad the model came from. It makes the cross-check in §6
mechanical.

### 5.2 Smart vs classic

Two Pydantic profiles sharing the field set (`contract.py`). `smart` pins
`movement/style/displayType = smart` in code (not in the LLM's hands) and requires
`connectivity` + `compatibility`. `compatibility` can be derived deterministically from
brand/model (Apple → ios; Galaxy Watch 4+ → android; Garmin/Amazfit/Huawei/Xiaomi/
Fitbit → both) — prefer code over the LLM where a rule exists.

### 5.3 Brands

Brand ids live today in `window.BRAND_IDS` in `import-watch.js` mirrored in
`references/brand-ids.md`. With an API, the backend resolves brands by name; the agent
fetches the brand list at session start. A **new brand is never auto-created in
hybrid mode** → `review` (the human confirms the brand exists and the spelling).

### 5.4 Discovery

Port the objective filters as-is. Today the human/Claude also triaged the snippets by
judgement (e.g. a projector listed as a smartwatch, two watches in one ad). In the
standalone agent that judgement moves into the contract (`is_wristwatch`,
`is_bulk_lot`, `notes`) plus the gate. Persist candidates in SQLite so a crashed run
resumes.

Region targeting: recent sessions targeted Bucuresti/Ilfov, but no region filter
exists in the scripts today — see §10 Q4.

### 5.5 Session control

`orchestrator.py --category watches|smart|both --target N [--dry-run]`.
Dry-run runs everything except the API write and records what it would have done —
this is how the agent is first trusted on live data (§9 phase 3).

### 5.6 Photos

Replace the browser/admin-form data-URL upload. Two options (decide in S3):
- **agent downloads** the `s=1000x1000` URLs with a normal HTTP client (outside any
  page origin → no CORS) and uploads bytes multipart to the API; or
- **the server downloads** from the URLs given in the API payload.
Prefer agent-side if the olxcdn URLs load without the bot check, since the agent is on
the residential IP. Require ≥ 2 photos (existing gate).

## 6. Confidence gate (hybrid publishing)

Confidence is computed **by code from signals**, never self-reported by the LLM.

**Hard skip** (never published, never queued): already imported, inactive, blocklisted
seller, implausible price, not a wristwatch / wall clock, strong repost match.

**Review** if ANY of:
- contract failed validation after the retry;
- `brand` missing or **not already known** to the backend;
- `model` null, or `model` not found (normalized, diacritic-insensitive) in title +
  description;
- `reference` set but not a substring of the ad text;
- `movement` null, or `movement_inferred` true (tunable after eval);
- brand from the LLM ≠ OLX brand param when the param is a real brand;
- price within X % above the `price_sanity` floor (X set by eval, e.g. 30 %);
- LLM `notes` non-null (suspected replica, locked device, contradiction…);
- < 2 photos, or description < 40 chars;
- smartwatch missing `connectivity` or `compatibility`;
- wall clock without `caseMat`;
- weak repost match;
- LLM output disagreed with a non-null OLX param on a mapped field (condition, caseMat,
  gender…).

**Publish** otherwise. All thresholds live in one config block and are tuned from the
replay eval.

## 7. Evaluation — decide the model with data

Ground truth: `history.jsonl` (≈935 OLX `import`, ≈288 `skip`, 2 `correction`) plus
the saved records in the admin DB (Sonnet's filled contracts after verification).

`eval/replay.py`:
1. Build a dataset: for N historical ad ids, the ad JSON (re-fetch if still live;
   **cache it** — many ads are gone, so snapshot what can be fetched now) and the
   saved DB record as the label.
2. Run the text-only pipeline up to the decision (no publish) per candidate model.
3. Report per field: exact match rate (`model` normalized, `movement`, `reference`,
   `condition`, `caseMat`, `gender`, `connectivity`, `compatibility`), skip/import
   agreement, and **the gate's precision**: of the ads the gate would auto-publish, how
   many match the label on every critical field. That precision is the reliability
   number; the review-queue size is its cost.
4. Also record latency per ad and schema-retry rate.

Note on labels: Sonnet often identified `model` **from photos**. In the text-only phase
those ads should land in review, not count as model errors — tag labels where the
model string does not appear in the ad text.

Acceptance bar (propose to the user): auto-published precision ≥ 98 % on critical
fields (`brand`, `model`, `movement`, `price`), review share ≤ ~40 %.

## 8. Django backend changes (`~/projects/anunturi/ceasuri`)

The user owns the backend; browser-driven admin form filling is replaced by a small
authenticated API. Relevant existing facts:

- `Watch` has `source`, `external_listing_id`, `seller_id`, `seller_name`,
  `is_active`, `status` (`ListingStatus`: active/sold/expired/withdrawn), `county`,
  `city`, `phone`, and `Category` includes `pocket` (not in `infer_fields.ENUMS` —
  keep enums in sync).
- `WatchAdmin` currently receives photos as base64 data URLs (`watches/admin.py`,
  "imagini salvate" banner); `Picture(watch, image, thumbnail)`.
- There is no REST framework today (`watches/views.py` is the only JSON-ish view).

Needed endpoints (token auth, staff-only):
- `GET  /api/import/exists?source=olx&external_id=<id>` — Stage-1 dedup
- `GET  /api/import/reposts?seller_id=…&model=…` — Stage-2 dedup
- `GET  /api/import/brands` — name → id list
- `POST /api/import/watches` — create a watch (published or pending review)
- `POST /api/import/watches/<id>/photos` — multipart upload (or URLs, see §5.6)
- `GET  /api/import/watches/<id>` — readback for verification

Plain Django views + JSON are enough; DRF / django-ninja optional. Needs tests in the
backend repo.

## 9. Phases

**Phase 0 — spikes (answers, throwaway code):**
- **S1 CDP path**: container → host forwarder → agent Chrome; in-page `fetch` of
  `/api/v1/offers/?category_id=1677` and one offer; phone reveal while logged in.
  Also probe whether `curl_cffi` avoids the 403.
- **S2 LLM backend**: serve 2–3 candidate models on the Mac Studio; confirm JSON-schema
  constrained output works with the chosen server; measure tok/s and per-ad latency.
- **S3 photos**: can olxcdn `s=1000x1000` URLs be downloaded with plain HTTP from home?
- **S4 dataset**: how many historical ad ids still return from the OLX API; snapshot them.

**Phase 1 — eval harness** (§7) with the ported `olx_client` / `contract` / `llm` /
`checks`, no publishing. Pick the model and tune thresholds.

**Phase 2 — backend API** (§8) with tests; draft/review representation decided.

**Phase 3 — orchestrator end-to-end in `--dry-run`** on live OLX, compared side by side
with a Claude Code session on the same ads.

**Phase 4 — live hybrid publishing**, container + schedule + alerts. Keep the Claude
Code runbook as the fallback and for the review queue if useful.

**Phase 5 (later) — vision**: add one photo (dial) with a local VLM for ads whose
text names no model; gated by a new eval run on the photo-identified subset.

## 10. Open questions for the user

1. **How is "review" represented on the site?** Options: `is_active=False` + a new
   `ListingStatus.PENDING_REVIEW`; a separate `needs_review` flag; or a staging table.
   (`is_active=False` + `withdrawn` would misstate the listing's history.)
2. **Review UI**: Django admin list filter + bulk "approve" action is the cheapest.
   Acceptable?
3. **Bulk lots and "not a wristwatch"**: skip silently as today, or queue for review?
4. **Region targeting**: should discovery filter by region (e.g. Bucuresti/Ilfov) and
   how was that done in sessions 18–19?
5. **Schedule and volume**: how often, how many ads per run?
6. **Alert channel**: email, Telegram, other?
7. **Blocklist growth**: today Claude adds counterfeit sellers to the blocklist. In the
   standalone agent, only the human adds them (from the review queue)?
8. **Repo**: new repository for the agent, or a new top-level directory here?

## 11. Out of scope (for now)

- Facebook source.
- Vision / photo identification (phase 5).
- Agent self-troubleshooting or editing its own code.
- Headless Chrome inside the container (fallback mode, later).
- Running the container on a VPS / datacenter IP (would need residential proxy work).
- OLX chat, delivery, safedeal metadata.

## 12. Iron rules that carry over

1. One ad at a time; every decision logged.
2. Read OLX only from a page already on olx.ro (unless S1 proves otherwise).
3. Verify by reading the record back, not by trusting a return value.
4. Always store description, source URL, external listing id, seller id/name.
5. Never import a suspiciously cheap listing (`price_sanity.py` is the single source of
   floors).
6. Route by kind (smart vs classic), not by category.
7. A contract field the LLM leaves null is cleared, not defaulted — in particular
   `movement` must never silently default to quartz.
