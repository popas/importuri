// === BRAND ID MAPPING ===
// Extract from https://3ceasuri.ro/admin/watches/brand/
// Regenerate if new brands are added.
window.BRAND_IDS = {"Certina":28,"Spinnaker":27,"Atlantic":26,"Orient":25,"Cauny":24,"Doxa":23,"Seconda":22,"Fossil":21,"Maurice Lacroix":20,"Bischoff":19,"Longines":18,"Hamilton":17,"Zenith":16,"Seiko":15,"Tudor":14,"Citizen":13,"Tissot":12,"Poljot":11,"Cartier":10,"Le Duc":9,"Racheta":8,"Omega":7,"TITUS Geneve":6,"Glashutte":5,"Rotary":4,"Rolex":3,"Casio":2,"Aerowatch":1,"Dugena":29,"Helfer Geneve":30,"Eberhard & Co":31,"Oris":33,"Saint Honoré":34};

// === DESCRIPTION FORMATTER ===
// Rewrites raw FB post text into a professional, structured description.
function formatDescription(raw) {
  if (!raw) return '';
  let text = raw;
  // Decode Unicode escapes
  text = text.replace(/\\u([\dA-F]{4})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
  // Normalize whitespace
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  text = text.replace(/[ \t]+/g, ' ');
  text = text.replace(/\n{3,}/g, '\n\n');
  text = text.split('\n').map(l => l.trim()).join('\n').trim();
  // Remove FB noise
  text = text.replace(/See translation$/gim, '');
  text = text.replace(/See more$/gim, '');
  text = text.replace(/\.\.\.$/, '');
  text = text.replace(/https?:\/\/www\.vinted\.ro\/\S+/g, '');
  // De-duplicate sentences
  const sentences = text.split(/(?<=[.!?])\s+/);
  const seen = new Set();
  const deduped = sentences.filter(s => {
    const key = s.toLowerCase().trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  text = deduped.join(' ').trim();
  text = text.replace(/\s{2,}/g, ' ').trim();
  return text;
}

// === PROFESSIONAL DESCRIPTION BUILDER ===
// Builds a structured, professional description from extracted watch data.
function buildProfessionalDescription(data) {
  const lines = [];
  
  // Title line: Brand + Model
  if (data.brand && data.model) {
    lines.push(`${data.brand} ${data.model}`);
    lines.push('');
  }
  
  // Key specs section
  const specs = [];
  if (data.movement) specs.push(`Mecanism: ${data.movement}`);
  if (data.diameter) specs.push(`Diametru: ${data.diameter} mm`);
  if (data.caseMat) specs.push(`Carcasa: ${data.caseMat}`);
  if (data.braceletMat) specs.push(`Brățară: ${data.braceletMat}`);
  if (data.year) specs.push(`An: ${data.year}`);
  if (data.waterRes && data.waterRes !== 'water_resistant_no') specs.push('Rezistentă la apă: Da');
  if (data.displayMat) specs.push(`Geam: ${data.displayMat}`);
  
  if (specs.length > 0) {
    lines.push('Specificații:');
    specs.forEach(s => lines.push(`- ${s}`));
    lines.push('');
  }
  
  // Condition
  if (data.condition) {
    const condMap = {new: 'Nou', excellent: 'Excelent', good: 'Bun', fair: 'Acceptabil', broken: 'Defect'};
    lines.push(`Stare: ${condMap[data.condition] || data.condition}`);
    lines.push('');
  }
  
  // Price
  if (data.price) {
    const currency = data.currency || 'RON';
    lines.push(`Preț: ${data.price} ${currency}${data.priceNote ? ' (' + data.priceNote + ')' : ''}`);
  }
  
  // Location
  if (data.location) {
    lines.push(`Locație: ${data.location}`);
  }
  
  // Seller
  if (data.seller) {
    lines.push(`Vânzător: ${data.seller}`);
  }
  
  // Original description (cleaned) as additional details
  if (data.rawDescription) {
    const cleaned = formatDescription(data.rawDescription);
    if (cleaned && cleaned.length > 10) {
      lines.push('');
      lines.push('Detalii suplimentare:');
      lines.push(cleaned);
    }
  }
  
  return lines.join('\n');
}

// === PHONE EXTRACTOR ===
function extractPhone(text) {
  if (!text) return '';
  const m = text.match(/(?:\+?40[\s.]?|0)7\d{2}[\s.]?[\s.]?\d{3}[\s.]?\d{3}/);
  return m ? m[0].replace(/[\s.]/g, '') : '';
}

// === LOCATION EXTRACTOR ===
function extractLocation(text) {
  if (!text) return '';
  // Match "în [City], [County]" or "in [City], [County]" or "Listed in [City]"
  const m = text.match(/(?:în|in|Listed in)\s+([A-ZÀ-Ž][^\n,]{2,30})(?:,\s*([A-ZÀ-Ž][^\n,]{2,30}))?/i);
  if (m) return m[2] ? `${m[1].trim()}, ${m[2].trim()}` : m[1].trim();
  return '';
}

// === SELLER EXTRACTOR ===
function extractSeller(text) {
  if (!text) return '';
  // Match "Seller details\n[Name]" pattern from commerce listings
  const m = text.match(/Seller details\s*\n([^\n]+)/i);
  return m ? m[1].trim() : '';
}

// === YEAR EXTRACTOR ===
function extractYear(text) {
  if (!text) return '';
  // Match year ranges like "1960-1970" or single years like "1965"
  const m = text.match(/\b((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?\b/);
  if (m) return m[2] ? `${m[1]}-${m[2]}` : m[1];
  return '';
}

// === REFERENCE NUMBER EXTRACTOR ===
function extractReference(text) {
  if (!text) return '';
  const m = text.match(/(?:ref\.?|reference|număr)\s*[:\-]?\s*([A-Z0-9\-\/]+)/i);
  return m ? m[1].trim() : '';
}

// === SLUG GENERATOR ===
function generateSlug(brand, model) {
  const slugify = s => s.toLowerCase()
    .replace(/[àáâãäă]/g, 'a').replace(/[èéêë]/g, 'e')
    .replace(/[ìíîï]/g, 'i').replace(/[òóôõö]/g, 'o')
    .replace(/[ùúûü]/g, 'u').replace(/[ș]/g, 's').replace(/[ț]/g, 't')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  return `-${slugify(brand)}-${slugify(model)}`;
}

// === CURRENCY DETECTOR ===
function detectCurrency(text) {
  if (!text) return 'RON';
  if (/\$/.test(text) || /\bUSD\b/i.test(text)) return 'USD';
  if (/€/.test(text) || /\bEUR\b/i.test(text)) return 'EUR';
  if (/lei/i.test(text) || /\bRON\b/i.test(text)) return 'RON';
  return 'RON';
}

// === WATCH IMPORT HARNESS v5 ===
// Uses brand ID mapping, auto-formats descriptions, extracts phone/location/seller/year/ref.
async function importWatch(data) {
  const log = [];
  function L(msg) { log.push(msg); console.log('[HARNESS]', msg); }

  // === 1. SELECT BRAND ===
  const brandId = window.BRAND_IDS[data.brand];
  
  if (brandId) {
    const select = document.getElementById('id_brand');
    let option = Array.from(select.options).find(o => o.value == brandId);
    if (!option) {
      option = document.createElement('option');
      option.value = brandId;
      option.textContent = data.brand;
      option.selected = true;
      select.appendChild(option);
    }
    select.value = brandId;
    select.dispatchEvent(new Event('change', {bubbles: true}));
    const container = document.querySelector('#select2-id_brand-container');
    if (container) { container.textContent = data.brand; container.title = data.brand; }
    await new Promise(r => setTimeout(r, 500));
    if (document.getElementById('id_brand').value == brandId) {
      L('BRAND OK (direct): ' + data.brand + ' (ID=' + brandId + ')');
    } else {
      L('DIRECT FAILED, falling back to Select2');
      return await selectBrandSelect2(data, log);
    }
  } else {
    L('BRAND NOT IN MAPPING: ' + data.brand + ' — using Select2');
    const result = await selectBrandSelect2(data, log);
    if (!result) return {success: false, error: 'BRAND_FAILED', log};
  }

  // === 2. BUILD PROFESSIONAL DESCRIPTION ===
  const professionalDesc = buildProfessionalDescription(data);
  
  // === 3. GENERATE SLUG ===
  const slug = data.modelSlug || generateSlug(data.brand, data.model);

  // === 4. FILL FIELDS ===
  const set = (id, val) => {
    if (!val && val !== 0) return;
    const el = document.getElementById(id);
    if (!el) return;
    el.value = String(val);
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };

  set('id_model_name', data.model);
  set('id_model_slug', slug);
  set('id_reference_number', data.reference);
  set('id_price', data.price);
  set('id_condition', data.condition || 'good');
  set('id_movement', data.movement || 'quartz');
  set('id_case_diameter_mm', data.diameter);
  set('id_case_material', data.caseMat);
  set('id_bracelet_material', data.braceletMat);
  set('id_type', data.type);
  set('id_year', data.year);
  set('id_water_resistance', data.waterRes);
  set('id_display_material', data.displayMat);
  set('id_display_color', data.displayColor);
  set('id_display_type', data.displayType);
  set('id_display_size', data.displaySize);
  set('id_currency', data.currency);
  set('id_description', professionalDesc);
  set('id_source_url', data.sourceUrl);
  set('id_facebook_listing_id', data.fbListingId);
  set('id_phone', data.phone);
  
  const optionalFields = [
    data.diameter&&'diameter', data.caseMat&&'case', data.braceletMat&&'bracelet',
    data.type&&'type', data.year&&'year', data.waterRes&&'WR', data.displayMat&&'glass',
    data.reference&&'ref', data.phone&&'phone', data.seller&&'seller', data.location&&'location'
  ].filter(Boolean);
  L('FIELDS: model,price,cond,movement' + (optionalFields.length ? ', ' + optionalFields.join(',') : ''));

  // === 5. FETCH + INJECT ALL IMAGES (with retry) ===
  if (!data.images || data.images.length === 0) {
    return {success: false, error: 'NO_IMAGES', log};
  }

  const images = [];
  for (const url of data.images) {
    let fetched = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          L('FETCH ' + resp.status + ' (attempt ' + (attempt+1) + '): ' + url.substring(0, 60));
          await new Promise(r => setTimeout(r, 1000));
          continue;
        }
        const blob = await resp.blob();
        const dataUrl = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = rej;
          r.readAsDataURL(blob);
        });
        if (dataUrl.startsWith('data:image/')) {
          images.push({data_url: dataUrl});
          fetched = true;
          break;
        }
      } catch(e) { L('FETCH FAIL (attempt ' + (attempt+1) + '): ' + e.message); }
    }
    if (!fetched) L('IMAGE FAILED AFTER 3 ATTEMPTS: ' + url.substring(0, 60));
  }
  L('IMAGES: ' + images.length + '/' + data.images.length);

  if (images.length === 0) {
    return {success: false, error: 'ALL IMAGES FAILED TO FETCH', log};
  }

  document.getElementById('images_payload').value = JSON.stringify(images);

  // === 6. VERIFY PAYLOAD ===
  const payloadLen = document.getElementById('images_payload').value.length;
  if (payloadLen < 500) {
    L('CRITICAL: payload only ' + payloadLen + ' chars');
    return {success: false, error: 'PAYLOAD_TOO_SMALL: ' + payloadLen, log};
  }
  L('PAYLOAD: ' + payloadLen + ' chars');

  // === 7. SUBMIT ===
  document.querySelector('input[name="_addanother"]').click();

  // === 8. VERIFY RESULT ===
  await new Promise(r => setTimeout(r, 5000));
  const txt = document.body.innerText;
  const ok = txt.includes('imagini salvate') && txt.includes('added successfully');
  
  return {success: ok, images: images.length, brandId: document.getElementById('id_brand').value, log};
}

