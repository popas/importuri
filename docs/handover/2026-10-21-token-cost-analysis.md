# Consumul de tokeni al buclei de import OLX: unde se duc și cum îl reduci

**Data:** 2026-10-21 (măsurat pe sesiunile din 2026-10-17 – 2026-10-20)
**Întrebarea:** poate harness-ul să consume mai puțini tokeni, de exemplu cu un orchestrator
Sonnet/Opus și cu Haiku pe procesele mai deterministe?
**Status:** analiză, nimic implementat.

Răspunsul scurt: da, dar câștigul mare nu vine din alegerea modelului. Tokenii se duc pe
**contextul care se adună în sesiune**. Orchestrarea rulează deja în Python și nu consumă
niciun token.

## Unde se duc tokenii (din transcrierile reale)

Sursa: câmpul `usage` din transcrierile Claude Code
(`~/.claude/projects/-home-kakanen-projects-anunturi-importuri/*.jsonl`), ultimele patru
sesiuni de import. Toate au rulat pe Sonnet 5.5.

Sesiunea `0aceeebd` (2026-10-20): 200 de importuri, 168 de skip-uri, 744 de apeluri API.

| | Tokeni | Echivalent API (Sonnet 5.5) |
|---|---|---|
| Citiri din cache (contextul re-citit la fiecare apel) | **189,2 M** | ~$38 (**~88%**) |
| Scrieri în cache | 0,88 M | ~$2–3,5 |
| Output (ce a scris modelul) | 0,24 M | ~$2,4 |
| **Total** | | **~$43 → ~$0,21 per import** |

Celelalte sesiuni arată la fel:

| Sesiune | Apeluri | Citiri din cache | Context mediu / apel | Context maxim |
|---|---|---|---|---|
| `0aceeebd` (10-20) | 744 | 189,2 M | 255K | 471K |
| `9aae96f7` (10-19/20) | 429 | 130,3 M | 305K | 549K |
| `8d28208d` (10-19) | 232 | 42,4 M | 184K | 322K |
| `e24b0526` (10-17) | 208 | 37,0 M | 179K | 315K |

Cum crește contextul în `0aceeebd`: pornește de la **43K** (system prompt-ul Claude Code,
tool-urile, CLAUDE.md, memoria), adaugă ~1,1K la fiecare apel (o foaie, o poză, un `finish`)
și ajunge la ~450K, unde se face compactarea (de două ori în sesiune). Media e de **255K
tokeni pe apel**. Pentru anunțul curent contează doar ~5K din ei. Restul de ~250K sunt
anunțurile vechi, re-citite la fiecare apel.

Note:
- Ce face operatorul pe fiecare anunț e deja minim: ~2 apeluri și ~660 de tokeni de output,
  iar foaia are ~1K tokeni. `olx-step.py` și-a făcut treaba. Costul vine din faptul că
  fiecare anunț moștenește istoria tuturor celor dinainte.
- Fiecare poză citită cu Read (249 în `0aceeebd`, ~1–1,5K tokeni fiecare) rămâne în context
  și e re-citită la toate apelurile următoare, până la compactare.
- La prețurile API, citirea din cache costă la fel pe Opus 5.5 și pe Sonnet 5.5 ($0,20/M).
  Într-o sesiune dominată de citiri din cache, alegerea modelului schimbă mai puțin decât
  lungimea contextului.
- Prețurile sunt echivalent API (Sonnet 5.5: $2 input / $10 output / $0,20 citire din
  cache per milion; Haiku 5.5: $0,10 / $0,50). Pe abonament, același volum de tokeni îți
  consumă limitele, deci ordinea priorităților rămâne aceeași.

## De ce „orchestrator Opus + Haiku pe partea deterministă” nu se potrivește aici

Partea deterministă e deja cod, la zero tokeni: dedup, prețuri minime, gate-uri, rutare,
logare, verificare (`olx-step.py`, `olx_import.py`). Ce rămâne pentru LLM e tocmai partea
care nu e deterministă: brand și model citite de pe poză, contrafaceri, descrierea corectată
în română. Iar „orchestratorul” nu face decât să ruleze linia `NEXT:`.

Așa că împărțirea care merge e alta: **bucla rămâne în cod, iar fiecare anunț primește un
apel LLM cu context curat**. Haiku intră la judecata per anunț, nu la orchestrare.

