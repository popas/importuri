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
```

Last updated: 2026-07-30. Added `Timex`(49), `Seksy`(50), `Edox`(51), `Mido`(52). Added `Ralmor`(48). Added `Westbury`(47), `Tressa Lux`(46), `NET`(45). Added `Jovial`(44), `Gruppo Gamma`(43), `Junghans`(42), `Chaika`(41). Added `Slava`(39), `Fresard`(40) on 2026-07-24. Brand 8 renamed `Racheta` → `Raketa` (2026-07-22).

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
