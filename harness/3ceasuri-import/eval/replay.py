#!/usr/bin/env python3
"""Offline replay of historical OLX ads through the deterministic path.

Run with python3 — no browser, no network:
    python3 harness/3ceasuri-import/eval/replay.py --limit 50

It answers the question §6 left open when it made `REVIEW:` non-overridable: **how
often would the gate fire on watches that were, in fact, imported?** Every one of
those is a watch the new rule converts into a skip, and nothing in `history.jsonl`
recorded the rate. Measure it before trusting a long unattended run.

It scores the SAME gate the importer runs — `olx_import.confidence_review` — not a
copy of it, so the two cannot drift.

What it can and cannot check, honestly:

- `history.jsonl` records brand, model, price, currency, images and category. Those
  can be compared against what the deterministic baseline produces.
- It does NOT record `movement`, `connectivity` or `compatibility`, so per-field
  agreement on those is not computable from this data at all. The gate rate for them
  still is, and that is the number that matters here.
- A `model` that does not appear in the ad text was identified from a PHOTO. Those
  are counted separately and must not be read as text-path errors — recovering them
  is vision work the replay cannot do.

Snapshots come from `snapshot.py` (the one browser step). Ads that are gone are
counted, never silently dropped.
"""

import argparse
import collections
import json
import os
import re
import sys

ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))

import olx_api
import admin_import
import price_sanity
import infer_fields
import contract_draft
import olx_import

SNAPSHOTS = os.path.join(ROOT, "harness/3ceasuri-import/eval/.snapshots")
HARNESS = os.path.join(ROOT, "harness/3ceasuri-import/scripts/import-watch.js")


