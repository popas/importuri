#!/usr/bin/env python3
# =============================================================================
# snapshot.py — cache historical OLX ads so the replay eval can run offline.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   LIMIT=50 browser-use < .../eval/snapshot.py
#
# This is the ONLY part of the eval that needs Chrome, and it is why: OLX answers
# a plain GET with 403, so every read has to be a fetch() from a page already on
# www.olx.ro (Global Constraint 6). Everything after this is offline.
#
# Env:
#   LIMIT    how many of the most recent OLX imports to try (default 50)
#   OUT      snapshot directory (default eval/.snapshots)
#   HISTORY  history.jsonl path
#
# Many historical ads are gone — that is expected and recorded, not an error. The
# replay reports how many could not be fetched so the sample size is never implied.
# =============================================================================
import os
import json
import sys

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import olx_api

LIMIT = int(os.environ.get("LIMIT", "50"))
OUT = os.environ.get("OUT", os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/eval/.snapshots"))
HISTORY = os.environ.get("HISTORY", os.path.join(PROJECT_ROOT, "history.jsonl"))


def emit(tag, obj):
    print(tag + ": " + json.dumps(obj, ensure_ascii=False))


rows = []
with open(HISTORY) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("source") == "olx" and r.get("event") == "import" and r.get("id"):
            rows.append(r)

rows = rows[-LIMIT:]
os.makedirs(OUT, exist_ok=True)

bu = olx_api.bind(globals())
olx_api.ensure_tab(bu, olx_api.CATEGORY_URL[olx_api.CATEGORY_WATCHES])

got, gone, cached = 0, 0, 0
for r in rows:
    path = os.path.join(OUT, "%s.json" % r["id"])
    if os.path.exists(path):
        cached += 1
        continue
    ad = olx_api.offer(bu, r["id"])
    if not ad:
        gone += 1
        with open(path, "w") as f:
            json.dump({"_gone": True, "id": r["id"]}, f)
        continue
    got += 1
    with open(path, "w") as f:
        # The label is stored alongside the ad, so the replay needs only this dir.
        json.dump({"ad": ad, "label": r}, f, ensure_ascii=False)

emit("SNAPSHOT", {"asked": len(rows), "fetched": got, "gone": gone,
                  "already_cached": cached, "out": OUT})
