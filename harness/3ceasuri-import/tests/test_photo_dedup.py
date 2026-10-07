#!/usr/bin/env python3
"""Offline checks for photo_dedup.py: the same watch relisted under a new ad id is
caught by its photo bytes, while shop banners, OLX placeholders and failed downloads
never count as evidence. Runs in a scratch folder -- never the real .photos/."""
import json, os, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import photo_dedup

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


def photo(tag):
    """A distinct 'photo': big enough to clear MIN_BYTES, unique per tag."""
    return ((tag + "|") * photo_dedup.MIN_BYTES).encode()[:photo_dedup.MIN_BYTES + 100]


def ad_dir(root, ad_id, photos):
    d = os.path.join(root, "olx-%s" % ad_id)
    os.makedirs(d, exist_ok=True)
    for i, data in enumerate(photos, 1):
        with open(os.path.join(d, "%02d.jpg" % i), "wb") as f:
            f.write(data)


def history(path, imported):
    with open(path, "w") as f:
        for i in imported:
            f.write(json.dumps({"event": "import", "id": str(i)}) + "\n")
        f.write(json.dumps({"event": "skip", "id": "999"}) + "\n")


root = tempfile.mkdtemp(prefix="dedup-test-")
hist = os.path.join(root, "history.jsonl")
banner = photo("BANNER")

# 1 = an imported watch; 2 = the same five photos again (another seller account)
ad_dir(root, 1, [photo("a"), photo("b"), photo("c"), photo("d"), photo("e")])
ad_dir(root, 2, [photo("c"), photo("a"), photo("e"), photo("b"), photo("d")])
# 3 = a different watch from a pawn shop that puts the same banner on every ad
ad_dir(root, 3, [photo("x"), photo("y"), banner])
for n in range(10, 16):                      # the shop's other listings, all imported
    ad_dir(root, n, [photo("w%d" % n), photo("v%d" % n), banner])
# 4 = only failed downloads and OLX's placeholder, shared with the imported ad 5
tiny = b"x" * 600
ad_dir(root, 5, [tiny, tiny, photo("p")])
ad_dir(root, 4, [tiny, tiny])
# 6 = shares ONE photo with imported ad 1 (a stock shot both sellers used)
ad_dir(root, 6, [photo("a"), photo("q"), photo("r")])
# 7 = a byte-identical copy of ad 8, which was never imported
ad_dir(root, 8, [photo("m"), photo("n")])
ad_dir(root, 7, [photo("m"), photo("n")])
history(hist, [1, 5] + list(range(10, 16)))

check(photo_dedup.find_duplicate(root, 2, hist) == ("1", 5),
      "the same five photos as an imported ad are a duplicate: %s"
      % (photo_dedup.find_duplicate(root, 2, hist),))
check(photo_dedup.find_duplicate(root, 3, hist) is None,
      "a shop banner on many ads is boilerplate, not a duplicate")
check(photo_dedup.find_duplicate(root, 4, hist) is None,
      "600-byte failed downloads are not photos")
check(photo_dedup.find_duplicate(root, 6, hist) is None,
      "one shared photo out of three is not enough")
check(photo_dedup.find_duplicate(root, 7, hist) is None,
      "only IMPORTED ads count -- a copy of a skipped or pending ad is not a repost")
check(photo_dedup.find_duplicate(root, 404, hist) is None, "no photos on disk -> None")
check(photo_dedup.find_duplicate(root, 1, hist) == ("2", 5) or
      photo_dedup.find_duplicate(root, 1, hist) is None,
      "an ad never matches itself")

# OLX's placeholder tile is named, so even a few ads sharing it never match
ph = os.path.join(root, "olx-20")
ad_dir(root, 20, [photo("s"), photo("t")])
ad_dir(root, 21, [photo("u"), photo("z")])
_orig = photo_dedup.PLACEHOLDERS
photo_dedup.PLACEHOLDERS = {photo_dedup.file_md5(os.path.join(root, "olx-21", "01.jpg")),
                            photo_dedup.file_md5(os.path.join(root, "olx-21", "02.jpg"))}
ad_dir(root, 22, [photo("u"), photo("z")])
history(hist, [1, 5, 21] + list(range(10, 16)))
check(photo_dedup.find_duplicate(root, 22, hist) is None, "placeholder hashes never count")
photo_dedup.PLACEHOLDERS = _orig

