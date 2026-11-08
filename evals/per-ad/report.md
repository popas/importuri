# Per-ad model eval

Reference: production Sonnet answers (site-accepted fields / judgement skips). 47 cases. Regenerate: `python3 evals/per-ad/eval.py score`.

| config | decision ok | skips caught | good ads skipped | model | variant | other fields | unknown model | invalid | desc gate | desc ≈ ref | $/ad | s/ad |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-high | 83% | 6/12 | 0 | 79% | 58% | 83% | 1 | 0 | 2 | 0.79 | 0.005 | 19 |
| haiku-low | 83% | 6/12 | 0 | 75% | 62% | 82% | 1 | 0 | 3 | 0.78 | 0.004 | 12 |
| haiku-medium | 86% | 7/12 | 0 | 79% | 46% | 83% | 0 | 0 | 2 | 0.80 | 0.005 | 14 |
| sonnet-high | 94% | 10/12 | 1 | 76% | 50% | 88% | 0 | 0 | 0 | 0.87 | 0.073 | 12 |
| sonnet-low | 86% | 7/12 | 0 | 79% | 58% | 88% | 0 | 0 | 1 | 0.90 | 0.065 | 9 |
| sonnet-medium | 89% | 8/12 | 0 | 75% | 46% | 89% | 0 | 0 | 2 | 0.88 | 0.066 | 9 |

## haiku-high

- 288635581 variant: 'Green Gold' (ref 'Gold Green')
- 288635581 brand: 'BOSS' (ref 'Hugo Boss')
- 307821123 model: 'Gold 9K' (ref 'Mecanic')
- 307821123 movement: None (ref 'manual')
- 295248289 variant: None (ref 'Big Date')
- 311663552 model: 'Quartz' (ref 'Date')
- 303881575 variant: 'Gold' (ref None)
- 239700714 model: 'Sportivo' (ref 'Chronograph')
- 239700714 variant: 'Black Leather' (ref None)
- 306743074 variant: 'Camo' (ref 'Grid Shock Camo')
- 311666038 model: 'Antimagnetic' (ref 'Mecanic')
- 311666038 variant: None (ref 'Gold-Tone')
- 311666038 movement: None (ref 'manual')
- 311658785 variant: 'Black Titanium' (ref 'Titanium')
- 311664733 model: 'Fit' (ref 'Smartwatch Round')
- 311664733 brand: 'VIWA' (ref 'Viwa Fit')
- 311664733 description gate: description_unedited
- 310127143 description gate: description_unedited
- 311662793 variant: 'Black' (ref None)
- 311617667 variant: 'Navy' (ref None)
- 311552615 variant: None (ref 'Silver, curea gri')
- 304023302 missed skip (not_a_watch)
- 309285260 missed skip (bulk_lot)
- 303844965 missed skip (suspected_counterfeit)
- 311124248 missed skip (suspected_counterfeit)
- 310445019 missed skip (suspected_counterfeit)
- 310078444 missed skip (mismatched_photos)

## haiku-low

- 288635581 variant: 'Green Dial Gold Chronograph' (ref 'Gold Green')
- 288635581 brand: 'BOSS' (ref 'Hugo Boss')
- 307821123 model: '9K Gold' (ref 'Mecanic')
- 307821123 movement: None (ref 'manual')
- 295248289 variant: None (ref 'Big Date')
- 311663552 model: 'Quartz' (ref 'Date')
- 303881575 variant: 'Gold' (ref None)
- 239700714 model: 'Sportivo' (ref 'Chronograph')
- 306743074 variant: 'Camo' (ref 'Grid Shock Camo')
- 311666038 model: 'Antimagnetic' (ref 'Mecanic')
- 311666038 variant: None (ref 'Gold-Tone')
- 311666038 movement: None (ref 'manual')
- 309038799 description gate: description_unedited
- 311658785 variant: None (ref 'Titanium')
- 311664733 model: None (ref 'Smartwatch Round')
- 311664733 brand: 'Fără marcă' (ref 'Viwa Fit')
- 311664733 description gate: description_unedited
- 311646244 description gate: description_meta
- 311647676 variant: None (ref 'Black')
- 309364544 variant: 'Midnight Blue' (ref 'Midnight')
- 311552615 variant: None (ref 'Silver, curea gri')
- 308662180 model: 'Suunto RUN' (ref 'Run')
- 304023302 missed skip (not_a_watch)
- 309285260 missed skip (bulk_lot)
- 303844965 missed skip (suspected_counterfeit)
- 311124248 missed skip (suspected_counterfeit)
- 310445019 missed skip (suspected_counterfeit)
- 310078444 missed skip (mismatched_photos)

