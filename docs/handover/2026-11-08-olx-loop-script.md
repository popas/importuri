# 2026-11-08 — the import loop as a script (`olx-loop.py`)

Issue: #2. Commits: 0e83a2b (driver fixes), 02bd4a8 (eval), 63dbc45 (loop + decide).

## What changed

Until 2026-11-08 an import ran inside a Claude Code session: an Opus orchestrator
spawned one Sonnet agent per ad (`.claude/agents/olx-per-ad.md`), and each agent ran
`olx-step.py start / next / finish` around one judgement. Now a plain Python script runs
the loop and asks a model only that judgement:

```
olx-loop.py
  ├─ olx-step.py start <queue> --target N --clear-every 0
  └─ per ad:
       ├─ olx-step.py next            → SKIPPED / ERROR / TARGET_REACHED / … or a sheet
       ├─ decide.py: claude -p (sheet + the "The sheet" rules of per-ad-agent.md)
       │    → {"action": "finish"|"skip", "skip_code", "fields", "description"}
       ├─ writes .contracts/olx-<id>.description.txt
       ├─ olx-step.py finish <id> field=value …   (or: skip <id> <code> '<notes>')
       ├─ on FIX: one more claude -p call, merged onto the first answer
       ├─ on NEW_BRAND: runs the printed git commit
       └─ every 10 ads: git add history.jsonl + brand files + shop-cards.json, commit, push
```

## How to run it

Prerequisites, as for any import: the CDP Chrome is up (`BU_CDP_URL`, default
`http://127.0.0.1:9222`), signed in to the 3ceasuri.ro admin and to olx.ro, with an
olx.ro tab; `claude` is on PATH and logged in (`claude -p "OK"` answers).

From the repo root, in a terminal:

```bash
python3 harness/3ceasuri-import/scripts/olx-loop.py harness/3ceasuri-import/<queue file> --target 100
```

| Option | Default | Meaning |
|---|---|---|
| `--target N` | required | imports this session; the driver stops the loop there |
| `--model` | `sonnet` | model of the decision call (`haiku`, `sonnet`, `opus`) |
| `--effort` | `high` | `low`, `medium`, `high`, `xhigh`, `max` |
| `--push-every N` | `10` | commit + push every N settled ads (`0`: only at the end) |
| `--no-push` | off | never commit or push (testing) |

Queue state: `python3 harness/3ceasuri-import/scripts/olx-step.py counts <queue file>`.

## What it prints

One line per ad (the driver's own first line): `IMPORTED <id>: …`, `SKIPPED <id>: …`,
`ERROR <id>: …`, `  FIX … -> asking again` before a retry. At every push:
`PROGRESS: imported N, skipped N, errors N | X ads/min | model $Y (sonnet high)`; at the
end the same line as `DONE:`.

## When it stops

| Line | Exit | Session | What to do |
|---|---|---|---|
| `TARGET_REACHED` / `QUEUE_EMPTY` | 0 | stopped (`stop`), pushed | nothing; a new run starts a new session |
| `OLX_BLOCKED <id>` | 2 | left running, ad stays `pending` | OLX refuses this browser (403/429 on the ad API). Restart the CDP Chrome or wait, then run the **same command**: it resumes |
| `BROWSER_FAILURE` / `PREFLIGHT_FAILED` | 2 | left running | fix Chrome / the admin login (`olx-troubleshooting` skill), run the same command |
| `STOPPED: three ERROR in a row` | 2 | left running | `olx-troubleshooting`; then the same command |
| `STOPPED: another olx-loop is running` | 2 | — | one loop at a time (one Chrome, one OLX tab, one `state.json`); stale lock: delete `.olx-loop.lock` |
| Ctrl-C (`INTERRUPTED`) | 130 | left running, pushed | the same command resumes |

Resuming works because `olx-step.py start` on the queue of a running session now always
resumes it (counters and target kept). A fresh session on the same queue: `olx-step.py
stop <queue>`, then run the loop.

## The decision call

`scripts/decide.py` is the only model call. It frames the sheet with the "The sheet"
section of `references/per-ad-agent.md` (read at call time — that section is the
rulebook), runs `claude -p --model <m> --effort <e> --output-format json --allowedTools
Read --add-dir .photos` from a temp directory (so no project CLAUDE.md or memory is
loaded; never `--bare`, it skips the login), and parses one JSON object. An unusable
reply is re-asked once; a second one marks the ad `error`. Only the sheet's DECIDE fields
(+ `new_model`) are passed to `finish`, as argv items — no shell quoting.

To change how decisions are made: edit `per-ad-agent.md` "The sheet" (or the driver's
`HINTS`), then re-run the eval below before trusting it.

## Choosing model and effort — `evals/per-ad/`

36 offline cases from the 2026-11-07/08 runs, sent through the same `decide.py` call.
Reference = what production Sonnet decided. Full table and every diff:
`evals/per-ad/report.md`; how to re-run: `evals/per-ad/README.md`.

| config | decision ok | skips caught | $/ad |
|---|---|---|---|
| haiku low / medium / high | 83% / 86% / 83% | 6 / 7 / 6 of 12 | ~0.005 |
| sonnet low / medium / high | 86% / 89% / 92% | 7 / 8 / 9 of 12 | ~0.065–0.070 |

Fields are about equal; the difference is the judgement skips (Haiku imported a bulk lot
and a smart ring). Hence the default `sonnet high`. Only 12 skip cases: one case moves a
rate by 8 points.

## Driver fixes made the same day (0e83a2b)

- `start` resumes the running session instead of zeroing `session_imported` — before,
  every per-ad agent reset it and `TARGET_REACHED` never fired.
- `olx_api.offer()` raises `Blocked` when every read answers 403/429; the driver prints
  `OLX_BLOCKED` and leaves the ad `pending` (it used to be `error`, "did not load").
  2026-11-08: CloudFront blocked the single-ad API after ~380 reads in one Chrome
  session; a fresh Chrome cleared it.
- `finish` strips a leading brand from `model` ("Suunto RUN" → "Run") and takes the
  site's spelling from the brand's MODELS list.

## Fallbacks

- **One agent per ad** from a Claude Code session: Prompt C in
  `OLX_IMPORT_SESSION_PROMPT.md`, agent type `olx-per-ad` (pinned to Sonnet).
- **One operator session**: Prompt B in the same file.

Both use the same driver and the same "The sheet" rules.

## Tests

`python3 harness/3ceasuri-import/tests/test_olx_loop.py` — a fake `olx-step.py` and a
fake `claude` (`OLX_STEP`, `CLAUDE_BIN` env vars): import, FIX → merged retry, skip →
OLX_BLOCKED exit, unusable reply → re-ask → error, 3× ERROR stop. The driver fixes are in
`test_olx_step.py`.

## Open

- The live 10-ad run comparing the script with the per-agent loop (issue #2 acceptance).
- The site may still hold Baume & Mercier rows 134 and 266 next to 298 (user directive
  2026-11-08: one brand, id 298) — check the admin, move their listings, delete them.