def norm_model(s):
    """Compare models the way a human would: case, spacing and punctuation are noise."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def baseline(ad, profile, brand_ids):
    """The deterministic half of pass 1, with no browser and no contract.

    This mirrors olx_import.run()'s section 2. It is deliberately the *baseline
    only*: what the scripts know before the model answers anything. That is exactly
    what the gate sees when the model declines to fill a field.
    """
    conf = olx_import.PROFILES[profile]
    title = ad.get("title") or ""
    description = olx_api.clean_description(ad.get("description"))
    text = (title + "\n\n" + description).strip()

    brand_label = olx_api.brand_param(ad)
    brand = (admin_import.match_brand(brand_label, brand_ids) if brand_label else None) \
            or admin_import.match_brand(title, brand_ids)
    if not brand and conf["brand_from_description"]:
        brand = admin_import.match_brand(description, brand_ids)
    brand = brand or (brand_label or None)

    data = dict(olx_api.map_params(ad))
    data.update(conf["forced"])
    if brand:
        data["brand"] = brand
    data["description"] = description

    m = re.search(r"(\d{2}(?:[.,]\d)?)\s*mm", text, re.I)
    if m:
        data["diameter"] = float(m.group(1).replace(",", "."))
    if conf["regex_baseline"]:
        m = re.search(r"(?:ref(?:erin[țt][ăa])?\.?\s*(?:nr\.?)?\s*[:\-]?\s*(?:este\s*)?)"
                      r"([A-Z0-9][A-Z0-9\-\./ ]{2,20}[A-Z0-9])", text, re.I)
        if m and any(c.isdigit() for c in m.group(1)):
            data["reference"] = m.group(1).strip(" .")
        m = re.search(r"\b((?:19|20)\d{2})\b", text)
        if m:
            data["year"] = int(m.group(1))
        low = text.lower()
        for pat, val in ((r"automat|automatic", "automatic"),
                         (r"quartz|baterie", "quartz"),
                         (r"mecanic|manual|cheiț|cheit|remontoar", "manual")):
            if re.search(pat, low):
                data["movement"] = val
                break
    return data, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--snapshots", default=SNAPSHOTS)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not os.path.isdir(args.snapshots):
        print("No snapshots at %s.\nRun the one browser step first:\n"
              "  LIMIT=%d browser-use < harness/3ceasuri-import/eval/snapshot.py"
              % (args.snapshots, args.limit))
        return 1

    try:
        brand_ids = admin_import.load_brand_ids(HARNESS)
    except Exception as e:
        print("could not load BRAND_IDS from the harness: %s" % e)
        return 1

    files = sorted(f for f in os.listdir(args.snapshots) if f.endswith(".json"))[:args.limit]
    gone = 0
    scored = 0
    cheap_now = 0
    gate_fired = 0
    blocking = 0                                  # at least one action=skip reason
    codes = collections.Counter()
    blocking_codes = collections.Counter()
    agree = collections.Counter()
    total = collections.Counter()
    model_from_photo = 0

    for name in files:
        with open(os.path.join(args.snapshots, name)) as f:
            snap = json.load(f)
        if snap.get("_gone"):
            gone += 1
            continue
        ad, label = snap["ad"], snap["label"]
        profile = "smart" if (ad.get("category") or {}).get("id") == 1943 else "classic"
        data, text = baseline(ad, profile, brand_ids)
        images = olx_api.photo_urls(ad)
        scored += 1

        # 1. would the price floor drop it today? (invariant 1 — nothing waives this)
        if price_sanity.implausible_price(data.get("price"), data.get("currency"),
                                          olx_api.brand_param(ad) or "", text):
            cheap_now += 1

        # 2. what would the gate say, on the BASELINE alone?
        reasons = olx_import.confidence_review(profile, data, images, brand_ids)
        if reasons:
            gate_fired += 1
        for r in reasons:
            codes[r["code"]] += 1
        stop = [r for r in reasons if r["action"] == "skip"]
        if stop:
            blocking += 1
            for r in stop:
                blocking_codes[r["code"]] += 1

        # 3. per-field agreement against what was actually saved
        for field in ("brand", "price", "currency", "category"):
            if label.get(field) is None:
                continue
            total[field] += 1
            if str(data.get(field)) == str(label.get(field)):
                agree[field] += 1
        if label.get("model"):
            total["model"] += 1
            if norm_model(label["model"]) in norm_model(text):
                agree["model"] += 1     # the text carried it; the baseline could reach it
            else:
                model_from_photo += 1

    if args.json:
        print(json.dumps({
            "scored": scored, "gone": gone, "cheap_now": cheap_now,
            "gate_fired": gate_fired, "blocking": blocking,
            "codes": dict(codes), "blocking_codes": dict(blocking_codes),
            "agreement": {k: [agree[k], total[k]] for k in total},
            "model_from_photo": model_from_photo}, indent=1))
        return 0

    pct = lambda n, d: ("%.1f%%" % (100.0 * n / d)) if d else "n/a"

    print("OLX replay — %d ads scored, %d no longer fetchable" % (scored, gone))
    if not scored:
        print("\nNothing to score. Run snapshot.py first.")
        return 0

    print("\n-- the number §6 left unknown ------------------------------------")
    print("  REVIEW: fires at all          %4d  (%s)" % (gate_fired, pct(gate_fired, scored)))
    print("  ...of which STOP the watch    %4d  (%s)  <- would become skips"
          % (blocking, pct(blocking, scored)))
    print("\n  Every one of these was imported for real, so this is the rate at which")
    print("  the non-overridable gate converts an importable watch into a skip --")
    print("  on the BASELINE alone, i.e. the worst case where the model answers nothing.")

    print("\n  by blocking code:")
    for code, n in blocking_codes.most_common():
        print("    %-22s %4d  (%s)" % (code, n, pct(n, scored)))
    print("\n  all codes (including action=fix, which does NOT stop the watch):")
    for code, n in codes.most_common():
        print("    %-22s %4d  (%s)" % (code, n, pct(n, scored)))

    print("\n-- per-field agreement with what was saved -----------------------")
    for field in ("brand", "price", "currency", "category", "model"):
        if total[field]:
            print("  %-10s %4d/%-4d  (%s)" % (field, agree[field], total[field],
                                              pct(agree[field], total[field])))
    print("  %d model labels do not appear in the ad text -- those were read off a"
          % model_from_photo)
    print("  photo, and must NOT be counted as text-path errors.")
    print("\n  movement / connectivity / compatibility are not in history.jsonl,")
    print("  so agreement on them is not computable from this data.")

    print("\n-- price floors --------------------------------------------------")
    print("  %d of %d would be dropped as suspiciously cheap today (%s)."
          % (cheap_now, scored, pct(cheap_now, scored)))
    print("  Anything above zero is worth reading one by one: these were imported")
    print("  before the floors existed, or the floors have drifted too high.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
