#!/usr/bin/env python3
# =============================================================================
# olx-import-watch.py — one-shot importer for a single OLX classic-watch ad
# (category 1677, moda/ceasuri). The flow lives in olx_import.py; this file only
# picks the profile, so the classic and smart paths cannot drift apart.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   AD_ID=266008409 browser-use < .../olx-import-watch.py                 # pass 1
#   AD_ID=266008409 CONFIRM=1 OVERRIDES='{...}' browser-use < .../olx-import-watch.py
#
# Env and marker lines: see olx_import.py.
# =============================================================================
import os, sys

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import olx_import

olx_import.run("classic", globals())
