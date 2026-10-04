#!/usr/bin/env python3
"""The 3ceasuri admin's JSON endpoints — lookups and import-json — and the switch
that decides whether they are there at all.

Until they existed, every admin question was a page: a changelist tab and a 3 s
sleep per duplicate check (four per watch), a hand-copied brand map, and a write
path that set ~40 inputs through the DOM and judged success from banner text. The
endpoints answer the same questions in one request each, and import-json answers
with what it saved or exactly why it refused. The endpoint list is in
references/django-backend.md; the field mapping is CONTRACT_TO_MODEL below.

Detection, which is the part that bites:
  - a missing path under /admin/watches/watch/ does NOT 404 — the admin's
    `<path:object_id>/` catch-all redirects it to /admin/ (an HTML 200). So
    "deployed" is "not redirected and JSON", whatever the status;
  - a lost session is a redirect to /admin/login/, which fetch() follows. That is
    an error (SessionLost), never "not deployed": falling back to the DOM path
    would only fail more slowly;
  - one probe per process decides for all six endpoints (they ship together);
  - API=off skips the probe and keeps the DOM path: the kill switch.

Every call runs as fetch() from a 3ceasuri.ro admin tab — from the OLX tab it would
be cross-origin and carry no session cookie — and goes back to the caller's tab.

browser-use's helper socket gives up on a js() call after 5 s, and import-json can
take 20 s fetching photos. So a request is started in the page, its answer parked
on `window.__siteApi`, and collected by short polls.

Like admin_import, this takes the CDP helpers as a bound object (`bu`).
"""

import json
import os
import random
import time
import urllib.parse

import infer_fields

ADMIN_URL_MARK = "3ceasuri.ro/admin"
WATCH = "/admin/watches/watch/"
BRAND = "/admin/watches/brand/"
LOOKUP_BATCH = 500           # the endpoint's own cap
JS_LIMIT = 60000             # browser-use reads a request line of at most 64 KB
POLL = 0.5
GET_TIMEOUT = 20
POST_TIMEOUT = 90            # nginx gives up at 60 s; wait long enough to see its 504


class SessionLost(RuntimeError):
    """The admin answered with its login page: sign in again, never fall back."""


# --- the § 1.3 mapping ---------------------------------------------------------
# Harness contract key -> Watch model field. Exactly what import-watch.js writes
# (`set('id_<field>', data.<key>)`); tests/test_contract_mapping.py holds the two
# writers to each other. `brand` travels separately, as {"name": ...}.
CONTRACT_TO_MODEL = {
    "model": "model_name",
    "reference": "reference_number",
    "category": "category",
    "condition": "condition",
    "movement": "movement",
    "caseMat": "case_material",
    "braceletMat": "bracelet_material",
    "diameter": "case_diameter_mm",
    "waterRes": "water_resistance",
    "displayMat": "display_material",
    "displayColor": "display_color",
    "displayType": "display_type",
    "displaySize": "display_size",
    "year": "year",
    "gender": "gender",
    "style": "style",
    "connectivity": "connectivity",
    "compatibility": "compatibility",
    "price": "price",
    "currency": "currency",
    "description": "description",
    "phone": "phone",
    "county": "county",
    "city": "city",
    "source": "source",
    "sourceUrl": "source_url",
    "videoUrl": "video_url",
    "externalId": "external_listing_id",
    "sellerId": "seller_id",
    "sellerName": "seller_name",
}
_MODEL_TO_CONTRACT = dict((v, k) for k, v in CONTRACT_TO_MODEL.items())
_MODEL_TO_CONTRACT["brand"] = "brand"


def to_model_fields(data):
    """The contract as model fields for import-json.

    Parity with the DOM writer: None and "" are not sent (0 is), the description is
    stripped, `condition` defaults to `good` — and `movement` has NO default: the JS
    defaulted it to quartz and that mislabelled a 1970s Poljot.
    """
    out = {}
    for key, field in CONTRACT_TO_MODEL.items():
        v = data.get(key)
        if key == "description" and isinstance(v, str):
            v = v.strip()
        if v is None or v == "":
            continue
        out[field] = v
    out.setdefault("condition", "good")
    return out


def from_model_field(name):
    """A server error's field name as the contract key, or None for a non-field."""
    return _MODEL_TO_CONTRACT.get(name)


