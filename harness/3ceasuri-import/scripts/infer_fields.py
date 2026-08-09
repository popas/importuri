#!/usr/bin/env python3
"""The extraction contract: the DB structure, the prompt, and a validator.

There is NO API call here and there must never be one. The model doing the
inference is the agent already driving the session — it reads the post text and
fills the structure in its own context. This module exists so that inference
stops being improvised.

Before this, extraction was in two halves and neither was reproducible in the way
that mattered: the regexes in import-post.py were deterministic but reliably
wrong on the same fields every time (`model` = the whole first sentence,
`reference` truncated at the first dot, `movement` defaulted to quartz), and the
after-the-fact fixes were the agent deciding on the spot with no written rules —
on 2026-08-04 the same class of decision was made four times with nothing
guaranteeing tomorrow's answer would match today's.

So: `SCHEMA` mirrors watches/models.py TextChoices exactly, `build_prompt()`
renders the fixed instructions plus the post, and `validate()` checks a filled
payload against the enums. The prompt makes the decision repeatable; the
validator makes a wrong one loud instead of letting the admin form drop it.

Flow per watch:
    import-post.py emits EXTRACT_PROMPT: with the post text and this contract
      -> the agent fills it and re-runs with OVERRIDES='{...}'
      -> validate() rejects anything that isn't a legal DB value
"""

# ---------------------------------------------------------------------------
# The structure. Mirrors watches/models.py TextChoices — keep in sync by hand
# (the Django app is a separate repo, so there is no import-time coupling).
# ---------------------------------------------------------------------------
ENUMS = {
    "category":     ["wrist", "wall"],
    "currency":     ["RON", "EUR"],
    "condition":    ["new", "excellent", "good", "fair", "broken"],
    "movement":     ["automatic", "manual", "quartz", "smart"],
    "gender":       ["women", "men", "unisex", "kids"],
    "style":        ["sport", "dress", "diver", "chronograph", "smart"],
    "caseMat":      ["titanium", "carbon", "aluminium", "steel", "gold", "silver",
                     "plastic", "ceramic", "wood", "other"],
    "braceletMat":  ["titanium", "carbon", "aluminium", "steel", "gold", "silver",
                     "plastic", "rubber", "leather", "nylon", "other"],
    "displayMat":   ["sapphire", "mineral", "acrylic", "plastic", "other"],
    "displayColor": ["black", "white", "silver", "gold", "other"],
    "displayType":  ["digital", "analog", "analog_digital", "smart", "none"],
    "displaySize":  ["small", "medium", "large"],
    "waterRes":     ["water_resistant_yes", "water_resistant_no"],
    "connectivity": ["gsm", "no_gsm"],
    "compatibility": ["ios", "android", "both"],
}

NUMERIC = {"price": float, "diameter": float, "year": int}
TEXT = ["brand", "model", "series", "reference", "priceNote", "phone", "location",
        "seller", "description"]
FLAGS = ["is_wristwatch", "is_bulk_lot"]

SCHEMA_FIELDS = TEXT + list(NUMERIC) + list(ENUMS) + FLAGS + ["notes"]

