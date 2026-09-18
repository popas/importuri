#!/usr/bin/env python3
"""The seeded contract draft — the contract as a file the model edits in place.

Before this, pass 2 took the filled contract through OVERRIDES='{…}', a single-quoted
shell variable. Two things went wrong with that and neither was the model's fault:
Romanian ad text contains apostrophes ("anii '70"), which terminate the quoting; and
because a field omitted from the answer is CLEARED, the model had to retype the entire
seller description to avoid deleting it.

So pass 1 now writes the WHOLE contract to disk, pre-filled with everything the
deterministic baseline knows, with the open fields null and named in `_todo`. The model
edits those and nothing else.

The clearing semantics are unchanged and deliberately so: the file IS the contract, so a
field the model blanks is still cleared. What disappears is the retyping, not the rule —
two half-authoritative sources is how fields go silently wrong (see infer_fields).
"""

import json
import os

import infer_fields

DRAFT_SUBDIR = "harness/3ceasuri-import/.contracts"

# Null is a legitimate answer for these, so `read` never demands a value.
NULLABLE = {"reference", "year", "notes", "priceNote", "seller", "phone", "location"}


def draft_path(project_root, ad_id):
    return os.path.join(project_root, DRAFT_SUBDIR, "olx-%s.json" % ad_id)


def todo_fields(data, profile):
    """The fields this ad's model must decide. Deterministic — the script chooses.

    ALWAYS_ASK is asked even when the baseline guessed a value, because copying a
    guess is how `movement` silently became quartz on a 1970s Poljot. ASK_IF_EMPTY is
    asked only when the baseline came up empty. A field the profile FORCES (smart:
    movement/style/displayType/category) appears in neither list — it is the
    category's own answer, and asking would invite a routing mistake.
    """
    todo = list(infer_fields.ALWAYS_ASK[profile])
    for f in infer_fields.ASK_IF_EMPTY:
        if f not in todo and data.get(f) in (None, ""):
            todo.append(f)
    return todo


def build(data, profile):
    """A complete contract, pre-filled, with `_todo` naming what is left to decide."""
    draft = {f: data.get(f) for f in infer_fields.SCHEMA_FIELDS}
    draft["_todo"] = todo_fields(data, profile)
    return draft


def write(path, draft):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(draft, f, ensure_ascii=False, indent=1, sort_keys=True)


def read(path, profile):
    """(payload, problems). `problems` empty means usable; `_todo` is stripped."""
    try:
        with open(path) as f:
            payload = json.load(f)
    except Exception as e:
        return {}, ["could not read the contract draft %s: %s" % (path, e)]
    if not isinstance(payload, dict):
        return {}, ["the contract draft must be a JSON object"]

    payload.pop("_todo", None)
    problems = infer_fields.validate(payload)
    for f in infer_fields.REQUIRED_BY_PROFILE[profile]:
        if payload.get(f) is None:
            problems.append("%s is required and was left null in the draft" % f)
    return payload, problems