def fixable(key):
    """Can the agent answer an error on this key with `finish`? Only contract keys:
    infer_fields.validate refuses anything else, so a `fix` on a harness-filled field
    would leave the agent looping on BAD_ANSWER."""
    return bool(key) and key in infer_fields.SCHEMA_FIELDS


# --- the envelope --------------------------------------------------------------
def deployed(env):
    """A real answer from an endpoint: not redirected and JSON, whatever the status."""
    return bool(env) and not env.get("redirected") and "json" in (env.get("ctype") or "").lower()


def session_lost(env):
    return bool(env) and "/admin/login/" in (env.get("url") or "")


def body_json(env):
    try:
        return json.loads(env.get("body") or "")
    except (TypeError, ValueError):
        return None


def forced_off():
    return os.environ.get("API", "").strip().lower() == "off"


# --- the tab -------------------------------------------------------------------
def _tid(t):
    return (t.get("targetId") or t.get("target_id")) if isinstance(t, dict) else t


def _current(bu):
    cur = getattr(bu, "current_tab", None)
    if not cur:
        return None
    try:
        return _tid(cur())
    except Exception:
        return None


def admin_tab(bu, prefer=()):
    """A tab on the 3ceasuri.ro admin — the first of `prefer` that is one — or None."""
    try:
        tabs = bu.list_tabs()
    except Exception:
        return None
    ids = [_tid(t) for t in tabs if ADMIN_URL_MARK in (t.get("url") or "").lower()]
    if not ids:
        return None
    return next((p for p in prefer if p in ids), ids[0])


# --- the request ---------------------------------------------------------------
# REQ is a JSON literal on purpose: the page reads it as an object, and an offline
# stub can read the same request back out of the expression.
_START_JS = r'''(() => { /*site_api:start*/ const REQ = %s; const K = %s;
  const box = (window.__siteApi = window.__siteApi || {}); box[K] = "";
  (async () => {
    try {
      const init = {method: REQ.method, credentials: "same-origin",
                    headers: {"Accept": "application/json"}};
      if (REQ.method !== "GET") {
        const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        let tok = m ? decodeURIComponent(m[1]) : "";
        if (!tok) {
          const d = new DOMParser().parseFromString(
            await (await fetch("/admin/watches/watch/add/")).text(), "text/html");
          const i = d.querySelector("input[name=csrfmiddlewaretoken]");
          tok = i ? i.value : "";
        }
        init.headers["X-CSRFToken"] = tok;
        if (REQ.blobs) {
          const fd = new FormData();
          fd.append("payload", JSON.stringify(REQ.json));
          for (let i = 0; i < REQ.blobs.length; i++) {
            const b = await (await fetch(REQ.blobs[i])).blob();
            const ext = ((b.type || "").split("/")[1] || "jpeg").replace("jpeg", "jpg");
            fd.append("images", b, "photo-" + String(i + 1).padStart(2, "0") + "." + ext);
          }
          init.body = fd;
        } else {
          init.headers["Content-Type"] = "application/json";
          init.body = JSON.stringify(REQ.json);
        }
      }
      const r = await fetch(REQ.path, init);
      box[K] = JSON.stringify({http: r.status, redirected: r.redirected, url: r.url,
                               ctype: r.headers.get("content-type") || "", body: await r.text()});
    } catch (e) {
      box[K] = JSON.stringify({http: 0, redirected: false, url: "", ctype: "", body: String(e)});
    }
  })();
  return K; })()'''

_POLL_JS = ('(() => { /*site_api:poll*/ const b = window.__siteApi || {}; const v = b[%s];'
            ' if (v) delete b[%s]; return v || ""; })()')


def _run(bu, req, timeout):
    """Start `req` in the current tab and collect its envelope; None when the page
    never answered (a raising js(), garbage, or the deadline)."""
    key = "r%d%06d" % (int(time.time() * 1000) % 10 ** 9, random.randrange(10 ** 6))
    expr = _START_JS % (json.dumps(req, ensure_ascii=False), json.dumps(key))
    if len(expr.encode("utf-8")) > JS_LIMIT:
        raise ValueError("site_api request is %d bytes; browser-use caps a js() call at 64 KB"
                         % len(expr.encode("utf-8")))
    try:
        if bu.js(expr) != key:
            return None
    except Exception:
        return None
    poll = _POLL_JS % (json.dumps(key), json.dumps(key))
    for _ in range(int(timeout / POLL) + 1):
        time.sleep(POLL)
        try:
            v = bu.js(poll)
        except Exception:
            return None
        if not v:
            continue
        try:
            env = json.loads(v)
        except (TypeError, ValueError):
            return None
        return env if isinstance(env, dict) and "http" in env else None
    return None