PROMPT = """# Extraction contract — fill this from the post text below

Populate the 3ceasuri DB record. Answer with ONE JSON object and nothing else.
Everything not stated or clearly implied in the text stays `null`. Do NOT guess a
movement, material, or year because it is "usually" that.

## Rules that exist because they were broken before

- `model` — the model NAME only. Short. No brand, never a sentence.
  "Vand Oris Divers Sixty-Five Date 40mm, stare buna" -> "Divers Sixty-Five Date".
  **The ad often does not name the model — LOOK AT THE PHOTOS.** Dial layout, bezel,
  handset, bracelet and caseback identify most watches: a Fossil ladies' watch with a
  crystal bezel, Roman numerals and a 4:30 date is a "Jacqueline". Read the caseback
  if a photo shows it — that is where the reference lives.
  The photos are saved to disk and their paths are in `EXTRACT_PROMPT.photos` — read
  them from there, never from a Facebook URL (those are signed and expire mid-session).
  Read ONE photo by default — the dial answers the model question on its own. Open a
  second only when you actually need the caseback (for `reference`). Reading all four
  "to be safe" is the expensive habit, not the reading itself; see references/post-extraction.md.
  Still nothing identifiable? Use the defining trait, short and factual:
  "Automatic 21 Jewels", "Vintage anii 1970-1980".
  **Never a filler noun.** "Original", "Clasic", "Ceas", "Dama" are not models — if
  that is all you have, stop and say so instead of inventing one.
- `reference` — the COMPLETE reference, dots and dashes included
  (T125.617.17.051.03, never T125). Only from text you can actually READ — the ad, or a
  legible caseback/papers photo. **Never derive a reference from the design**: a dial
  match identifies a model family, not the exact variant, and a wrong reference on a
  public listing is worse than an empty field.
- A model identified from photos rather than the ad is OUR classification, not the
  seller's claim. Put it in `model`, say so in `notes`, and leave `description` as the
  seller wrote it — do not add the model name into their text.
- `movement` — infer it, don't just copy it. The ad states it only half the time, but
  the model usually settles it (a Fossil Jacqueline is quartz; a Poljot from the '70s
  is hand-wound), and so does the dial (a running-seconds subdial, a smooth sweep in a
  video, "21 jewels" on the dial). Say in `notes` when you inferred rather than read
  it. Only null when brand, model, era and photos genuinely leave it open — that stops
  for review, which beats the harness silently defaulting to `quartz` (it mislabelled a
  1970s Poljot that way).
- `description` — the seller's text, cleaned: no FB header, no author name or
  timestamp, no "See more"/"See translation", no comments, no obfuscated timestamp
  characters. Keep the seller's line breaks.
- `year` — ONE year as an integer. `id_year` is a numeric input, so a decade range
  is silently dropped: if the post only says "anii '70", leave this null and put the
  decade in `model` instead.
- `price` — for THIS watch. `priceNote` = "negociabil", "fix", etc.
- `category` — `wrist` for anything worn on the wrist, `wall` for a clock hung on a
  wall (pendulum, cuckoo, kitchen, station, cartel). Leave null only when the post
  genuinely leaves it open; a null on a non-wristwatch stops the import for review.
- `is_wristwatch` — false for wall/mantel/pendulum/alarm clocks or anything not worn
  on the wrist. A post with `is_wristwatch: false` AND `category: "wall"` is now
  IMPORTED, not skipped — wall clocks are listed on the site. Mantel, pocket, table
  and alarm clocks are still out: mark them `is_wristwatch: false` and leave
  `category` null so they skip.
- Wall clocks are usually unbranded. When no maker is named on the dial or in the ad,
  set `brand` to `Fără marcă` — never invent a maker, and never put "Ceas de perete"
  in the brand field (it is the category, not the brand). `model` then carries the
  defining trait: "Pendulă cu cuc anii '70", "Ceas de perete quartz 30 cm".
  Vintage German/Austrian makers (Junghans, Kienzle, Gustav Becker, Schatz) are real
  brands — read the dial and the movement plate before falling back to `Fără marcă`.
- `caseMat` for a wall clock is usually `wood`; `diameter` is stored in MILLIMETRES,
  so a 30 cm wall clock is `300`.
- Smartwatches (`movement` = smart) fill three extra fields; for everything else
  all three stay null. `series` — the normalized model line, short: "Series 9",
  "SE 2", "Ultra 2", "Galaxy Watch 7", "Venu 3" (no brand, no case size).
  `connectivity` — gsm when the watch can take calls without the phone (ad or
  photos say "LTE", "Cellular", "4G", "eSIM"; on Apple Watch the cellular models
  have a red ring or dot on the crown), no_gsm when it is GPS/Bluetooth only;
  null when the post genuinely leaves it open. `compatibility` — follows from
  the model, not the ad: Apple Watch = ios; Galaxy Watch 4 and newer = android;
  Garmin, Amazfit, Huawei, Xiaomi = both.
- `is_bulk_lot` — true when one price covers several watches.
- `notes` — one short sentence ONLY if the operator must know something (suspected
  replica, contradictory price, unclear post). Otherwise null.

## Fields

{fields}

## Known brands — use these exact spellings when they match, otherwise write the
brand as the post spells it

{brands}

## Post text

{text}
"""


def _field_lines():
    out = []
    for f in TEXT:
        out.append("- `%s`: text or null" % f)
    for f, t in NUMERIC.items():
        out.append("- `%s`: %s or null" % (f, "integer" if t is int else "number"))
    for f, vals in ENUMS.items():
        out.append("- `%s`: one of %s, or null" % (f, " | ".join(vals)))
    for f in FLAGS:
        out.append("- `%s`: true or false (never null)" % f)
    out.append("- `notes`: text or null")
    return "\n".join(out)


def build_prompt(text, brands=()):
    return PROMPT.format(fields=_field_lines(),
                         brands=", ".join(sorted(brands)) or "(none)",
                         text=(text or "").strip())


def validate(payload):
    """Return a list of problems with a filled payload. Empty list = usable.

    This is the deterministic half: whatever the inference decided, an illegal
    enum value or a decade in `year` is caught here rather than being silently
    dropped by the admin form (which is how the Poljot year went missing).
    """
    problems = []
    for key, value in (payload or {}).items():
        if value is None:
            continue
        if key in ENUMS and value not in ENUMS[key]:
            problems.append("%s=%r is not one of %s" % (key, value, "|".join(ENUMS[key])))
        elif key in NUMERIC:
            try:
                NUMERIC[key](value)
            except (TypeError, ValueError):
                problems.append("%s=%r is not a %s" % (key, value, NUMERIC[key].__name__))
        elif key in FLAGS and not isinstance(value, bool):
            problems.append("%s=%r is not a boolean" % (key, value))
        elif key not in SCHEMA_FIELDS and key not in ("force",):
            problems.append("%s is not a field in the contract" % key)
    return problems
