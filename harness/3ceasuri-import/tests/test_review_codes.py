#!/usr/bin/env python3
"""Every review reason must be machine-readable: a code, and an action the runbook
can follow without judgement. Prose reasons are what made REVIEW: a coin flip."""
import os, re, sys

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
SRC = os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx_import.py")

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

src = open(SRC).read()

# 1. no bare-string review reasons survive
bare = re.findall(r"review\.append\(\s*[\"']", src)
check(not bare, "1: %d review.append() calls still push a bare string" % len(bare))

# 2. every review entry is built by the helper, with a legal action
codes = re.findall(r"_review\(\s*[\"']([a-z_]+)[\"']\s*,\s*[\"'](fix|skip)[\"']", src)
check(len(codes) >= 8, "2: expected >=8 coded review reasons, found %d" % len(codes))
check(len({c for c, _ in codes}) == len(codes), "2: duplicate review codes: %s" % codes)

# 3. the codes the runbook and the logger depend on all exist
for required in ("new_brand", "model_missing", "price_missing", "movement_missing",
                 "too_few_images", "thin_description", "misrouted_smart", "weak_repost"):
    check(any(c == required for c, _ in codes) or ('"%s"' % required) in src,
          "3: missing review code %r" % required)

# 4. doubt is never a 'fix' -- these must stop the watch, not be patched
for code, action in codes:
    if code in ("movement_missing", "weak_repost", "thin_description", "misrouted_smart"):
        check(action == "skip", "4: %s must be action=skip, is %r" % (code, action))

# 5. the two out-of-band reasons (built as dict literals, not via the helper) are
#    coded too -- a REVIEW consumer must never meet a bare string.
for code, action in (("weak_repost", "skip"), ("draft_invalid", "fix")):
    check(('"code": "%s", "action": "%s"' % (code, action)) in src,
          "5: %s must be emitted as a coded reason with action=%s" % (code, action))

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