def fetch(bu, path, method="GET", body=None, blobs=None, tab=None, return_to=None,
          timeout=None):
    """fetch() `path` from an admin tab: {http, redirected, url, ctype, body}, or None
    when no admin tab is open or the page never answered.

    The caller's tab (`return_to`, else the current one) is restored afterwards.
    `blobs` turns a POST into multipart: `payload` = `body` as JSON, plus one
    `images` part per blob: URL, in order. Blob URLs belong to the page that made
    them, so pass the `tab` they were staged in.
    """
    cur = _current(bu)
    back = return_to or cur
    tab = tab or admin_tab(bu, prefer=(cur, return_to))
    if not tab:
        return None
    req = {"path": path, "method": method}
    if method != "GET":
        req["json"] = body or {}
        if blobs is not None:
            req["blobs"] = list(blobs)
    if cur != tab:          # unknown counts as elsewhere: switching to a tab never reloads it
        bu.switch_tab(tab)
    try:
        return _run(bu, req, timeout or (GET_TIMEOUT if method == "GET" else POST_TIMEOUT))
    finally:
        if back and back != tab:
            bu.switch_tab(back)


def _get_json(bu, path, tab=None, return_to=None):
    """A read-only GET: the parsed body of a 200 JSON answer, else None (fall back
    for this call). A lost session raises."""
    try:
        env = fetch(bu, path, tab=tab, return_to=return_to)
    except Exception:
        return None
    if session_lost(env):
        raise SessionLost("admin session lost - sign in to 3ceasuri.ro/admin")
    if not deployed(env) or env.get("http") != 200:
        return None
    d = body_json(env)
    return d if isinstance(d, dict) else None


# --- the switch ----------------------------------------------------------------
_AVAILABLE = None


def reset():
    """Forget the probe (a payload is one process; the offline tests are not)."""
    global _AVAILABLE
    _AVAILABLE = None


def probe_report(bu, local_brand_ids):
    """What `olx-step.py start` prints: {"api": "on"|"off"|"lost", ...}, and with the
    API on, which site brands the local BRAND_IDS map lacks (by id: the map also
    holds aliases and spelling variants)."""
    if forced_off():
        return {"api": "off", "why": "forced"}
    try:
        if not available(bu):
            return {"api": "off", "why": "not deployed"}
        rows = brand_rows(bu)
    except SessionLost as e:
        return {"api": "lost", "why": str(e)}
    out = {"api": "on"}
    if rows is not None:
        # Rows, not brands_all()'s {name: id}: two rows can share a name (the site has
        # two "Eberhard & Co"), and a dict keeps only one of them.
        have = set(local_brand_ids.values())
        out["brands"] = {"site": len(rows),
                         "missing": sorted("%s (id %s)" % (b["name"], b["id"])
                                           for b in rows if b["id"] not in have)}
    return out


def available(bu, tab=None, return_to=None):
    """Are the endpoints deployed? One probe per process, `GET lookup/?ids=0`.

    Anything odd — no admin tab, a raising js(), garbage, a non-JSON envelope —
    is False, never a crash. A lost session raises SessionLost instead.
    """
    global _AVAILABLE
    if forced_off():
        return False
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        env = fetch(bu, WATCH + "lookup/?ids=0", tab=tab, return_to=return_to)
    except Exception:
        env = None
    if session_lost(env):
        raise SessionLost("admin session lost - sign in to 3ceasuri.ro/admin")
    _AVAILABLE = bool(deployed(env) and env.get("http") == 200
                      and isinstance(body_json(env), dict))
    return _AVAILABLE


