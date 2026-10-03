#!/usr/bin/env python3
# =============================================================================
# olx-import-smartwatch.py — one-shot importer for a single OLX smartwatch ad
# (category 1943, smartwatch-uri). The flow lives in olx_import.py; this file
# only picks the profile, so the classic and smart paths cannot drift apart.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   AD_ID=307673714 browser-use < .../olx-import-smartwatch.py            # pass 1
#   AD_ID=307673714 CONFIRM=1 OVERRIDES='{...}' browser-use < .../olx-import-smartwatch.py
#
# Env and marker lines: see olx_import.py.
# =============================================================================
import os, sys

# browser-use runs this from stdin, so __file__ is not this script: take PROJECT_ROOT,
# else the nearest directory at or above the cwd that holds the harness.
PROJECT_ROOT = os.environ.get("PROJECT_ROOT") or os.getcwd()
while not os.path.isdir(os.path.join(PROJECT_ROOT, "harness/3ceasuri-import")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import olx_import

olx_import.run("smart", globals())
