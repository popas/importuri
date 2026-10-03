#!/usr/bin/env python3
"""Which of the site's active OLX listings are gone from OLX — and, once the Django
`deactivate/` endpoint is deployed, end them.

Nothing ever ended a listing when its OLX ad was sold or deleted. On 2026-10-04, 23 of
a random 60 of the 1323 active OLX listings answered 410/404 on OLX, so roughly 500
watches were shown as for sale, with the seller's phone, that no longer existed.
The contract for the two admin endpoints this uses is
docs/handover/2026-10-04-deactivate-gone-olx-listings.md.

Read-only unless APPLY=1, and even then only the server-side endpoint writes: there is
no fallback that ticks boxes in the admin form. Every ambiguous OLX answer (403, 429,
a bot-check page, a timeout, an unfamiliar status) is "unknown" and never sent —
deactivating a listing because OLX was briefly in a bad mood would be worse than
leaving it up one more day.

The payload wrapper is olx-check-active.py; this module takes the CDP helpers through
`run(globals())`, like olx_import.run().
"""

import datetime
import json
import os
import random
import time

ACTIVE_IDS_PATH = "/admin/watches/watch/active-ids/"
DEACTIVATE_PATH = "/admin/watches/watch/deactivate/"
CHANGELIST_PAGE = "/admin/watches/watch/?source__exact=olx&is_active__exact=1&p=%d"
PAGE_LIMIT = 500            # active-ids rows per request; responses stay well under 64 KB
APPLY_BATCH = 200           # items per deactivate POST; the request stays under 64 KB
BLOCKED_HTTP = (0, 403, 429)
BLOCKED_STREAK = 5          # this many blocked answers in a row stops the sweep

# OLX ad status -> the site's ListingStatus. Only these are trusted as "gone";
# any other non-active status is reported as unknown for a human to look at.
GONE_STATUS = {"outdated": ("expired", "olx_outdated"),
               "removed_by_user": ("withdrawn", "olx_removed_by_user")}


def classify(http, status):
    """(verdict, listing_status, reason) for one OLX answer.

    verdict: "active" | "gone" | "unknown". Only "gone" is ever sent to the site.
    """
    if http == 200 and status == "active":
        return "active", None, None
    if http in (404, 410):
        return "gone", "withdrawn", "olx_http_%d" % http
    if http == 200 and status in GONE_STATUS:
        return ("gone",) + GONE_STATUS[status]
    if http == 200:
        return "unknown", None, "olx_status_%s" % (status or "unreadable")
    return "unknown", None, "olx_http_%s" % http


# --- the site side ------------------------------------------------------------
_FETCH_JS = ('(async () => { try { const r = await fetch(%s, %s);'
             ' return JSON.stringify({http: r.status, redirected: r.redirected,'
             ' ctype: r.headers.get("content-type") || "", body: await r.text()}); }'
             ' catch(e) { return JSON.stringify({http: 0, body: String(e)}); } })()')


def _fetch(bu, path, init):
    """fetch() a same-origin path from the current tab: {http, redirected, ctype, body}."""
    return json.loads(bu.js(_FETCH_JS % (json.dumps(path), init)))


def _is_json(env):
    """True only for a real answer from the endpoint.

    An endpoint that is not deployed yet does NOT 404: the admin's
    `<path:object_id>/` catch-all takes the path for an object id and redirects to
    /admin/ with an HTML page (200). Checked live on 2026-10-04.
    """
    return (env.get("http") == 200 and not env.get("redirected")
            and "json" in (env.get("ctype") or ""))


def _get(bu, path):
    return _fetch(bu, path, '{headers: {Accept: "application/json"}}')


_PAGE_JS = r'''(async () => {
  const r = await fetch(%s);
  if (!r.ok) return JSON.stringify({http: r.status, rows: []});
  const d = new DOMParser().parseFromString(await r.text(), "text/html");
  const rows = [...d.querySelectorAll("#result_list tbody tr")].map(tr => {
    const c = n => { const e = tr.querySelector("td.field-" + n); return e ? e.innerText.trim() : ""; };
    const a = tr.querySelector('a[href*="/change/"]');
    const m = a ? a.getAttribute("href").match(/\/(\d+)\/change/) : null;
    return {id: c("external_listing_id"), pk: m ? Number(m[1]) : null, created: c("created_at")};
  });
  return JSON.stringify({http: r.status, rows});
})()'''


