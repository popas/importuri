# 2026-11-08 — the import loop as a script (`olx-loop.py`)

Issue: #2. Commits: 0e83a2b (driver fixes), 02bd4a8 (eval), 63dbc45 (loop + decide).

## Cum folosești scriptul — pas cu pas

**1. Pornește Chrome-ul cu CDP** pe profilul persistent `~/.hermes/chrome-debug`:

```bash
harness/3ceasuri-import/scripts/chrome-cdp.sh start     # deschide și tab-urile olx.ro + admin
harness/3ceasuri-import/scripts/chrome-cdp.sh status    # CDP up? ce profil?
```

Scriptul rulează exact comanda folosită până acum (`--remote-debugging-address=0.0.0.0
--remote-debugging-port=9222 '--remote-allow-origins=*' --user-data-dir="$HOME/.hermes/chrome-debug"
--no-first-run --no-default-browser-check`) și așteaptă până răspunde CDP-ul. Alte
valori: `CHROME_PROFILE=… CDP_PORT=… CDP_ADDRESS=…` în fața comenzii.

> `0.0.0.0` înseamnă că oricine ajunge la portul 9222 (de ex. din rețeaua locală) poate
> controla browserul, autentificat în admin, fără parolă. Dacă nu-l comanzi de pe altă
> mașină, `CDP_ADDRESS=127.0.0.1 …/chrome-cdp.sh start` îl ține doar pe acest calculator.

**2. Prima dată pe profil:** autentifică-te în tab-urile deschise (`3ceasuri.ro/admin`
și olx.ro). Profilul e un folder — login-urile, cookie-urile și setările rămân în
`~/.hermes/chrome-debug` și sunt acolo la fiecare pornire cu același folder. Folderul stă
**în afara repo-ului** intenționat: conține o sesiune de admin activă; nu-l comite.

**Backup / mutare a profilului** (cu Chrome închis):

```bash
harness/3ceasuri-import/scripts/chrome-cdp.sh stop
harness/3ceasuri-import/scripts/chrome-cdp.sh backup            # -> ~/.hermes/backups/chrome-debug-<dată>.tar.gz
harness/3ceasuri-import/scripts/chrome-cdp.sh restore ~/.hermes/backups/chrome-debug-<dată>.tar.gz
```

Backup-ul lasă pe dinafară cache-urile (cea mai mare parte din cei ~1,2 GB; Chrome le
reface). `restore` mută profilul curent deoparte (`…before-restore-<dată>`), nu-l șterge.
Pe Linux, Chrome criptează cookie-urile cu cheia din keyring-ul utilizatorului: un backup
pus înapoi pe același calculator/utilizator își păstrează login-urile; pe altă mașină
probabil va trebui să te autentifici din nou.

**3. Verifică `claude`** (o singură dată pe mașină):

```bash
claude -p "Reply with OK" </dev/null           # trebuie să scrie OK
```

**4. Alege coada** — cozile cu anunțuri în așteptare, cele mai pline primele:

```bash
cd ~/projects/anunturi/importuri
python3 harness/3ceasuri-import/scripts/candidates.py queues          # --all: și cele goale
#   | Coadă                                | Tip   | Pending | Importate | Sărite | Erori | Generată   |
#   |:-------------------------------------|:------|--------:|----------:|-------:|------:|:-----------|
#   | .candidates-olx-smart-nat-1107b.json | smart |      24 |       100 |     36 |     0 | 2026-11-07 |
#   ...
#   cozi cu pending: 11 · anunțuri pending: 145 · cozi goale ascunse: 38 (--all le arată)
#   Pornește: python3 harness/3ceasuri-import/scripts/olx-loop.py harness/3ceasuri-import/<coada> --target 10
```

Ultima linie e comanda gata de copiat, pentru coada cu cele mai multe `pending` (sau
pentru cea cu o sesiune încă deschisă, marcată cu `*`). O singură coadă:
`python3 harness/3ceasuri-import/scripts/olx-step.py counts harness/3ceasuri-import/<coada>`.

