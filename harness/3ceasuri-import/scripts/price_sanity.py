#!/usr/bin/env python3
"""Is this price plausible for this watch, or is the listing a fake?

User directive 2026-08-09: **never import a suspiciously cheap listing — most of
them are fakes.** A replica seldom says "replica"; what gives it away is the
price. A "Rolex Datejust" at 900 lei and an "Apple Watch Series 11" at 160 lei are
not bargains, they are counterfeits or outright scams, and either one on the site
costs more trust than a missed listing costs inventory.

So this is a DROP rule, not a review flag: discovery drops these candidates and
the importers refuse them outright, before any DB write.

The floors below are the lowest price at which a GENUINE, used, even damaged
example plausibly trades in Romania — deliberately generous, so the rule catches
the obvious fakes rather than shaving the bottom of the honest market. They are
estimates and they are meant to be tuned: this table is the single place to do it,
and every script reads it from here.

Nothing here is a judgement about the seller. It is arithmetic about the price.
"""

import re

# Rough conversion, only ever used to compare a EUR price against a RON floor.
# Precision does not matter for an order-of-magnitude test.
EUR_TO_RON = 5.0

# Brand -> the lowest plausible RON price for a genuine example in any condition.
BRAND_FLOOR_RON = {
    "patek philippe": 50000,
    "audemars piguet": 40000,
    "vacheron constantin": 30000,
    "richard mille": 50000,
    "a. lange": 30000,
    "hublot": 8000,
    "rolex": 6000,
    "panerai": 5000,
    "iwc": 4000,
    "jaeger-lecoultre": 3000,
    "breitling": 2500,
    "cartier": 2500,
    "tudor": 2500,
    "chopard": 2500,
    "zenith": 2000,
    "grand seiko": 2500,
    "omega": 1500,
    "tag heuer": 1200,
    "longines": 700,
    "montblanc": 1200,
    "bvlgari": 2500,
    "gucci": 500,
}

# Model families whose floor does not follow from the brand alone: an Apple Watch
# Ultra and an Apple Watch SE are both "Apple". Matched against title + body, most
# specific first — the first hit wins.
FAMILY_FLOOR_RON = [
    (r"watch\s*ultra|ultra\s*[23]\b", 1200, "Apple/Samsung Watch Ultra"),
    (r"apple\s*watch.*\bseries\s*(9|10|11)\b|\bseries\s*(9|10|11)\b.*apple\s*watch", 700,
     "Apple Watch Series 9-11"),
    (r"apple\s*watch.*\bseries\s*([6-8])\b|\bseries\s*([6-8])\b.*apple\s*watch", 400,
     "Apple Watch Series 6-8"),
    (r"apple\s*watch.*\bse\s*2?\b", 250, "Apple Watch SE"),
    (r"apple\s*watch", 200, "Apple Watch"),
    (r"galaxy\s*watch\s*[5-8]\b", 350, "Galaxy Watch 5-8"),
    (r"\bfenix\b|\bepix\b|\benduro\b|\bmarq\b", 700, "Garmin Fenix/Epix/Enduro/MARQ"),
]


# A watch advertised as NEW or SEALED is a different market from a used one, and the
# floors above cannot see the difference: they have to stay low enough for a
# scratched vintage piece, which leaves them useless against "ceas tissot automatic
# sigilat, 400 lei" (seller 1380706487, six such ads on 2026-08-12 — a sealed
# Longines at exactly 700 RON cleared the used floor by one leu, and Tissot had no
# floor at all). These apply ONLY when the ad claims the watch is new or sealed, so
# the honest second-hand and vintage market is untouched.
#
# "ca nou" means "like new" and describes a USED watch — it must not trigger this,
# which is why the claim is matched after those phrases are stripped out.
_USED_BUT_TIDY_RE = re.compile(
    r"\b(?:ca|aproape|precum)\s+(?:[sș]i\s+)?nou[aă]?\b", re.I)