def active_ids(bu, max_pages=60):
    """([{id, pk, created}], via). via: "endpoint" | "changelist".

    Prefers active-ids/; while that is not deployed yet (_is_json) it scrapes the
    filtered changelist one page per call — a single call for every page outran
    CDP's evaluate timeout on 2026-10-04.
    """
    env = _get(bu, "%s?source=olx&after_pk=0&limit=%d" % (ACTIVE_IDS_PATH, PAGE_LIMIT))
    if _is_json(env):
        rows, after = [], 0
        while True:
            d = json.loads(env["body"])
            rows += [{"id": str(r["external_listing_id"]), "pk": r.get("pk"),
                      "created": r.get("created_at")} for r in d.get("results") or []]
            after = d.get("next_after_pk")
            if not after:
                return rows, "endpoint"
            env = _get(bu, "%s?source=olx&after_pk=%s&limit=%d" % (ACTIVE_IDS_PATH, after, PAGE_LIMIT))
            if not _is_json(env):
                raise RuntimeError("active-ids/ answered %s mid-way (after_pk=%s)"
                                   % (env.get("http"), after))

    seen, rows = set(), []
    for page in range(1, max_pages + 1):
        d = json.loads(bu.js(_PAGE_JS % json.dumps(CHANGELIST_PAGE % page)))
        new = [r for r in d.get("rows") or [] if r.get("id") and r["id"] not in seen]
        if not new:          # past the last page Django re-serves an error/empty list
            break
        for r in new:
            seen.add(r["id"])
            rows.append(r)
    return rows, "changelist"


def csrf_token(bu):
    """The admin's CSRF token: the cookie, else the hidden input of an admin form."""
    tok = bu.js('(() => { const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);'
                ' return m ? decodeURIComponent(m[1]) : ""; })()')
    if tok:
        return tok
    return bu.js('(async () => { const d = new DOMParser().parseFromString(await (await fetch('
                 '"/admin/watches/watch/add/")).text(), "text/html");'
                 ' const i = d.querySelector("input[name=csrfmiddlewaretoken]");'
                 ' return i ? i.value : ""; })()') or ""


def deactivate(bu, gone, dry_run=False):
    """POST the gone ids in batches. Returns the merged server answer, or
    {"unavailable": True, ...} while the endpoint is not deployed (see _is_json:
    that is a redirect to /admin/, not a 404)."""
    merged = {"dry_run": dry_run, "deactivated": [], "already_inactive": [],
              "not_found": [], "rejected": {}}
    token = csrf_token(bu)
    for i in range(0, len(gone), APPLY_BATCH):
        body = {"source": "olx", "dry_run": dry_run,
                "items": [{"external_listing_id": g["id"], "status": g["listing_status"],
                           "reason": g["reason"]} for g in gone[i:i + APPLY_BATCH]]}
        env = _fetch(bu, DEACTIVATE_PATH,
                     '{method: "POST", headers: {"Content-Type": "application/json",'
                     ' "X-CSRFToken": %s}, body: %s}' % (json.dumps(token), json.dumps(json.dumps(body))))
        if i == 0 and (env.get("http") == 404 or (env.get("http") == 200 and not _is_json(env))):
            return {"unavailable": True, "http": env.get("http"), "redirected": env.get("redirected")}
        if not _is_json(env):
            merged.setdefault("errors", []).append({"batch": i // APPLY_BATCH, "http": env.get("http"),
                                                     "body": (env.get("body") or "")[:300]})
            continue
        d = json.loads(env["body"])
        for k in ("deactivated", "already_inactive", "not_found"):
            merged[k] += d.get(k) or []
        merged["rejected"].update(d.get("rejected") or {})
    return merged


# --- the OLX side ---------------------------------------------------------------
def olx_answer(bu, ad_id):
    """{http, status} for one ad, fetched from a tab on www.olx.ro."""
    return json.loads(bu.js(
        '(async () => { try { const r = await fetch("/api/v1/offers/%s/", {headers:{Accept:'
        '"application/json"}}); const t = await r.text(); let st = null;'
        ' try { st = JSON.parse(t).data.status; } catch(e) {}'
        ' return JSON.stringify({http: r.status, status: st}); }'
        ' catch(e) { return JSON.stringify({http: 0, status: null}); } })()' % int(ad_id)))


