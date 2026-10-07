#!/usr/bin/env python3
# =============================================================================
# photo_dedup.py — the same watch relisted under a new ad id, caught by its photos.
#
# Two ways one watch came back on 2026-10-07, both imported-or-nearly before a human
# noticed: the same seller re-posting three minutes later (310205408 after 310205538)
# and a second seller account posting the identical five photos (299246401 after
# 299247856). The seller+model repost check cannot see either in pass 1 — the model
# is not known yet — and never sees the second, because the seller differs. The
# photo bytes are the same file both times: OLX serves an upload unchanged.
#
# Plain module (python3 or a browser-use payload, no browser calls). Only photos of
# ads that were IMPORTED count (history.jsonl), and a hash found under many ads is a
# shop's banner card or OLX's placeholder, never evidence: the pawn shops put the
# same two logo images on every watch they list.
# =============================================================================
import hashlib
import json
import os

import candidates

CACHE = ".hashes.json"     # {"olx-<id>/NN.jpg": [size, mtime, md5]} inside the photo root
BANNER_ADS = 5             # a hash under this many OTHER ads is boilerplate
MIN_SHARED = 2             # photos an ad must share with ONE earlier ad (fewer if it has fewer)
MIN_BYTES = 5000           # smaller is a failed download (OLX answers 600 bytes), not a photo
# OLX's grey "OLX" tile, served where an upload is gone. Rare enough per run to slip
# under BANNER_ADS, so it is named.
PLACEHOLDERS = {"ad28c3de369aa3f26db355c4429bb3ef"}


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def index(photo_root):
    """{ad_id: {file: md5}} for every olx-<id> directory, cached by (size, mtime).

    The cache makes a re-run cost one stat() per photo; only new or changed files are
    read. A cache that cannot be written is not an error — the next run re-hashes.
    """
    cache_path = os.path.join(photo_root, CACHE)
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    out, changed = {}, False
    for d in sorted(os.listdir(photo_root)) if os.path.isdir(photo_root) else []:
        full = os.path.join(photo_root, d)
        if not d.startswith("olx-") or not os.path.isdir(full):
            continue
        files = {}
        for name in sorted(os.listdir(full)):
            if not name.endswith(".jpg"):
                continue
            path = os.path.join(full, name)
            st = os.stat(path)
            if st.st_size < MIN_BYTES:
                continue
            key = "%s/%s" % (d, name)
            hit = cache.get(key)
            if hit and hit[0] == st.st_size and hit[1] == int(st.st_mtime):
                files[name] = hit[2]
            else:
                files[name] = file_md5(path)
                cache[key] = [st.st_size, int(st.st_mtime), files[name]]
                changed = True
        out[d[len("olx-"):]] = files
    if changed:
        try:
            tmp = cache_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cache, f)
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return out


def find_duplicate(photo_root, ad_id, history_path):
    """(earlier_ad_id, shared_count) when this ad's photos repeat an imported ad's.

    None when there is no such ad, or when this ad has no photos on disk yet.
    """
    idx = index(photo_root)
    ad_id = str(ad_id)
    ads_per_hash = {}
    for files in idx.values():
        for h in set(files.values()):
            ads_per_hash[h] = ads_per_hash.get(h, 0) + 1
    # ads_per_hash counts this ad too, hence the -1.
    mine = {h for h in set(idx.get(ad_id, {}).values())
            if ads_per_hash.get(h, 0) - 1 < BANNER_ADS and h not in PLACEHOLDERS}
    if not mine:
        return None
    need = min(MIN_SHARED, len(mine))
    done = candidates.history_imported(history_path)
    best = None
    for other, files in idx.items():
        if other == ad_id or other not in done:
            continue
        shared = len(mine & set(files.values()))
        if shared >= need and (best is None or shared > best[1]):
            best = (other, shared)
    return best
