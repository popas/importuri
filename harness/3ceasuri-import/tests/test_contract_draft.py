#!/usr/bin/env python3
"""Offline tests for the seeded contract draft (no browser, no network)."""
import json, os, sys, tempfile

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import contract_draft, infer_fields

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

BASE = {"brand": "Apple", "condition": "good", "gender": "unisex",
        "price": 1150, "currency": "RON", "description": "Vand Apple Watch, stare buna.",
        "phone": "0722333444", "caseMat": "aluminium"}

# 1. the draft carries the whole contract, not just the open fields
d = contract_draft.build(BASE, "smart")
check(d["brand"] == "Apple" and d["price"] == 1150, "1: mapped params missing from the draft")
check(d["description"] == BASE["description"], "1: description must be pre-filled, never retyped")
check(d["phone"] == "0722333444", "1: phone must be pre-filled")
for f in infer_fields.SCHEMA_FIELDS:
    check(f in d, "1: draft is not a whole contract, missing %s" % f)

# 2. _todo names what the model must decide, and nothing it already has
check("model" in d["_todo"], "2: model must always be asked")
check("connectivity" in d["_todo"] and "compatibility" in d["_todo"],
      "2: smart facets must be asked")
check("brand" not in d["_todo"], "2: a field the baseline filled must not be asked")
check("movement" not in d["_todo"], "2: smart forces movement, it is not the model's call")

dc = contract_draft.build(BASE, "classic")
check("movement" in dc["_todo"], "2: classic must always ask movement (never default quartz)")
check("connectivity" not in dc["_todo"], "2: classic must not ask smart facets")

# 3. a field the baseline could not fill is asked; one it filled is not
check("gender" not in contract_draft.todo_fields(BASE, "smart"), "3: gender was known")
check("gender" in contract_draft.todo_fields({k: v for k, v in BASE.items() if k != "gender"},
                                             "smart"), "3: empty gender must be asked")

# 4. round-trip: write, edit as the model would, read back
path = os.path.join(tempfile.mkdtemp(), "olx-1.json")
contract_draft.write(path, d)
edited = json.load(open(path))
edited.update({"model": "Watch Series 9", "connectivity": "no_gsm",
               "compatibility": "ios", "is_wristwatch": True, "is_bulk_lot": False})
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(problems == [], "4: clean draft rejected: %s" % problems)
check("_todo" not in payload, "4: _todo must be stripped before the merge")
check(payload["model"] == "Watch Series 9", "4: edit lost")
check(payload["description"] == BASE["description"], "4: description lost on read")

# 5. clearing semantics survive -- a field the model BLANKS is cleared
edited["gender"] = None
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(problems == [], "5: blanking a field is legal: %s" % problems)
check(payload["gender"] is None, "5: a blanked field must stay null, not be restored")

# 6. an unanswered REQUIRED field is a problem, not a silent null
edited["model"] = None
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(any("model" in p for p in problems), "6: null model must be reported: %s" % problems)

# 7. nullable-by-design fields are never required
edited["model"] = "Watch Series 9"
edited["reference"] = None
edited["notes"] = None
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(problems == [], "7: reference/notes are legitimately null: %s" % problems)

# 8. an illegal enum is caught on read, by infer_fields.validate
edited["connectivity"] = "LTE"
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(any("connectivity" in p for p in problems), "8: illegal enum not caught: %s" % problems)

# 9. a key outside the contract is rejected (the `series` class of mistake)
edited["connectivity"] = "no_gsm"
edited["series"] = "Series 9"
json.dump(edited, open(path, "w"))
payload, problems = contract_draft.read(path, "smart")
check(any("series" in p for p in problems), "9: unknown key not rejected: %s" % problems)

# 10. a draft that was never written is a problem, not a crash
_missing, problems = contract_draft.read(os.path.join(tempfile.mkdtemp(), "nope.json"), "smart")
check(problems and "could not read" in problems[0], "10: a missing draft must be reported: %s" % problems)

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