## haiku-medium

- 288635581 variant: 'Green Gold' (ref 'Gold Green')
- 288635581 brand: 'BOSS' (ref 'Hugo Boss')
- 295248289 variant: None (ref 'Big Date')
- 311663552 model: 'Quartz' (ref 'Date')
- 311663552 variant: 'Black Dial' (ref None)
- 303881575 variant: 'Gold' (ref None)
- 239700714 model: 'Sportivo' (ref 'Chronograph')
- 306743074 variant: 'Camo' (ref 'Grid Shock Camo')
- 311666038 model: 'Antimagnetic' (ref 'Mecanic')
- 311666038 variant: 'Gold Case' (ref 'Gold-Tone')
- 309038799 variant: 'Black Milanese' (ref None)
- 309038799 description gate: description_unedited
- 311658785 variant: None (ref 'Titanium')
- 311664733 model: None (ref 'Smartwatch Round')
- 311664733 brand: 'Fără marcă' (ref 'Viwa Fit')
- 311664733 description gate: description_unedited
- 311647676 variant: 'Black Steel Strap' (ref 'Black')
- 309364544 variant: 'Midnight Blue' (ref 'Midnight')
- 311617667 variant: 'Navy' (ref None)
- 311666907 variant: 'Black/Graphite' (ref 'Black/Graphite Aluminum')
- 311552615 variant: None (ref 'Silver, curea gri')
- 308662180 model: 'Suunto RUN' (ref 'Run')
- 309285260 missed skip (bulk_lot)
- 303844965 missed skip (suspected_counterfeit)
- 311124248 missed skip (suspected_counterfeit)
- 310445019 missed skip (suspected_counterfeit)
- 310078444 missed skip (mismatched_photos)

## sonnet-high

- 288635581 variant: 'Chronograph Green Dial' (ref 'Gold Green')
- 288635581 brand: 'BOSS' (ref 'Hugo Boss')
- 307821123 model: 'Aur 9K' (ref 'Mecanic')
- 307821123 movement: None (ref 'manual')
- 311663552 model: 'Date Quartz' (ref 'Date')
- 303881575 variant: 'Gold PVD' (ref None)
- 239700714 model: 'Sportivo' (ref 'Chronograph')
- 306743074 variant: 'Camuflaj' (ref 'Grid Shock Camo')
- 311666038 model: 'Antimagnetic' (ref 'Mecanic')
- 311666038 variant: None (ref 'Gold-Tone')
- 311658785 variant: None (ref 'Titanium')
- 311664733 model: 'Fit' (ref 'Smartwatch Round')
- 311664733 brand: 'VIWA' (ref 'Viwa Fit')
- 311647676 variant: None (ref 'Black')
- 311662793 variant: 'Black' (ref None)
- 311617667 variant: 'Navy' (ref None)
- 311666907 variant: 'Black/Graphite' (ref 'Black/Graphite Aluminum')
- 311552615 variant: None (ref 'Silver, curea gri')
- 311124248 missed skip (suspected_counterfeit)
- 310078444 missed skip (mismatched_photos)
- 298522676 variant: 'Yellow White Dial' (ref 'Yellow')
- 256849892 variant: 'Day Date Silver Dial' (ref 'Day Date')
- 309054954 variant: 'Professional Pre-Bond 200M' (ref 'Professional 200M Pre-Bond')
- 299436000 model: 'Classic Slim' (ref 'BN0281')
- 299436000 variant: 'White Dial, Mesh + Blue Strap' (ref None)
- 300995529 model: 'Cymaflex' (ref 'Autorotor')
- 300995529 variant: 'Autorotor' (ref "Cymaflex, anii '60")
- 311663147 variant: 'NSU Motorom Gold Chronograph' (ref 'Chronograph Gold')
- 283237013 skipped a good ad: null
- 302184639 model: 'Khaki Pioneer' (ref 'Khaki Aviation')
- 302184639 variant: None (ref 'Pioneer')