# the cache: written once, reused, and a changed file is re-hashed
cache = os.path.join(root, photo_dedup.CACHE)
check(os.path.exists(cache), "the hash cache must be written")
before = photo_dedup.index(root)["2"]["01.jpg"]
with open(os.path.join(root, "olx-2", "01.jpg"), "wb") as f:
    f.write(photo("CHANGED"))
os.utime(os.path.join(root, "olx-2", "01.jpg"), (1, 1))
check(photo_dedup.index(root)["2"]["01.jpg"] != before, "a changed file must be re-hashed")
check(photo_dedup.find_duplicate(root, 2, hist) == ("1", 4), "four of five still match")

# --- shop cards: the same file beside two DIFFERENT watches -------------------
# The shape of 304459760 / 304460733 (2026-10-07): two TotalConvert watches, each with
# its own photos, both carrying the shop's three cards. Only two ads, so far under
# BANNER_ADS -- by count alone the second one looked like a relist of the first.
croot = tempfile.mkdtemp(prefix="cards-test-")
chist = os.path.join(croot, "history.jsonl")
cards_file = os.path.join(croot, "shop-cards.json")
shop = [photo("LOGO"), photo("STOREFRONT"), photo("INSIDE")]
ad_dir(croot, 30, [photo("blue1"), photo("blue2")] + shop)
ad_dir(croot, 31, [photo("orange1"), photo("orange2"), photo("orange3")] + shop)
# a relist: the same five photos (the G-Shock shape) -- never cards
ad_dir(croot, 40, [photo("g%d" % i) for i in range(5)])
ad_dir(croot, 41, [photo("g%d" % i) for i in range(5)])
# one own photo each beside the shared ones: as likely a relist as a shop (the Rolex
# shape, 7 of 8 shared) -- not learned
ad_dir(croot, 50, [photo("r-own-a")] + [photo("r%d" % i) for i in range(3)])
ad_dir(croot, 51, [photo("r-own-b")] + [photo("r%d" % i) for i in range(3)])
history(chist, [30, 40, 50])

check(photo_dedup.find_duplicate(croot, 31, chist) == ("30", 3),
      "without the card check the shop's second watch looks like a relist")
got = photo_dedup.shop_cards(croot, 31, cards_file, seller="TotalConvert.ro")
check(sorted(got) == ["04.jpg", "05.jpg", "06.jpg"],
      "the three shared files beside different watches are cards: %s" % sorted(got))
saved = photo_dedup.load_cards(cards_file)
check(set(saved) == set(got.values()), "learned cards are written to the list: %s" % saved)
_e = next(iter(saved.values()), {})
check(_e.get("seller") == "TotalConvert.ro" and _e.get("also_on") == "olx-30"
      and _e.get("example", "").startswith("olx-31/"), "a learned entry says where: %s" % _e)
check(photo_dedup.find_duplicate(croot, 31, chist, ignore=set(saved)) is None,
      "with the cards ignored, the shop's second watch is not a relist")
check(photo_dedup.shop_cards(croot, 30, cards_file) == {f: h for f, h in
      photo_dedup.index(croot)["30"].items() if h in saved},
      "the first ad's copies of the cards are cards too")
check(photo_dedup.shop_cards(croot, 41, cards_file) == {}, "a relist's photos are never cards")
check(photo_dedup.find_duplicate(croot, 41, chist, ignore=set(saved)) == ("40", 5),
      "a relist is still a duplicate")
check(photo_dedup.shop_cards(croot, 51, cards_file) == {},
      "one own photo each is not enough to call the shared ones cards")

# the list works where the other ad is not on disk (the other machine)
other = tempfile.mkdtemp(prefix="cards-other-")
ad_dir(other, 32, [photo("green1"), photo("green2")] + shop)
check(sorted(photo_dedup.shop_cards(other, 32, cards_file)) == ["03.jpg", "04.jpg", "05.jpg"],
      "a card on the list is dropped even with no other ad on disk")
check(photo_dedup.shop_cards(other, 32, os.path.join(other, "none.json")) == {},
      "without the list and without another ad nothing is learned")
check(photo_dedup.load_cards(os.path.join(other, "none.json")) == {},
      "a missing list reads as empty")
with open(os.path.join(other, "bad.json"), "w") as f:
    f.write("{not json")
check(photo_dedup.load_cards(os.path.join(other, "bad.json")) == {},
      "an unreadable list reads as empty")
check(photo_dedup.load_cards(photo_dedup.CARDS_FILE),
      "the committed list (references/shop-cards.json) loads and is not empty")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