NEW_CLAIM_RE = re.compile(
    r"\bsigilat[eă]?\b|\bin tipla\b|\bnepurtat[aă]?\b|\bnew in box\b|\bnib\b|\bnou[aă]?\b", re.I)

NEW_FLOOR_RON = {
    "rolex": 25000,
    "cartier": 10000,
    "iwc": 15000,
    "panerai": 15000,
    "omega": 8000,
    "tudor": 8000,
    "breitling": 8000,
    "tag heuer": 4000,
    "oris": 3000,
    "longines": 2500,
    "maurice lacroix": 2500,
    "frederique constant": 2500,
    "rado": 2000,
    "hamilton": 1800,
    "tissot": 1200,
    "certina": 900,
    "seiko": 600,
    "citizen": 500,
    "orient": 500,
    "fossil": 400,
    "g-shock": 350,
    "casio": 250,
}


def _norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c)).lower()


def claims_new(text):
    """True when the ad presents the watch as new/sealed rather than second-hand."""
    return bool(NEW_CLAIM_RE.search(_USED_BUT_TIDY_RE.sub(" ", text or "")))


# A replica is advertised by MODEL, not by brand — writing "Rolex" invites the
# takedown. "Ceas GMT-Master II - 41mm" at 149 lei and "HB Big Bang Steel" at 1599
# (both seen 2026-08-12) never say Rolex or Hublot, so the brand table never fired
# and both cleared every floor. These model names belong to exactly one maker, so an
# ad using one is judged against that maker's floor.
#
# Ordered most specific first; every value must be a key in BRAND_FLOOR_RON.
MODEL_IMPLIES_BRAND = [
    (r"\bgmt[\s-]?master\b", "rolex"),
    (r"\bsea[\s-]?dweller\b", "rolex"),
    (r"\bsky[\s-]?dweller\b", "rolex"),
    (r"\byacht[\s-]?master\b", "rolex"),
    # NOT "day-date": it is the name of an ordinary complication before it is the
    # name of a Rolex, and a 1997 Swatch listing "functii: day-date (afisaj zi si
    # data)" was held to Rolex's 6000 RON floor because of it.
    (r"\bair[\s-]?king\b", "rolex"),
    (r"\bexplorer\s*(?:ii|2)\b", "rolex"),
    (r"\boyster\s+perpetual\b", "rolex"),
    (r"\bdatejust\b", "rolex"),
    (r"\bsubmariner\b", "rolex"),
    (r"\bdaytona\b", "rolex"),
    (r"\bmilgauss\b", "rolex"),
    (r"\bdeepsea\b", "rolex"),
    (r"\bcellini\b", "rolex"),
    (r"\bbig\s+bang\b", "hublot"),
    (r"\bclassic\s+fusion\b", "hublot"),
    (r"\broyal\s+oak\b", "audemars piguet"),
    (r"\bnautilus\b", "patek philippe"),
    (r"\baquanaut\b", "patek philippe"),
    (r"\bcalatrava\b", "patek philippe"),
    (r"\bspeedmaster\b", "omega"),
    (r"\bseamaster\b", "omega"),
    (r"\bplanet\s+ocean\b", "omega"),
    (r"\baqua\s+terra\b", "omega"),
    (r"\bnavitimer\b", "breitling"),
    (r"\bsuperocean\b", "breitling"),
    (r"\bluminor\b", "panerai"),
    (r"\bradiomir\b", "panerai"),
    (r"\breverso\b", "jaeger-lecoultre"),
    (r"\bportugieser\b|\bportuguese\b", "iwc"),
    (r"\bbig\s+pilot\b", "iwc"),
    (r"\bballon\s+bleu\b", "cartier"),
    (r"\bblack\s+bay\b", "tudor"),
    (r"\bpelagos\b", "tudor"),
    (r"\bel\s+primero\b", "zenith"),
    (r"\bcarrera\b", "tag heuer"),
    (r"\bmonaco\b", "tag heuer"),
]


# What the marketplace's brand field says when the seller named no maker at all.
# Anything else counts as a named brand, whether or not it has a floor of its own.
UNNAMED_BRAND = {"", "alt brand", "alta marca", "alte marci", "altele", "other",
                 "unbranded", "fara marca", "no name", "noname", "generic", "swiss"}