## sonnet-low

- 288635581 variant: 'Green Dial Gold Chronograph' (ref 'Gold Green')
- 288635581 brand: 'BOSS' (ref 'Hugo Boss')
- 295248289 variant: None (ref 'Big Date')
- 311663552 model: 'Sport' (ref 'Date')
- 311663552 variant: 'Black Dial' (ref None)
- 283501997 variant: 'Chronograph Flyback Black Dial' (ref 'Chronograph Flyback')
- 239700714 model: 'Sportivo' (ref 'Chronograph')
- 306743074 variant: 'Camuflaj Digital' (ref 'Grid Shock Camo')
- 311666038 model: 'Antimagnetic' (ref 'Mecanic')
- 311666038 variant: 'Gold Case' (ref 'Gold-Tone')
- 309038799 variant: 'Mystic Black' (ref None)
- 311658785 variant: None (ref 'Titanium')
- 311664733 model: 'Viwa Fit' (ref 'Smartwatch Round')
- 311664733 brand: 'Viwa' (ref 'Viwa Fit')
- 311664733 description gate: description_unedited
- 309364544 variant: 'Midnight Blue' (ref 'Midnight')
- 311552615 variant: None (ref 'Silver, curea gri')
- 308662180 model: 'Suunto Run' (ref 'Run')
- 300625444 missed skip (not_a_watch)
- 310553432 missed skip (bulk_lot)
- 311124248 missed skip (suspected_counterfeit)
- 310445019 missed skip (suspected_counterfeit)
- 310078444 missed skip (mismatched_photos)

## sonnet-medium

- 288635581 variant: 'Cronograf Verde Auriu' (ref 'Gold Green')
- 288635581 brand: 'BOSS' (ref 'Hugo Boss')
- 307821123 model: 'Aur 9K' (ref 'Mecanic')
- 307821123 movement: None (ref 'manual')
- 311663552 model: 'Quartz' (ref 'Date')
- 311663552 variant: 'Black Dial' (ref None)
- 303881575 variant: 'Auriu, cadran argintiu' (ref None)
- 283501997 variant: 'Chronograph Flyback Black Panda' (ref 'Chronograph Flyback')
- 239700714 model: 'Sportivo' (ref 'Chronograph')
- 239700714 variant: 'Black Dial' (ref None)
- 306743074 variant: 'Camuflaj' (ref 'Grid Shock Camo')
- 311666038 model: 'Antimagnetic' (ref 'Mecanic')
- 311666038 variant: 'Cadran deschis, carcasă aurie' (ref 'Gold-Tone')
- 309038799 variant: 'Mystic Black' (ref None)
- 311658785 variant: None (ref 'Titanium')
- 311664733 model: 'Fit' (ref 'Smartwatch Round')
- 311664733 brand: 'VIWA' (ref 'Viwa Fit')
- 311664733 description gate: description_unedited
- 309364544 description gate: description_meta
- 310127143 connectivity: None (ref 'no_gsm')
- 311662793 variant: 'Black' (ref None)
- 311617667 variant: 'Navy' (ref None)
- 311666907 variant: 'Black/Graphite' (ref 'Black/Graphite Aluminum')
- 311552615 variant: '41mm Silver' (ref 'Silver, curea gri')
- 308662180 model: 'Suunto Run' (ref 'Run')
- 300625444 missed skip (not_a_watch)
- 303844965 missed skip (suspected_counterfeit)
- 311124248 missed skip (suspected_counterfeit)
- 310078444 missed skip (mismatched_photos)