# --- A1: lookups ---------------------------------------------------------------
def lookup_ids(bu, ids, tab=None, return_to=None):
    """{"existing": {id: row}, "missing": [...], "duplicates": {...}} over `ids`, or
    None when the API is off or any batch answers non-JSON.

    No `source`: dedup stays source-agnostic, like the `?q=` search it replaces —
    OLX and Facebook ids cannot collide, and an old OLX row the backfill missed
    would be invisible to source=olx.
    """
    if not available(bu, tab=tab, return_to=return_to):
        return None
    ids = [str(i) for i in ids if str(i).strip().isdigit()]
    out = {"existing": {}, "missing": [], "duplicates": {}}
    for i in range(0, len(ids), LOOKUP_BATCH):
        d = _get_json(bu, WATCH + "lookup/?ids=" + ",".join(ids[i:i + LOOKUP_BATCH]),
                      tab=tab, return_to=return_to)
        if d is None:
            return None
        out["existing"].update(d.get("existing") or {})
        out["missing"] += d.get("missing") or []
        out["duplicates"].update(d.get("duplicates") or {})
    return out


def _repost_row(r):
    """An endpoint row in the shape admin_import.find_repost reads off the changelist."""
    ext = r.get("external_listing_id")
    return {"brand": r.get("brand") or "", "model": r.get("model_name") or "",
            "extid": "" if ext is None else str(ext), "seller": r.get("seller_id") or "",
            "pk": r.get("pk"), "is_active": r.get("is_active")}


def reposts(bu, model, seller_id=None, exclude_id=None, tab=None, return_to=None):
    """{"by_seller": [rows], "by_model": [rows]} for find_repost, or None.

    The endpoint only gathers rows; whether a hit is strong, weak or vetoed by the
    brand stays in find_repost, where the rule has always lived.
    """
    if not model or not available(bu, tab=tab, return_to=return_to):
        return None
    q = {"model": model}
    if seller_id:
        q["seller_id"] = seller_id
    if exclude_id:
        q["exclude_id"] = exclude_id
    d = _get_json(bu, WATCH + "reposts/?" + urllib.parse.urlencode(q),
                  tab=tab, return_to=return_to)
    if d is None:
        return None
    return {k: [_repost_row(r) for r in (d.get(k) or []) if isinstance(r, dict)]
            for k in ("by_seller", "by_model")}


def brand_rows(bu, tab=None, return_to=None):
    """[{id, name, slug}] for every brand row on the site, by id, or None."""
    if not available(bu, tab=tab, return_to=return_to):
        return None
    d = _get_json(bu, BRAND + "all/", tab=tab, return_to=return_to)
    if d is None:
        return None
    return [b for b in d.get("brands") or [] if isinstance(b, dict) and b.get("name")]


def brands_all(bu, tab=None, return_to=None):
    """{name: id} for every brand on the site, or None. Two rows with one name keep
    the lower id, as the server's own name lookup does."""
    rows = brand_rows(bu, tab=tab, return_to=return_to)
    if rows is None:
        return None
    out = {}
    for b in rows:
        out.setdefault(b["name"], b["id"])
    return out


def brand_lookup(bu, name, tab=None, return_to=None):
    """{"id", "name", "slug"} for a brand name (normalized match), or None."""
    name = (name or "").strip()          # the server keys `found` by the trimmed name
    if not name or not available(bu, tab=tab, return_to=return_to):
        return None
    d = _get_json(bu, BRAND + "lookup/?" + urllib.parse.urlencode({"names": name}),
                  tab=tab, return_to=return_to)
    return ((d or {}).get("found") or {}).get(name)


# --- A2: import-json -----------------------------------------------------------
def import_json(bu, watch_fields, brand_name, image_urls=None, blob_urls=None,
                dry_run=False, tab=None, return_to=None):
    """POST one watch. Returns the raw envelope (None when the page never answered);
    the caller routes it — a POST never falls back to the DOM path.

    `image_urls`: a JSON body, and the server fetches the photos. `blob_urls`:
    multipart, with the photos staged in `tab` by admin_import.stage_images.
    """
    body = {"watch": watch_fields, "brand": {"name": brand_name}, "create_brand": True,
            "dry_run": bool(dry_run)}
    if blob_urls is None:
        body["image_urls"] = list(image_urls or [])
    return fetch(bu, WATCH + "import-json/", method="POST", body=body, blobs=blob_urls,
                 tab=tab, return_to=return_to)
