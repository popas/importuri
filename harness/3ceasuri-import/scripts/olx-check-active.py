#!/usr/bin/env python3
# =============================================================================
# olx-check-active.py — which of the site's active OLX listings are gone from OLX,
# and (APPLY=1, once the Django endpoint is deployed) end them on 3ceasuri.ro.
# The logic lives in active_check.py; the endpoint contract is
# docs/handover/2026-10-04-deactivate-gone-olx-listings.md.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`. It needs a
# signed-in 3ceasuri.ro/admin tab and opens/uses a www.olx.ro tab.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   SAMPLE=60 SEED=1 browser-use < harness/3ceasuri-import/scripts/olx-check-active.py
#   browser-use < .../olx-check-active.py                 # every listing, ~40 min
#   APPLY=dry browser-use < .../olx-check-active.py       # + server-side dry run
#   APPLY=1 browser-use < .../olx-check-active.py         # + end the gone ones
#
# Read-only unless APPLY is set. Markers: ACTIVE_IDS: PROGRESS: STATS: GONE:
# UNKNOWN: APPLY: APPLY_UNAVAILABLE: APPLY_SKIPPED: REPORT: ERROR:
# A full sweep outlives a 10-minute shell call: run it in the background.
# =============================================================================
import os, sys

# browser-use runs this from stdin, so __file__ is not this script: take PROJECT_ROOT,
# else the nearest directory at or above the cwd that holds the harness.
PROJECT_ROOT = os.environ.get("PROJECT_ROOT") or os.getcwd()
while not os.path.isdir(os.path.join(PROJECT_ROOT, "harness/3ceasuri-import")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
os.environ["PROJECT_ROOT"] = PROJECT_ROOT
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import active_check

active_check.run(globals())
