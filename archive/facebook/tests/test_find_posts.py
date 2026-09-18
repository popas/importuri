#!/usr/bin/env python3
"""Offline harness for find-posts.py: stubs the browser-use globals and feeds a
canned [role=feed] so every objective filter path is exercised without Chrome."""
import json, os, re, sys, io, contextlib

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
SRC = os.path.join(ROOT, "archive/facebook/scripts/find-posts.py")

BLOCKED = "100014204027198"   # Timofeevich Vasilovich, from seller-blocklist.json

# id, videofirst, author, text  -- one per filter path
FEED = [
    dict(i=0, id="111", lid=None, vf=False, au="1001", txt="Vand ceas Doxa mecanic vintage, stare buna, functioneaza impecabil. Pret 500 lei, negociabil. Tel 0731394148"),
    dict(i=1, id="222", lid=None, vf=True,  au="1002", txt="Super oferta ceasuri! Pret 1500 lei"),
    dict(i=2, id="333", lid=None, vf=False, au=BLOCKED, txt="Vand Seiko 5 automatic, 40 mm, pret 800 lei"),
    dict(i=3, id="444", lid=None, vf=False, au="1004", txt="Replica AAA+ Rolex Submariner, calitate 1:1, pret 900 lei"),
    dict(i=4, id="555", lid=None, vf=False, au="1005", txt="Ceas de perete vechi, lemn masiv, pret 300 lei"),
    dict(i=5, id="666", lid=None, vf=False, au="1006", txt="ENICAR by Ariste Racine estab. 1913, Switzerland"),
    dict(i=6, id="777", lid=None, vf=False, au="1007", txt="Ceas vechi rusesc de colectie, pret 99 lei"),
    dict(i=7, id="888", lid=None, vf=False, au="1008", txt="Ceas dama mic, curea piele, 15 euro"),
    dict(i=8, id="999", lid=None, vf=False, au="1009", txt="Vand Citizen Eco-Drive titan, 42 mm, pret 1200 lei"),
    # link-less: no id/lid but has a price -> must be recovered by force-hydrate
    dict(i=9, id=None, lid=None, vf=False, au="1010", txt="Rolex Submariner 16610, full set, cutie si acte, pret 7500 euro"),
    # diacritics: post says Genève, BRAND_IDS says Helfer Geneve
    dict(i=10, id="1212", lid=None, vf=False, au="1011", txt="Helfer Genève Quadrix J2 Stones, 43 mm, safir, pret 3000 euro"),
    # real 2026-07-27 feed post: PLURAL wall clocks + a price range (stock clearing, not a listing)
    dict(i=11, id="1313", lid=None, vf=False, au="1012", txt="Ceasuri de perete funcționale, prețuri cuprinse între 200-350 ron. Junghans, Wehrle-Germani. Westerstrand Suedia. 0763 549 947"),
    # bulk lot of wristwatches: price range alone must be enough to drop it
    dict(i=12, id="1414", lid=None, vf=False, au="1013", txt="Vand Seiko si Citizen, lot de 3 ceasuri de mana, preturi cuprinse intre 500-900 lei"),
]
HYDRATED_ID = "1010"
ALREADY_IMPORTED = {"999"}     # admin ?q=999 returns a row

state = {"url": "https://www.facebook.com/groups/vanzareceasuri/", "scrollY": 0, "calls": []}


def _feed_json():
    items = []
    for it in FEED:
        d = dict(it)
        items.append(d)
    return json.dumps({"ok": True, "h": 20000 + state["scrollY"], "y": state["scrollY"],
                       "n": len(FEED), "items": items})


def js(expr):
    state["calls"].append(expr[:40])
    if "createTreeWalker" in expr:
        return _feed_json()
    if "scrollBy" in expr:
        state["scrollY"] += 1400
        return "ok"
    if "location.href" in expr and "paginator" not in expr:
        return state["url"]
    if "scrollIntoView" in expr:
        return "c"
    if "set=pcb" in expr and "children" in expr:
        m = re.search(r"children\[(\d+)\]", expr)
        idx = int(m.group(1))
        if FEED[idx]["id"] is None:
            FEED[idx]["id"] = HYDRATED_ID       # media lazy-loaded on second look
            return HYDRATED_ID
        return FEED[idx]["id"] or ""
    if "paginator" in expr:
        m = re.search(r"[?&]q=(\d+)", state["url"])
        if not m:
            return "83 watchs"                   # unfiltered changelist = admin total
        return ("1 watch" if m.group(1) in ALREADY_IMPORTED else "0 watchs")
    return ""