Nicio coadă cu `pending` → creează una (secțiunea [Cum creezi o coadă nouă](#cum-creezi-o-coadă-nouă)).

**5. Prima dată, un test mic** (un singur anunț, fără commit/push):

```bash
python3 harness/3ceasuri-import/scripts/olx-loop.py \
    harness/3ceasuri-import/.candidates-olx-watches-nat-1107b.json --target 1 --no-push
```

Atenție: și testul importă de-adevăratelea pe site; `--no-push` oprește doar git-ul.

**6. Rularea propriu-zisă.** Pentru rulări lungi, într-un `tmux` (să nu se oprească
dacă închizi terminalul) și cu un log:

```bash
tmux new -s olx
cd ~/projects/anunturi/importuri
python3 harness/3ceasuri-import/scripts/olx-loop.py \
    harness/3ceasuri-import/.candidates-olx-watches-nat-1107b.json --target 30 \
    2>&1 | tee -a olx-loop.log
#   Ctrl-b apoi d = lași tmux-ul să ruleze;  tmux attach -t olx = te întorci la el
```

**7. Ce vezi:** câte o linie pe anunț (`IMPORTED …`, `SKIPPED …`), la fiecare 10 anunțuri
un `PROGRESS: …` (și un push pe GitHub), la final `DONE: imported N, skipped N, errors N
| … | model $X`. Un anunț durează de obicei 30–90 s.

**8. Dacă vrei să-l oprești:** Ctrl-C. Face push la ce s-a importat și lasă sesiunea
deschisă; **aceeași comandă** o reia de unde a rămas (contoarele și ținta se păstrează).

**9. Dacă se oprește singur** — uită-te la ultima linie:

- `TARGET_REACHED` / `QUEUE_EMPTY` → gata, totul e salvat și împins. O coadă rămasă fără
  pending e mutată în `harness/3ceasuri-import/.candidates-done/` (linia `ARCHIVED:`);
  aceeași comandă pe ea răspunde apoi `QUEUE_EMPTY … is finished`.
- `OLX_BLOCKED` → OLX refuză browserul. `chrome-cdp.sh restart`, apoi aceeași comandă.
  Dacă blocajul rămâne și după restart (profilul persistent păstrează cookie-urile
  olx.ro), șterge cookie-urile olx.ro din acel Chrome (Settings → Privacy → Site data)
  sau așteaptă o vreme.
- `BROWSER_FAILURE`, `PREFLIGHT_FAILED`, `three ERROR in a row` → vezi tabelul „When it
  stops” mai jos (sau cere-i lui Claude Code să folosească skill-ul `olx-troubleshooting`),
  apoi aceeași comandă.

**10. O țintă nouă pe aceeași coadă** cât timp sesiunea e încă deschisă (după un
Ctrl-C sau o blocare): `--target` nou e ignorat la reluare. Închide sesiunea, apoi pornește:

```bash
python3 harness/3ceasuri-import/scripts/olx-step.py stop harness/3ceasuri-import/<coada>
python3 harness/3ceasuri-import/scripts/olx-loop.py harness/3ceasuri-import/<coada> --target 50
```

**11. Verificare la final:** `counts` pe coadă (pasul 4), `git log --oneline -3` (commit-urile
„history: OLX import loop …”), iar adevărul e în admin: `https://3ceasuri.ro/admin/`.

**Model mai ieftin** (nerecomandat — ratează mai multe skip-uri, vezi evals mai jos):
`--model haiku --effort medium`.

## Cum creezi o coadă nouă

O coadă e un fișier `harness/3ceasuri-import/.candidates-*.json` cu anunțurile de luat, fiecare
cu un `status` (`pending` → `imported` / `skipped` / `error`). O face **descoperirea**: caută
pe OLX cele mai noi anunțuri dintr-o categorie, aruncă ce e sigur de aruncat și scrie fișierul.
Când `candidates.py queues` nu mai arată nimic cu `pending`, sau vrei anunțuri mai noi, faci
una nouă.

**Ce-ți trebuie:** Chrome-ul CDP pornit (pasul 1), autentificat pe olx.ro **și** în admin —
descoperirea întreabă adminul ce e deja pe site. Scripturile `olx-find-*.py` sunt payload-uri
browser-use: se dau pe stdin lui `browser-use`, **nu** se rulează cu `python3`.

```bash
cd ~/projects/anunturi/importuri
export BU_CDP_URL=http://127.0.0.1:9222

# ceasuri clasice (categoria 1677), toată țara
MAX_CANDIDATES=150 MAX_PAGES=25 \
OUT=harness/3ceasuri-import/.candidates-olx-watches-nat-1109.json \
browser-use < harness/3ceasuri-import/scripts/olx-find-watches.py

# smartwatch-uri (categoria 1943), toată țara
MAX_CANDIDATES=150 MAX_PAGES=25 \
OUT=harness/3ceasuri-import/.candidates-olx-smart-nat-1109.json \
browser-use < harness/3ceasuri-import/scripts/olx-find-smartwatches.py
```

> **`OUT` suprascrie fără să întrebe.** Un fișier care există deja e înlocuit cu totul, cu tot
> cu statusurile lui. Fără `OUT`, scriptul scrie în `.candidates-olx-watches.json` /
> `.candidates-olx-smart.json`, care **există deja** — dă-i mereu un nume nou.
> `candidates.py queues --all` arată numele luate.

**Numele cozii**, ca până acum: `.candidates-olx-<watches|smart>-<regiune>-<LLZZ>.json` —
regiunea `nat` (toată țara), `bucuresti`, `ilfov`, `cluj`…; data ca lună+zi (`1109` = 9
noiembrie); a doua coadă din aceeași zi primește o literă (`nat-1109b`).

| Variabilă | Implicit | Ce face |
|---|---|---|
| `MAX_CANDIDATES` | `8` | câte anunțuri intră în coadă, cel mult |
| `MAX_PAGES` | `5` | câte pagini de 40 de anunțuri citește, cele mai noi primele; se oprește mai devreme când a strâns destule |
| `COUNTY` | — | doar un județ, scris **exact** cu diacritice (ș, ț cu virgulă): `"București"`, `"Ilfov"`, `"Cluj"`, `"Brașov"`, `"Constanța"`, `"Iași"`, `"Timiș"` — `"Brasov"` aruncă tot (`wrong_county`) |
| `EXCLUDE_COUNTY` | — | județe de scos, despărțite prin virgulă: `"București,Ilfov"` (aceeași grafie) |
| `QUERY` | — | căutare text în categorie, de ex. `"ceas de buzunar"` — doar `olx-find-watches.py` |
| `MIN_RON` / `MIN_EUR` | `100`/`20` clasice, `150`/`30` smart | prețul minim (sub el anunțul nu intră) |
| `DEBUG_DROPS=1` | — | afișează și anunțurile aruncate, cu motivul |

Exemple: `COUNTY="București" MAX_CANDIDATES=60 OUT=…/.candidates-olx-watches-bucuresti-1109.json`;
restul țării fără capitală: `EXCLUDE_COUNTY="București,Ilfov"`.

**Ce afișează:** o linie `CANDIDATES: [...]` (un rând scurt pe anunț) și una `STATS:` —
`candidates` = câte au intrat în coadă, `dropped` = câte s-au aruncat și de ce,
`admin_total` = câte ceasuri are site-ul acum, `out` = fișierul scris. Un `ERROR:` cu „OLX
returned no offers” = nu ești logat pe olx.ro sau OLX blochează browserul (vezi pasul 9).

**Ce aruncă singur:** anunțuri inactive, fără preț sau sub pragul de preț, replici declarate,
accesorii, intervale de preț, stoc de magazin declarat, vânzători din blocklist și tot ce e
**deja importat pe site**. **Ce nu aruncă:** anunțurile *sărite* în cozile vechi — reapar
într-o coadă nouă și bucla le judecă din nou (cele dispărute de pe OLX se sar singure, ca
`not_active`). Loturi, piese, poze care nu se potrivesc: le prinde bucla, la import.

**Apoi:** `candidates.py queues` (coada nouă trebuie să apară cu `pending`) și pornești bucla
pe ea (pașii 5–6).

**Varianta prin Claude Code:** cere „Prompt A” din `OLX_IMPORT_SESSION_PROMPT.md`. Claude
pregătește sesiunea, rulează descoperirea prin skill-ul `olx-find-watches` /
`olx-find-smartwatches` și raportează `STATS` și câte anunțuri au intrat în coadă.
Spune-i ce nume să aibă coada (`OUT`), altfel o scrie peste cea implicită.

## Cum îmbunătățești bucla după ce rulează singură

Nici scriptul, nici Claude nu învață între rulări: se îmbunătățesc doar fișierele — regulile
(`per-ad-agent.md` „The sheet”, `HINTS` din `olx-step.py`), codul driverului și evals.
Bucla de îmbunătățire:

**1. Fiecare rulare lasă urme** (în `harness/3ceasuri-import/.runs/`, gitignored):

| Fișier | Ce conține |
|---|---|
| `olx-loop-<data-ora>.json` | rezumatul rulării: importuri/skip-uri/erori, FIX pe cod, skip pe cod, cost, apeluri model, fiecare anunț |
| `olx-<id>-decision.json` | pentru fiecare anunț: foaia, fiecare răspuns JSON al modelului (și al doilea, după FIX), fiecare răspuns al driverului, costul |
| `olx-<id>-pass1.log`, `-pass2-N.log` | ieșirea brută a importerului |
| `history.jsonl` (în git) | fiecare import și skip, cu motivul |

La final scriptul afișează și pe ecran: `FIX: description_drifted 3, … | SKIP: bulk_lot 2, …
| $0.08 and 1.3 model calls per decided ad`. Un FIX sau un skip care crește de la o rulare
la alta e primul semn că o regulă trebuie schimbată.

**2. Analiza:** deschide Claude Code în repo și cere, de exemplu, „analizează ultima rulare
olx-loop” (sau „anunțul 123 a ieșit greșit: modelul trebuia să fie X”). Claude citește
fișierele de mai sus, caută tipare și propune o reparație în reguli sau în cod.

**3. Cazul problemă intră în evals, cu răspunsul corect:**

```bash
python3 evals/per-ad/eval.py add <id> --expect import --set model=Seamaster --set variant=null
python3 evals/per-ad/eval.py add <id> --expect skip:bulk_lot      # trebuia sărit
```

**4. Reparația se verifică înainte de commit** — întâi pe cazul care a cerut-o, apoi pe tot setul:

```bash
python3 evals/per-ad/eval.py run sonnet high --only <id>
python3 evals/per-ad/eval.py run sonnet high && python3 evals/per-ad/eval.py score
```

Dacă scorul pe tot setul nu scade, reparația intră în git.

**5. Corecturile tale din admin** sunt cel mai bun semnal: un anunț pe care îl repari pe site
= un caz pentru pasul 3.

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
| `TARGET_REACHED` / `QUEUE_EMPTY` | 0 | stopped (`stop`), pushed; a queue with nothing pending moved to `.candidates-done/` (`ARCHIVED:`) | nothing; a new run starts a new session (on an archived queue it says `QUEUE_EMPTY … is finished` and exits 0) |
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

## The year (same day, later)

`year` is now always asked (`infer_fields.ALWAYS_ASK`, both profiles) and pass 1 no
longer seeds it: the regex took the first 19xx/20xx anywhere in the text. Of 21 imports
(2026-11-07/08) it set unasked, 7 were wrong — a service, a battery change, two ranges,
a history date, "2020-Now", a street name ("Str. 1 Decembrie 1918"). Rule: the year the
watch was made or bought new; never a service/battery/warranty/history date; a range or
a decade -> null. Eval: 10 of those ads added; Sonnet high answers the year right on 31
of 32 cases (the 32nd: right year, broken JSON - production re-asks).

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
