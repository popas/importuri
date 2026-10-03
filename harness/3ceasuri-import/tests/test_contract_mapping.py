#!/usr/bin/env python3
"""The two writers must write the same fields.

import-watch.js (the DOM path) and site_api.CONTRACT_TO_MODEL (import-json) each map
the harness contract onto Watch fields. A field added to one and not the other would
go missing on the site whenever the other path runs — the description bug in
reverse — so it fails here, offline, instead."""
import os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SCRIPTS = os.path.join(ROOT, "harness/3ceasuri-import/scripts")
sys.path.insert(0, SCRIPTS)
import site_api

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


src = open(os.path.join(SCRIPTS, "import-watch.js")).read()

# Documented exceptions: ids the JS sets that are not a contract key -> field pair.
EXCEPTIONS = {
    "model_slug": "server-computed: Watch.save() recomputes it on every save",
    "description": "set from professionalDesc (the contract's description, trimmed)",
}

js = {}
# set('id_<field>', data.<key>) — also with a default after the key: `|| 'good'`
for field, key in re.findall(r"\bset\('id_(\w+)',\s*data\.(\w+)", src):
    check(key not in js, "the JS writes data.%s twice" % key)
    js[key] = field
# setAny(['id_<field>', 'id_facebook_<old>'], data.<key>) — the old ids are fallbacks
for ids, key in re.findall(r"\bsetAny\(\[([^\]]*)\],\s*data\.(\w+)\)", src):
    names = re.findall(r"'id_(\w+)'", ids)
    current = [n for n in names if not n.startswith("facebook_")]
    check(len(current) == 1, "setAny for data.%s must name one current id, got %s" % (key, names))
    check(key not in js, "the JS writes data.%s twice" % key)
    if current:
        js[key] = current[0]

# Every id the JS sets is either a parsed pair or a documented exception.
for field in re.findall(r"\bset\('id_(\w+)'", src):
    check(field in js.values() or field in EXCEPTIONS,
          "import-watch.js sets id_%s, which is neither a data.<key> pair nor a documented "
          "exception" % field)
check("model_slug" not in site_api.CONTRACT_TO_MODEL.values(),
      "model_slug is server-computed and must not be sent")

# The description exception, pinned: it IS the contract's description, trimmed.
check(re.search(r"\bset\('id_description',\s*professionalDesc\)", src),
      "id_description is no longer set from professionalDesc - revisit the exception")
check("data.description.trim()" in src,
      "professionalDesc no longer comes from data.description - revisit the exception")
js["description"] = "description"

for key in sorted(set(js) | set(site_api.CONTRACT_TO_MODEL)):
    check(js.get(key) == site_api.CONTRACT_TO_MODEL.get(key),
          "%s: import-watch.js writes %r, CONTRACT_TO_MODEL maps %r"
          % (key, js.get(key), site_api.CONTRACT_TO_MODEL.get(key)))

# the parser itself works on the shapes it must accept
check(js.get("condition") == "condition", "the parser must accept `data.condition || 'good'`")
check(js.get("movement") == "movement", "the parser must accept `data.movement || 'quartz'`")
check(js.get("externalId") == "external_listing_id", "setAny must map to the current id")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
