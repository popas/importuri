# Per-ad model eval

Which model and effort can run the one-ad import agent (`.claude/agents/olx-per-ad.md`)?
Offline: no browser, no OLX, nothing written to the site.

```bash
python3 evals/per-ad/eval.py run haiku low       # one config -> results/haiku-low.jsonl
python3 evals/per-ad/eval.py run sonnet high     # models: haiku|sonnet|opus, effort: low|medium|high|xhigh|max
python3 evals/per-ad/eval.py score               # every results/*.jsonl -> report.md
```

- `cases.jsonl` + `photos/` — 36 ads from the 2026-11-07/08 runs: 12 classic and 12 smart
  imports, 12 judgement skips (not_a_watch, bulk_lot, suspected_counterfeit,
  mismatched_photos). Each case is the sheet the agent saw, rebuilt from `.runs/` and
  `.contracts/`. `build` regenerates them from local logs (only on the machine that ran
  the imports; it overwrites the set — commit only on purpose).
- The prompt and the `claude -p` call are `harness/3ceasuri-import/scripts/decide.py` —
  the same module `olx-loop.py` uses in production — fed the sheet `olx-step.py`'s
  `sheet()` renders, with the CURRENT `per-ad-agent.md` "The sheet" rules. A change to
  the instructions, the hints or the framing is what gets tested.
- The reference is what production did (Sonnet agents): the site-accepted fields, or
  the skip. A Sonnet config therefore measures Sonnet's self-consistency; a
  disagreement is not automatically an error — `report.md` lists every diff.
- Description scoring uses the importer's own gates (`olx_import.confidence_review`)
  plus word similarity to the production description.
- `$/ad` is what `claude -p` reports (API-equivalent cost), `s/ad` is wall time.