def check(bu, rows, pace=1.5, sleep=time.sleep, on_progress=None):
    """Ask OLX about every row. Returns (results, stopped) — stopped is None or a reason."""
    results, streak = [], 0
    for n, row in enumerate(rows, 1):
        a = olx_answer(bu, row["id"])
        verdict, status, reason = classify(a.get("http"), a.get("status"))
        results.append(dict(row, http=a.get("http"), olx_status=a.get("status"),
                            verdict=verdict, listing_status=status, reason=reason))
        streak = streak + 1 if a.get("http") in BLOCKED_HTTP else 0
        if streak >= BLOCKED_STREAK:
            return results, "blocked: %d blocked answers in a row (last http %s)" % (streak, a.get("http"))
        if on_progress and n % 100 == 0:
            on_progress(n, results)
        if pace:
            sleep(pace)
    return results, None


def summarize(results, total, via, stopped):
    counts = {"active": 0, "gone": 0, "unknown": 0}
    for r in results:
        counts[r["verdict"]] += 1
    decided = counts["active"] + counts["gone"]
    return {"site_active_olx": total, "via": via, "checked": len(results), **counts,
            "gone_pct": round(100.0 * counts["gone"] / decided, 1) if decided else None,
            "stopped": stopped}


# --- the payload --------------------------------------------------------------
def run(g):
    """Entry point for olx-check-active.py. Env:

    SAMPLE=N   check a random N of the active listings (SEED for a repeatable draw)
    LIMIT=N    check the first N (by pk) instead
    IDS=a,b    check exactly these ids (skips listing the site)
    PACE=1.5   seconds between OLX requests
    APPLY=1    post the gone ones to deactivate/ (APPLY=dry: server-side dry run)
    OUT=path   the JSON report (default .runs/active-check-<timestamp>.json)
    """
    import admin_import, olx_api

    bu = admin_import.bind(g)
    emit = lambda tag, obj: print("%s: %s" % (tag, json.dumps(obj, ensure_ascii=False)), flush=True)
    root = os.environ.get("PROJECT_ROOT") or os.getcwd()
    out = os.environ.get("OUT") or os.path.join(
        root, "harness/3ceasuri-import/.runs",
        "active-check-%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M"))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    tabs = bu.list_tabs()
    admin_tab = next((t["targetId"] for t in tabs if "3ceasuri.ro/admin" in (t.get("url") or "")), None)
    if not admin_tab:
        emit("ERROR", {"msg": "no 3ceasuri.ro/admin tab - open the admin and sign in"})
        raise SystemExit(1)

    bu.switch_tab(admin_tab)
    if os.environ.get("IDS"):
        rows = [{"id": i.strip(), "pk": None, "created": None}
                for i in os.environ["IDS"].split(",") if i.strip()]
        total, via = None, "ids"
    else:
        rows, via = active_ids(bu)
        total = len(rows)
    emit("ACTIVE_IDS", {"count": total, "via": via})

    if os.environ.get("SAMPLE"):
        random.seed(os.environ.get("SEED") or None)
        rows = random.sample(rows, min(int(os.environ["SAMPLE"]), len(rows)))
    elif os.environ.get("LIMIT"):
        rows = sorted(rows, key=lambda r: r.get("pk") or 0)[:int(os.environ["LIMIT"])]

    def save(results, stats=None, applied=None):
        with open(out, "w") as f:
            json.dump({"stats": stats, "applied": applied, "results": results}, f,
                      ensure_ascii=False, indent=1)

    olx_api.ensure_tab(bu, None, bu.list_tabs())
    results, stopped = check(bu, rows, pace=float(os.environ.get("PACE", "1.5")),
                             on_progress=lambda n, r: (save(r), emit("PROGRESS", {"checked": n})))
    stats = summarize(results, total, via, stopped)
    gone = [r for r in results if r["verdict"] == "gone"]
    save(results, stats)
    emit("STATS", stats)
    emit("GONE", [r["id"] for r in gone])
    unknown = [{"id": r["id"], "reason": r["reason"]} for r in results if r["verdict"] == "unknown"]
    if unknown:
        emit("UNKNOWN", unknown[:50])

    mode = os.environ.get("APPLY", "")
    if mode in ("1", "dry") and gone:
        if stopped:
            emit("APPLY_SKIPPED", {"reason": "the sweep stopped early (%s) - re-run first" % stopped})
        else:
            bu.switch_tab(admin_tab)
            applied = deactivate(bu, gone, dry_run=(mode == "dry"))
            save(results, stats, applied)
            emit("APPLY_UNAVAILABLE" if applied.get("unavailable") else "APPLY",
                 applied if applied.get("unavailable") else
                 {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in applied.items()})
    emit("REPORT", {"path": out})