// Fallback Select2 selection
async function selectBrandSelect2(data, log) {
  const L = (m) => { log.push(m); console.log('[S2]', m); };
  for (let attempt = 0; attempt < 5; attempt++) {
    if (attempt > 0) await new Promise(r => setTimeout(r, 1000));
    const container = document.querySelector('#select2-id_brand-container');
    if (!container) { L('NO SELECT2'); return false; }
    ['mousedown','mouseup','click','focus'].forEach(e =>
      container.dispatchEvent(new MouseEvent(e, {bubbles: true})));
    await new Promise(r => setTimeout(r, 2000));
    const search = document.querySelector('.select2-search__field');
    if (!search) { L('NO SEARCH a'+attempt); continue; }
    search.value = data.brand.substring(0, 4);
    search.dispatchEvent(new Event('input', {bubbles: true}));
    search.dispatchEvent(new Event('keyup', {bubbles: true}));
    await new Promise(r => setTimeout(r, 3000));
    const opts = document.querySelectorAll('.select2-results__option');
    for (const opt of opts) {
      if (opt.textContent.trim().toLowerCase().includes(data.brand.toLowerCase())) {
        ['mousedown','mouseup','click'].forEach(e =>
          opt.dispatchEvent(new MouseEvent(e, {bubbles: true})));
        await new Promise(r => setTimeout(r, 1000));
        if (document.getElementById('id_brand').value) {
          L('BRAND OK via S2: ' + data.brand);
          return true;
        }
      }
    }
    L('NOT FOUND a'+attempt);
  }
  return false;
}

window.importWatch = importWatch;
window.formatDescription = formatDescription;
window.buildProfessionalDescription = buildProfessionalDescription;
window.extractPhone = extractPhone;
window.extractLocation = extractLocation;
window.extractSeller = extractSeller;
window.extractYear = extractYear;
window.extractReference = extractReference;
window.generateSlug = generateSlug;
window.detectCurrency = detectCurrency;
'Harness v5 ready. Professional descriptions, phone/location/seller extraction, auto-slug, retry images.';