# Wording that says the ad is openly a homage or a modded watch rather than
# claiming to BE the model — "Seiko Mod Daytona", "Seiko modificat in stil
# Submariner". Those are honest listings of a real Seiko and must not be judged
# against Rolex's floor.
_HOMAGE_RE = re.compile(
    r"\bmod(?:ificat[ae]?|at|ded)?\b|\bin stil\b|\bstyle\b|\bhomage\b|\bomagiu\b", re.I)


def _names_a_priced_brand(haystack):
    return any(re.search(r"\b" + re.escape(n) + r"\b", haystack) for n in BRAND_FLOOR_RON)


def implied_brand(haystack, brand=None):
    """The maker a model name gives away, when the ad names no maker of its own.

    Deliberately a FALLBACK, and it stays silent in three cases, each of which was a
    real false positive on the 2026-08-12 candidate pool:

    * the ad names a brand — believe it. Seiko has no floor of its own, so checking
      only the priced brands held "Seiko Mode Submariner" to Rolex's floor.
    * the ad names a priced brand in its text, so that brand governs: a genuine
      vintage Tudor Submariner is held to Tudor's floor, not Rolex's.
    * the ad openly says homage/mod, which is a real watch described by what it
      resembles, not one passing itself off.
    """
    if _norm(brand).strip() not in UNNAMED_BRAND:
        return None
    if _names_a_priced_brand(haystack):
        return None
    if _HOMAGE_RE.search(haystack):
        return None
    for pattern, name in MODEL_IMPLIES_BRAND:
        if re.search(pattern, haystack):
            return name
    return None


def price_in_ron(price, currency):
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    return price * EUR_TO_RON if (currency or "RON").upper() == "EUR" else price


def implausible_price(price, currency, brand=None, text=""):
    """Return a reason string when the price is too low to be genuine, else None.

    `brand` is the resolved brand name (or the seller's label); `text` should be
    the title plus the ad body, because the model family usually lives there.
    """
    ron = price_in_ron(price, currency)
    if ron is None or ron <= 0:
        return None

    low = _norm(text)
    for pattern, floor, label in FAMILY_FLOOR_RON:
        if re.search(pattern, low):
            if ron < floor:
                return ("%s at %d RON is below the %d RON floor for a genuine one — "
                        "almost certainly a fake or a scam" % (label, ron, floor))
            return None                     # the family rule settles it, floor cleared

    # The brand argument is whatever the caller resolved — often the marketplace's
    # own label, which is unreliable (OLX offered "Swiss" for a Christophe Duchamp)
    # and frequently absent. So the ad's own words count too: a listing that calls
    # itself a Rolex is judged as one, whoever filled in the dropdown.
    haystack = _norm(brand) + " \n " + low

    # Fold the maker implied by a model name into the haystack, so both floors below
    # see it exactly as if the ad had named the brand. Appending is only safe because
    # implied_brand() stays silent whenever the ad already names a priced brand.
    _implied = implied_brand(haystack, brand)
    if _implied:
        haystack += " \n " + _implied

    # Checked before the used floor, because it is the stricter of the two and the
    # used floor would otherwise clear the listing and return.
    if claims_new(text):
        for name, floor in NEW_FLOOR_RON.items():
            if re.search(r"\b" + re.escape(name) + r"\b", haystack):
                if ron < floor:
                    return ("%s advertised as new/sealed at %d RON is below the %d RON "
                            "floor for a genuine new one — almost certainly a replica"
                            % (brand or name, ron, floor))
                break

    for name, floor in BRAND_FLOOR_RON.items():
        # match as a word, so "Tudor" does not fire on "Tudorache"
        if re.search(r"\b" + re.escape(name) + r"\b", haystack):
            if ron < floor:
                return ("%s at %d RON is below the %d RON floor for a genuine one — "
                        "almost certainly a fake" % (brand or name, ron, floor))
            return None
    return None