## Variantele, în ordinea câștigului per efort

### 1. `/clear` la fiecare ~25 de anunțuri, cu Sonnet. Zero cod.

Coada se reia singură de pe disc, deci nu se pierde nimic. Contextul mediu ar scădea de la
~255K la ~70K, adică de **~3,5 ori mai ieftin** cu același model și aceeași calitate.
Trebuie verificat doar că `next` merge după un `/clear` fără un nou `start`, ca să nu se
reseteze `state.json`.

### 2. Un subagent Haiku per anunț, în Claude Code

Sesiunea principală (Sonnet, `/effort low`) rulează `next`. Pentru fiecare foaie pornește
`Agent(model: haiku)`, care citește poza, scrie descrierea și rulează `finish`.
Orchestratorul crește atunci cu ~200 de tokeni per anunț în loc de ~2,2K. Rămâne o
necunoscută: contextul de bază al unui subagent din Claude Code. Asta se măsoară pe 5
anunțuri înainte de orice decizie. Escaladarea iese natural din gate-urile existente: un
`FIX` sau un caz de contrafacere trece la Sonnet.

### 3. Agentul propriu pe API (planul din `agent/`, pasul 1)

Un singur apel structurat per anunț: foaia, o poză și regulile, ~5K tokeni la intrare.
Estimare: ~$6 pe o sesiune ca `0aceeebd` pe Sonnet și **sub $0,50 pe Haiku 5.5**, față de
~$43. Câștigul e cel mai mare pentru că dispare și baza de 43K a Claude Code (system prompt,
tool-uri, CLAUDE.md). Directorul `agent/` nu există încă.

## Ce poate face Haiku și ce nu

| Decizie | Nivel propus |
|---|---|
| Rulat `next`/`finish`, parsat ieșirea | cod (e deja) |
| Descrierea corectată ușor | Haiku. Gate-urile `description_drifted`/`_meta` prind derapajele |
| Brand și model din lista MODELS, mișcarea, anul | Haiku, **doar după evaluare** |
| Contrafacere, lot, poze nepotrivite | Sonnet, sau escaladare când Haiku semnalează |
| Al doilea `FIX`, brand nou, troubleshooting, descoperire | Sonnet/Opus |

Gate-urile REVIEW cu `action: fix` sunt deja semnalul de escaladare. Un model mic care
greșește lovește un gate și primește încă o încercare, iar acolo intervine modelul mare. Nu
trebuie construit nimic nou pentru asta.

## Cum măsori înainte să muți ceva pe Haiku

Există **871 de contracte** în `harness/3ceasuri-import/.contracts/` și 1520 de loguri
pass-1 în `harness/3ceasuri-import/.runs/`, adică foile și răspunsurile care au intrat
efectiv pe site. Treci ~50 de foi prin Haiku offline și compară cu contractele: brand și
model exact, mișcare, câte gate-uri `FIX` ar fi picat. Exact asta e pasul 2 din planul
agentului propriu.

## Recomandare

1. Varianta 1 de la sesiunea următoare, pentru că e gratuită.
2. Varianta 3 ca agent propriu, cu evaluarea Haiku pe contractele existente.
3. Varianta 2 doar dacă bucla rămâne în Claude Code.

## Implementat: varianta 1 (2026-10-21)

Driverul impune regula, nu operatorul: după fiecare 25 de anunțuri încheiate (importate +
sărite) în contextul curent, `olx-step.py` răspunde cu `CLEAR_CHECKPOINT` în loc de
`NEXT: ... next`, iar `next` refuză să meargă mai departe (cod 5). Omul tastează `/clear`
și lipește Prompt B neschimbat; `start` vede că e aceeași coadă, încă `running`, cu
checkpoint-ul atins, și reia sesiunea fără să reseteze contoarele (`RESUMED_SESSION`).
Un anunț rămas cu draft pe disc e reluat de `next` ca până acum (`RESUMED`).
`start --clear-every K` schimbă pragul; `--clear-every 0` îl oprește. Ținta are
prioritate: la `TARGET_REACHED` urmează `stop`, nu `/clear`.

De verificat la prima sesiune: contextul mediu pe apel (ar trebui să fie ~70K, nu ~255K),
cu același script de numărat pe transcriere.
