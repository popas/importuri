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

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
