#!/usr/bin/env python3
"""The replay eval, end to end, on synthetic snapshots (no browser, no network).

The eval's whole job is to report a number nobody has measured -- the rate at which
a non-overridable REVIEW: gate turns an importable watch into a skip. A tool that
reports that wrongly is worse than no tool, so its arithmetic is pinned here.
"""
import json, os, subprocess, sys, tempfile

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import olx_import

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


def param(key, vkey, label):
    return {"key": key, "name": key, "type": "select",
            "value": {"key": vkey, "label": label}}


def price_param(value, currency="RON"):
    return {"key": "price", "name": "Pret", "type": "price",
            "value": {"value": value, "currency": currency, "negotiable": False}}


def photos(n):
    return [{"id": i, "filename": "f%d" % i, "width": 750, "height": 1000,
             "link": "https://x.olxcdn.com/v1/files/f%d/image;s={width}x{height}" % i}
            for i in range(1, n + 1)]


def snap(aid, cat, title, desc, params, nphotos, label):
    return {"ad": {"id": aid, "url": "https://www.olx.ro/d/oferta/x-ID%s.html" % aid,
                   "title": title, "description": desc, "status": "active",
                   "params": params, "photos": photos(nphotos),
                   "user": {"id": 1, "name": "S"},
                   "location": {"city": {"name": "Cluj-Napoca"}, "region": {"name": "Cluj"}},
                   "category": {"id": cat}},
            "label": label}


d = tempfile.mkdtemp()

# 1. a classic watch whose ad STATES its movement -> the gate does not stop it
json.dump(snap(1, 1677, "Seiko Prospex automatic 44mm",
               "Ceas automatic, cumparat in 2019, stare impecabila, cutie si documente.",
               [param("brand", "seiko", "Seiko"), price_param(3500)], 8,
               {"id": "1", "brand": "Seiko", "model": "Prospex", "price": 3500,
                "currency": "RON", "category": "wrist"}),
          open(os.path.join(d, "1.json"), "w"))

# 2. a classic watch that never states a movement -> movement_missing, action=skip
json.dump(snap(2, 1677, "Ceas dama elegant",
               "Ceas de dama, stare buna, cu cutie si garantie, purtat rar de tot.",
               [param("brand", "seiko", "Seiko"), price_param(900)], 6,
               # the label names a model the ad text never does -- it was read off
               # the dial, which is exactly the case the eval must not score as an error
               {"id": "2", "brand": "Seiko", "model": "Presage Cocktail", "price": 900,
                "currency": "RON", "category": "wrist"}),
          open(os.path.join(d, "2.json"), "w"))

# 3. a smartwatch -> connectivity/compatibility missing, but both are action=fix
json.dump(snap(3, 1943, "Garmin Fenix 7X Solar 51mm",
               "Ceas in stare foarte buna, folosit un an, vine cu incarcator si cutie.",
               [param("brand", "garmin", "Garmin"), price_param(1700)], 3,
               {"id": "3", "brand": "Garmin", "model": "Fenix 7X Solar", "price": 1700,
                "currency": "RON", "category": "wrist"}),
          open(os.path.join(d, "3.json"), "w"))

# 4. an ad that is no longer fetchable -> counted, never silently dropped
json.dump({"_gone": True, "id": "4"}, open(os.path.join(d, "4.json"), "w"))

p = subprocess.run([sys.executable, os.path.join(ROOT, "harness/3ceasuri-import/eval/replay.py"),
                    "--snapshots", d, "--json"], capture_output=True, text=True)
check(p.returncode == 0, "replay exited %d: %s" % (p.returncode, p.stderr[:300]))
out = json.loads(p.stdout)

check(out["scored"] == 3, "scored should skip the gone ad, got %s" % out["scored"])
check(out["gone"] == 1, "a gone ad must be counted, got %s" % out["gone"])

# the headline number: only #2 STOPS, because only movement_missing is action=skip
check(out["blocking"] == 1,
      "exactly one of these three must be a would-be SKIP, got %s (%s)"
      % (out["blocking"], out["blocking_codes"]))
check(out["blocking_codes"].get("movement_missing") == 1,
      "the blocker must be movement_missing: %s" % out["blocking_codes"])

# the smartwatch's missing facets fire, but as action=fix -- they must NOT be
# counted as would-be skips, or the eval overstates the cost of the new rule
check(out["codes"].get("connectivity_missing") == 1, "smart facets must be reported: %s" % out["codes"])
check("connectivity_missing" not in out["blocking_codes"],
      "an action=fix reason must never be counted as a would-be skip")

# agreement is computed against the saved record
check(out["agreement"]["brand"] == [3, 3], "brand agreement: %s" % out["agreement"]["brand"])
check(out["agreement"]["price"] == [3, 3], "price agreement: %s" % out["agreement"]["price"])

# a model that IS in the ad text counts as reachable; one that is not is a photo read
check(out["agreement"]["model"][1] == 3, "every label with a model must be scored")
check(out["model_from_photo"] >= 1,
      "a model absent from the ad text must be counted as photo-identified, not an error")

# the gate the eval scores is the importer's own, not a copy
check(hasattr(olx_import, "confidence_review"),
      "the eval must score olx_import.confidence_review, which must exist")
_r = olx_import.confidence_review("classic", {"brand": "Seiko", "model": "X", "price": 1,
                                              "movement": None, "description": "x" * 50},
                                  ["a", "b"], {"Seiko": 1})
check(any(x["code"] == "movement_missing" and x["action"] == "skip" for x in _r),
      "confidence_review must be the real gate: %s" % _r)

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
