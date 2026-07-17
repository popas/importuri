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
Racheta:8
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
```

Last updated: 2026-07-17. Added Luch (35).

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