def list_tabs():
    return [{"targetId": "T1", "url": "https://www.facebook.com/groups/vanzareceasuri/", "title": "grup"}]

def new_tab(url):
    state["url"] = url
    return {"targetId": "T2"}

def goto_url(url):
    state["url"] = url

def close_tab(t): pass
def switch_tab(t): pass


os.environ.update({"PROJECT_ROOT": ROOT, "MAX_SCROLLS": "2", "MAX_CANDIDATES": "8",
                   "OUT": "/tmp/claude-501/cand-test.json"})

g = {"__name__": "__main__", "js": js, "list_tabs": list_tabs, "new_tab": new_tab,
     "goto_url": goto_url, "close_tab": close_tab, "switch_tab": switch_tab}

buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        exec(compile(open(SRC).read(), SRC, "exec"), g)
except SystemExit:
    pass
out = buf.getvalue()
print(out)

# ---- assertions ----
cands = json.loads(re.search(r"^CANDIDATES: (.*)$", out, re.M).group(1))
stats = json.loads(re.search(r"^STATS: (.*)$", out, re.M).group(1))
got = {c["id"] for c in cands}
fails = []

def check(cond, msg):
    if not cond: fails.append(msg)

by_all = lambda i: next((c for c in cands if c["id"] == i), {})

check(got == {"111", "222", "1010", "1212"}, "expected {111,222,1010,1212} survivors, got %s" % sorted(got))
# video-first is a candidate now (user directive 2026-08-04): the clip goes to
# Watch.video_url instead of costing us the listing.
check(stats["dropped"].get("video_first") is None, "video_first must no longer be a drop reason")
check(by_all("222").get("video") is True, "video-first candidate must be flagged video:true")
check(by_all("111").get("video") is False, "photo-only candidate must be flagged video:false")
check(stats["dropped"].get("blocklisted_seller") == 1, "blocklisted seller not dropped")
check(stats["dropped"].get("replica") == 1, "replica not dropped")
check(stats["dropped"].get("not_wristwatch") == 2, "wall clocks not dropped (singular AND plural)")
check(stats["dropped"].get("bulk_or_price_range") == 1, "bulk lot / price range not dropped")
check(stats["dropped"].get("no_price") == 1, "no-price not dropped")
check(stats["dropped"].get("price_below_floor") == 2, "price floor should drop 99 lei AND 80 eur")
check(stats["dropped"].get("already_imported") == 1, "admin dedup did not drop 999")
check(stats["admin_total"] == 83, "admin_total should be read from the paginator")

by = {c["id"]: c for c in cands}
check(by["111"]["price"] == 500 and by["111"]["cur"] == "RON", "111 price/currency wrong: %s" % by["111"])
check(by["111"]["brand"] == "Doxa", "brand hint failed for Doxa: %r" % by["111"]["brand"])
check(by["1010"]["price"] == 7500 and by["1010"]["cur"] == "EUR", "hydrate-recovered price wrong: %s" % by["1010"])
check(by["1212"]["cur"] == "EUR" and by["1212"]["price"] == 3000, "EUR parse wrong: %s" % by["1212"])
check(by["1212"]["brand"] == "Helfer Geneve", "diacritic brand match failed: %r" % by["1212"]["brand"])
check(all(len(c["snip"]) <= 180 for c in cands), "snippet exceeds SNIPPET cap")
check(len(out) < 1800, "emitted output too large: %d bytes" % len(out))

saved = json.load(open("/tmp/claude-501/cand-test.json"))
check(len(saved["candidates"]) == 4, "candidates file should hold 4 records")
check(all("text" in c for c in saved["candidates"]), "candidates file must keep FULL text for resumption")

print("emitted bytes:", len(out))
print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
