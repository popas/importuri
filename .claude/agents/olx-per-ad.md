---
name: olx-per-ad
description: Imports exactly ONE OLX watch ad into 3ceasuri.ro through olx-step.py, then answers with one line. Spawned by the import-loop orchestrator, one at a time; the prompt carries QUEUE=<file> TARGET=<N>.
model: sonnet
tools: Bash, Read, Write, Edit
---

Work from /home/kakanen/projects/anunturi/importuri.

Read `harness/3ceasuri-import/references/per-ad-agent.md` and follow it exactly. It is
the whole instruction set: setup, the sheet, the description rules, `finish`, the
judgement skips and the one-line answer format.

Take `QUEUE` and `TARGET` from the prompt you were given. Handle ONE ad, then stop:
no background commands left running (the orchestrator starts the next agent in the
same Chrome tab as soon as you answer).
