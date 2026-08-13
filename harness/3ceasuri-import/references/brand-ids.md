# Brand ID Mapping for 3ceasuri.ro

Extracted from https://3ceasuri.ro/admin/watches/brand/ on 2026-05-31.
Regenerate when new brands are added.

```
Certina:28
Spinnaker:27
Atlantic:26
Orient:25
Cauny:24
Doxa:23
Seconda:22
Fossil:21
Maurice Lacroix:20
Bischoff:19
Longines:18
Hamilton:17
Zenith:16
Seiko:15
Tudor:14
Citizen:13
Tissot:12
Poljot:11
Cartier:10
Le Duc:9
Raketa:8
Omega:7
TITUS Geneve:6
Glashutte:5
Rotary:4
Rolex:3
Casio:2
Aerowatch:1
Dugena:29
Helfer Geneve:30
Eberhard & Co:31
Oris:33
Saint Honoré:34
Luch:35
Sandoz:36
Vostok:37
Slava:39
Fresard:40
Chaika:41
Junghans:42
Gruppo Gamma:43
Jovial:44
NET:45
Tressa Lux:46
Westbury:47
Ralmor:48
Timex:49
Seksy:50
Edox:51
Mido:52
Buchner & Bovalier:53
Fără marcă:54
Predom Metron:56
Apple:57
Garmin:58
Samsung:59
Christophe Duchamp:60
Breitling:61
Locman:62
Saturne:63
Angles:64
Jean Marcel:65
Tag Heuer:66
Amazfit:67
Xiaomi:68
Traser:69
U-Boat:70
Festina:71
Guess:72
Rado:73
Jaguar:74
Roberto Cavalli:75
Theorein:76
Skoda Motorsport:77
Michael Kors:78
Invicta:79
Girard-Perregaux:80
Audemars Piguet:81
Sector:82
Gevril:83
GANT:84
Militado:85
Hublot:86
Bulova:87
Amulcor:88
OnePlus:89
Huawei:90
Accurist:91
Hugo Boss:92
Police:93
Swatch:94
Super Speed V6:95
Corum:96
IWC:97
Sinn:98
Capuer:99
Vostok Europe:100
Philip Watch:101
Stuhrling Original:102
Adidas:103
Emporio Armani:104
Unique:105
Frederique Constant:106
Fortis:107
```

Last updated: 2026-08-13. Added `Fortis`(107, ad 307129988), `Frederique Constant`(106, ad 305702589), `Unique`(105, ad 307997777), `Emporio Armani`(104, ad 301201897), `Adidas`(103, ad 307998215), `Stuhrling Original`(102, ad 295098648), `Philip Watch`(101, ad 306587562), `Vostok Europe`(100, ad 291377529), `Capuer`(99, ad 308010140), `Sinn`(98, ad 302208145), `IWC`(97, ad 302933017), `Corum`(96, ad 299571378), `Super Speed V6`(95, ad 189855374), `Swatch`(94, ad 298142936), `Police`(93, ad 303485157), `Hugo Boss`(92, ad 299395469), `Accurist`(91, ad 303993731), `Huawei`(90, ad 305344167), `OnePlus`(89, ad 306786878), `Amulcor`(88, ad 305357778), `Bulova`(87, ad 273108277), `Hublot`(86, ad 307129191), `Militado`(85, ad 302695090), `GANT`(84, ad 247268734), `Gevril`(83, ad 274923668), `Sector`(82, ad 304369016), `Audemars Piguet`(81, ad 293791993), `Girard-Perregaux`(80, ad 288774671), `Invicta`(79, ad 304369204), `Michael Kors`(78, ad 307974009), `Skoda
Motorsport`(77, ad 299467472 — OLX's own dropdown picked Seiko because the
movement inside is a Seiko Epson VR42, but the dial/box both read "SKODA
Motorsport" with no Seiko branding anywhere on the item, so the importer used
the actual retail brand instead), `Theorein`(76, ad 249821518), `Roberto
Cavalli`(75, ad 307140522), `Jaguar`(74, ad 304154865), `Rado`(73, ad 283650344),
`Guess`(72, ad 305363118), `Festina`(71, ad 290156551), `U-Boat`(70, ad
279321699 — same brand-correction pattern, OLX said Breitling), `Traser`(69, ad
306813551), `Amazfit`(67, ad 298341794), `Xiaomi`(68, ad 303268328) — all
created by the OLX importers the same day.

2026-08-09: Added `Apple`(57) — the first brand created by the OLX
importer (`olx-import-smartwatch.py`, ad 307818256). Expect most smartwatch brands
(Huawei, Xiaomi, Fitbit) to arrive the same way — `Garmin`(58)
already did, on the same day: in the
smartwatch category a NEW_BRAND is the normal case, not the exception.

Earlier that day: Added `Predom Metron`(56), the Polish wall-clock maker, created
by the script itself now that the lookup works. Added `Fără marcă`(54) — the brand wall clocks and other
unsigned pieces get; never invent a maker for them. That slug-vs-name lookup bug is now
FIXED in `import-post.py`: it searches the changelist by *name* and reuses an existing
row instead of creating a second one (a stale `BRAND_IDS` had produced a duplicate
`Fără marcă` with slug `f-r-marc`, since deleted).
Earlier: 2026-08-08 added `Buchner & Bovalier`(53), which hit that bug and needed the
manual step.
Earlier: 2026-07-30 added `Timex`(49), `Seksy`(50), `Edox`(51), `Mido`(52). Added `Ralmor`(48). Added `Westbury`(47), `Tressa Lux`(46), `NET`(45). Added `Jovial`(44), `Gruppo Gamma`(43), `Junghans`(42), `Chaika`(41). Added `Slava`(39), `Fresard`(40) on 2026-07-24. Brand 8 renamed `Racheta` → `Raketa` (2026-07-22).

**Alias:** the harness's `window.BRAND_IDS` also keeps `"Racheta": 8` so a post using the
old Romanian spelling still resolves to brand 8. Without it the lookup misses, falls back to
Select2, and creates a duplicate brand (that is how the stray `Raketa`(38) appeared on
2026-07-20). Keep the alias when regenerating this mapping from the admin — it will not
appear in the extraction output.

## Extraction Script

Run on `/admin/watches/brand/` page:

```javascript
var rows = document.querySelectorAll('#result_list tbody tr');
var brands = [];
rows.forEach(function(r) {
  var link = r.querySelector('th a');
  var name = link ? link.textContent.trim() : '';
  var href = link ? link.href : '';
  var m = href.match(/\/brand\/(\d+)\//);
  var id = m ? m[1] : null;
  if (name && id) brands.push({id: id, name: name});
});
// Copy brands into the mapping above
```
