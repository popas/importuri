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


def _norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c)).lower()


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
    for name, floor in BRAND_FLOOR_RON.items():
        # match as a word, so "Tudor" does not fire on "Tudorache"
        if re.search(r"\b" + re.escape(name) + r"\b", haystack):
            if ron < floor:
                return ("%s at %d RON is below the %d RON floor for a genuine one — "
                        "almost certainly a fake" % (brand or name, ron, floor))
            return None
    return None
