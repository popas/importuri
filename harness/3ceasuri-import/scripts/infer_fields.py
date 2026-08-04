#!/usr/bin/env python3
"""ONE structured LLM call that fills the whole Watch record from a post body.

Why this exists: the regex inference in import-post.py gets the easy fields right
and the hard ones wrong in the same way every time — `model` came back as the
post's entire first sentence on 4 of 5 imports on 2026-08-04, `reference` was
truncated at the first dot ("T125" for "T125.617.17.051.03"), and `description`
carried FB comment junk. Each of those cost a hand-fix after the import.

The fix is not more regexes. The post text is prose; the target is a Django model
with a fixed set of enums. So: hand the model the post and the DB structure, and
let it populate the structure in a single call. `SCHEMA` below mirrors
`watches/models.py` exactly — when a TextChoices class there changes, change it
here too (there is no import-time coupling; the Django app is a separate repo).

The call is deliberately ONE round trip per post. Splitting it per field, or
looping to "refine", is the token waste this replaces.

Falls back to `None` on any problem (no credentials, API error, refusal, bad
JSON) — import-post.py then keeps its regex inference, so a missing API key
degrades quality without breaking the import.
"""
import json
import os

MODEL = os.environ.get("INFER_MODEL", "claude-opus-5")
# Extraction, not reasoning: `low` keeps thinking (on by default on Opus 5) short.
EFFORT = os.environ.get("INFER_EFFORT", "low")
MAX_TOKENS = int(os.environ.get("INFER_MAX_TOKENS", "8000"))


def _n(schema):
    """Make a field nullable — the model must be able to say 'not stated'."""
    return {"anyOf": [schema, {"type": "null"}]}


_STR = {"type": "string"}


def _enum(*values):
    return {"type": "string", "enum": list(values)}


# Mirrors watches/models.py TextChoices. Keep in sync by hand.
FIELDS = {
    "brand":        _n(_STR),
    "model":        _n(_STR),
    "reference":    _n(_STR),
    "price":        _n({"type": "number"}),
    "currency":     _n(_enum("RON", "EUR")),
    "priceNote":    _n(_STR),
    "condition":    _n(_enum("new", "excellent", "good", "fair", "broken")),
    "movement":     _n(_enum("automatic", "manual", "quartz", "smart")),
    "gender":       _n(_enum("women", "men", "unisex", "kids")),
    "style":        _n(_enum("sport", "dress", "diver", "chronograph", "smart")),
    "caseMat":      _n(_enum("titanium", "carbon", "aluminium", "steel", "gold",
                             "silver", "plastic", "ceramic", "other")),
    "braceletMat":  _n(_enum("titanium", "carbon", "aluminium", "steel", "gold",
                             "silver", "plastic", "rubber", "leather", "nylon", "other")),
    "displayMat":   _n(_enum("sapphire", "mineral", "acrylic", "plastic", "other")),
    "displayColor": _n(_enum("black", "white", "silver", "gold", "other")),
    "displayType":  _n(_enum("digital", "analog", "analog_digital", "smart", "none")),
    "displaySize":  _n(_enum("small", "medium", "large")),
    "waterRes":     _n(_enum("water_resistant_yes", "water_resistant_no")),
    "diameter":     _n({"type": "number"}),
    "year":         _n({"type": "integer"}),
    "phone":        _n(_STR),
    "location":     _n(_STR),
    "seller":       _n(_STR),
    "description":  _n(_STR),
    # Judgement calls the regex filters get wrong: wall clocks that dodge the
    # keyword list, and "both for 400 lei" bundles. Both cost imports on 2026-08-03/04.
    "is_wristwatch": {"type": "boolean"},
    "is_bulk_lot":   {"type": "boolean"},
    "notes":        _n(_STR),
}

SCHEMA = {
    "type": "object",
    "properties": FIELDS,
    "required": list(FIELDS),
    "additionalProperties": False,
}

PROMPT = """Acesta este textul unui anunț de vânzare de ceasuri de pe Facebook (română, uneori engleză).
Populează structura bazei noastre de date pe baza lui.

Reguli:
- Deduce fiecare câmp DOAR din text. Ce nu e afirmat sau clar implicat rămâne null.
  Nu ghici mecanismul, materialul sau anul „pentru că așa e de obicei".
- `model`: DOAR numele modelului, scurt, fără brand și fără propoziții.
  „Vând Oris Divers Sixty-Five Date 40mm, stare buna" -> „Divers Sixty-Five Date".
  Dacă anunțul nu dă un nume de model, folosește caracteristica definitorie
  („Automatic 21 Jewels", „Vintage anii 1970-1980"), tot scurt.
- `reference`: numărul de referință COMPLET, cu tot cu puncte/liniuțe (ex. T125.617.17.051.03).
- `description`: textul anunțului curățat — fără antetul Facebook, fără numele
  autorului și timestamp, fără „See more"/„See translation", fără comentarii,
  fără caractere de timestamp ofuscat. Păstrează formatarea pe linii a vânzătorului.
- `price`: prețul cerut pentru ACEST ceas. `priceNote` = „negociabil", „fix", etc.
- `year`: un singur an ca număr întreg. Dacă anunțul dă doar un deceniu, lasă null.
- `is_wristwatch`: false pentru ceas de perete/șemineu/pendulă/deșteptător sau orice
  nu se poartă pe mână.
- `is_bulk_lot`: true dacă un singur preț acoperă mai multe ceasuri.
- `notes`: o propoziție scurtă doar dacă e ceva ce operatorul trebuie să știe
  (replică suspectată, preț contradictoriu, anunț neclar). Altfel null.

Branduri deja existente în baza de date — folosește exact aceste nume când se potrivesc,
altfel scrie numele brandului așa cum apare în anunț:
{brands}

Textul anunțului:
---
{text}
---"""


def infer(text, brands=(), client=None):
    """Return a dict of inferred fields, or None if inference is unavailable.

    `client` is injectable so the offline tests can exercise this without network.
    """
    if os.environ.get("NO_LLM") == "1":
        return None
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        prompt = PROMPT.format(brands=", ".join(sorted(brands)) or "(niciunul)",
                               text=(text or "").strip())
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            # SDK 0.76 in the browser-use env has no typed `output_config`; the
            # server does. extra_body forwards it unchanged.
            extra_body={"output_config": {
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": SCHEMA},
            }},
        )
        # A refusal returns HTTP 200 with empty/partial content — check before reading.
        if getattr(resp, "stop_reason", None) == "refusal":
            return None
        raw = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        if not raw:
            return None
        data = json.loads(raw)
    except Exception:
        return None
    # Drop nulls so the caller can merge over its regex baseline without erasing it.
    return {k: v for k, v in data.items() if v is not None}
