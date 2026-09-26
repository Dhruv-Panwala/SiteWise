const map = L.map('map', { zoomControl: false }).setView([51.5074, -0.1278], 11);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);

// The grid changes map width at responsive breakpoints and browser zoom levels.
// Re-measure the container so Leaflet positions and loads the correct tiles.
const mapResizeObserver = new ResizeObserver(() => {
  map.invalidateSize({ pan: false, debounceMoveend: true });
});
mapResizeObserver.observe(document.getElementById('map'));

let marker = null;
let selected = null;
let screenVersion = 0;
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char]));

function toast(message) { const el = $('toast'); el.textContent = message; el.hidden = false; clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => { el.hidden = true; }, 5000); }
function setSelected(lat, lon, label = 'Map location') { selected = { latitude: Number(lat), longitude: Number(lon), label }; $('coordinates').textContent = `${selected.latitude.toFixed(5)}, ${selected.longitude.toFixed(5)}`; if (marker) marker.remove(); marker = L.marker([selected.latitude, selected.longitude]).addTo(map).bindPopup(escapeHtml(label)); marker.openPopup(); map.setView([selected.latitude, selected.longitude], Math.max(map.getZoom(), 15)); $('map-hint').hidden = true; }
map.on('click', (event) => setSelected(event.latlng.lat, event.latlng.lng));

function showResults(locations) { const root = $('search-results'); root.innerHTML = ''; if (!locations.length) { root.innerHTML = '<p class="field-help">No UK location found. Try a full postcode or click the map.</p>'; return; } locations.forEach((location) => { const button = document.createElement('button'); button.className = 'search-result'; button.type = 'button'; button.textContent = location.label; button.addEventListener('click', () => { setSelected(location.latitude, location.longitude, location.label); root.innerHTML = ''; $('search-input').value = location.label; }); root.appendChild(button); }); }
async function search() { const q = $('search-input').value.trim(); if (!q) return; $('search-button').disabled = true; try { const response = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`); const data = await response.json(); if (!response.ok) throw new Error(data.error); showResults(data.results || []); } catch (error) { toast(error.message || 'Search failed. Click the map to choose a site.'); } finally { $('search-button').disabled = false; } }
$('search-button').addEventListener('click', search); $('search-input').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); search(); } });

function cardEmpty(message) { return `<p class="empty-copy">${escapeHtml(message)}</p>`; }
function renderCases(items, type) { if (!items?.length) return cardEmpty(type === 'permission' ? 'No sufficiently comparable permitted residential case was retrieved.' : 'No comparable refused residential case was retrieved.'); return items.map((item) => { const refused = item.decision_category === 'permission_refused'; return `<div class="case"><div class="case-top"><div><h4>${escapeHtml(item.address_text || item.application_id)}</h4><small>${escapeHtml(item.authority || 'Authority not recorded')} · ${escapeHtml(item.application_id || '')}</small></div><span class="decision ${refused ? 'refused' : ''}">${escapeHtml(item.decision || 'Decision recorded')}</span></div><p>${escapeHtml(item.description || 'No description recorded')}</p>${item.source_url ? `<a class="source-link" href="${escapeHtml(safeUrl(item.source_url))}" target="_blank" rel="noreferrer">Open application ↗</a>` : ''}</div>`; }).join(''); }
function renderStack(items, fallback, formatter) { if (!items?.length) return cardEmpty(fallback); return items.map(formatter).join(''); }
function metric(value, label) { return `<div class="metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span></div>`; }

function renderDashboard(data, siteLabel) {
  renderCouncil(data);
  const advice = data.planning_advice || {}; const constraints = (data.planning_constraints || []).filter((item) => item.status === 'confirmed' || item.status === 'historical'); const localPlan = data.local_plan || {};
  $('empty-state').hidden = true; $('dashboard').hidden = false;
  $('result-title').textContent = siteLabel || data.property.authority || 'Selected site'; $('result-subtitle').textContent = `${data.property.latitude.toFixed(5)}, ${data.property.longitude.toFixed(5)} · ${data.property.proposed_description || 'Proposal not described'}`;
  $('source-status').textContent = localPlan.status ? `GLA ${localPlan.status}` : 'Planning evidence';
  $('metrics').innerHTML = [metric((advice.comparable_permissions || []).length, 'comparable permissions'), metric((advice.comparable_refusals || []).length, 'comparable refusals'), metric(constraints.length, 'spatial matches (check currency)'), metric((data.nearby_applications || []).length, 'nearby applications')].join('');
  $('suggestions').innerHTML = renderStack((advice.suggestions || []).filter(item => item.basis !== 'retrieved_policy_text'), 'No deterministic suggestions were generated.', (item) => `<div class="suggestion ${item.priority === 'high' ? 'high' : ''}"><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.action)}</p></div>`);
  $('constraint-count').textContent = `${constraints.length} found`; $('constraints').innerHTML = renderStack(constraints, 'No confirmed point-intersection constraint was retrieved. This is not site clearance.', (item) => `<div class="stack-item"><b>${escapeHtml(item.name || item.dataset)}</b><p>${escapeHtml(item.designation || item.coverage_warning || 'Published planning layer')}</p>${item.source_url ? `<a class="source-link" href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">View source ↗</a>` : ''}</div>`);
  $('permission-count').textContent = `${(advice.comparable_permissions || []).length} cases`; $('permissions').innerHTML = renderCases(advice.comparable_permissions, 'permission');
  $('refusal-count').textContent = `${(advice.comparable_refusals || []).length} cases`; $('refusals').innerHTML = renderCases(advice.comparable_refusals, 'refusal');
  $('policy-count').textContent = `${(advice.borough_policy_evidence || []).length} items`; $('policy-evidence').innerHTML = renderStack(advice.borough_policy_evidence, 'No borough policy layer evidence was retrieved.', (item) => `<div class="stack-item"><b>${escapeHtml(item.designation)}</b><p>${escapeHtml(item.message)}</p>${(item.source_urls || [])[0] ? `<a class="source-link" href="${escapeHtml(safeUrl(item.source_urls[0]))}" target="_blank" rel="noreferrer">View layer/source ↗</a>` : ''}</div>`);
  $('gap-count').textContent = `${(advice.data_gaps || []).length} checks`; $('data-gaps').innerHTML = renderStack(advice.data_gaps, 'No data gaps were reported.', (item) => `<div class="stack-item"><b>${escapeHtml(item.name || item.dataset)}</b><p>${escapeHtml(item.message)}</p></div>`);
  window.setTimeout(() => $('dashboard').scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
}


function safeUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : '#'; }
  catch { return '#'; }
}
function sourceLink(url, label) {
  return url ? '<a class="source-link" href="' + escapeHtml(safeUrl(url)) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(label) + '</a>' : '';
}
function renderCouncil(data) {
  const policy = data.council_policy || {};
  const authority = policy.authority || {};
  const items = policy.items || [];
  $('council-status').textContent = authority.name || 'Council unverified';
  $('council-summary').textContent = authority.status === 'boundary_verified'
    ? authority.name + ' administrative boundary verified. ' + items.length + ' relevant guidance passages retrieved. Design options below are not confirmation that the scheme complies.'
    : authority.message || 'Council-policy retrieval is unavailable. No local rules have been assumed.';
  $('council-rules').innerHTML = renderStack(items, 'No relevant policy text was retrieved for this location and proposal. Coverage is limited; consult the council before relying on this screen.', item =>
    '<div class="policy-rule"><span class="policy-label">' + escapeHtml(item.id + ' · ' + item.authority) +
    '</span><h4>' + escapeHtml(item.title) + '</h4><p>' + escapeHtml(item.suggested_action) +
    '</p><details><summary>Read the council evidence</summary><blockquote>' + escapeHtml(item.excerpt) +
    '</blockquote><p class="field-help">' + escapeHtml(item.document_status) + '</p><p class="field-help">Retrieved ' +
    escapeHtml(item.retrieved_at?.slice(0,10)) + ' · ' + escapeHtml(item.source_status) + '</p>' +
    sourceLink(item.source_url, 'Open official source' + (item.page ? ' · PDF page ' + item.page : '')) + '</details></div>');
  $('policy-limitations').innerHTML = [...(policy.limitations || []), ...(policy.errors || []).map(x => x.message)]
    .map(message => '<p class="empty-copy">' + escapeHtml(message) + '</p>').join('');
}
async function explainScreen(evidenceId, version) {
  $('ai-status').textContent = 'Generating';
  $('ai-report').textContent = 'Explaining the retrieved policies and site evidence… You can read the guidance while this runs.';
  try {
    const response = await fetch('/api/explain', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({evidence_id:evidenceId})});
    const report = await response.json();
    if (version !== screenVersion) return;
    if (!response.ok) throw new Error(report.error || 'Explanation request failed');
    const labels = {generated:'AI explanation', partial:'Incomplete AI answer', not_configured:'Token not configured', unavailable:'Provider unavailable', unverified:'Citation check failed', disabled:'AI disabled'};
    $('ai-status').textContent = labels[report.status] || 'Not available';
    // Render provider output as text, never unsanitised HTML/Markdown.
    $('ai-report').textContent = [report.text, report.message].filter(Boolean).join('\n\n');
    $('ai-sources').innerHTML = (report.citations || []).map(c => sourceLink(c.source_url, '[' + c.id + '] ' + c.title)).join(' ');
  } catch (error) {
    if (version !== screenVersion) return;
    $('ai-status').textContent = 'Unavailable';
    $('ai-report').textContent = (error.message || 'AI explanation failed.') + ' The council guidance above remains available.';
  }
}
$('site-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!selected) { toast('Search for a location or click the map first.'); return; }
  const version = ++screenVersion;
  const site = {...selected};
  $('dashboard').hidden = true;
  const button = $('analyse-button');
  button.disabled = true;
  button.querySelector('span').textContent = 'Reading council and site evidence…';
  $('ai-sources').innerHTML = '';
  $('ai-status').textContent = 'Waiting for evidence';
  $('ai-report').textContent = 'Retrieving the new site screen.';
  try {
    const response = await fetch('/api/analyze', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...site, description:$('description').value, include_gla:$('include-gla').checked})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Analysis failed');
    renderDashboard(data, site.label);
    if ($('include-llm').checked && data.evidence_id) {
      void explainScreen(data.evidence_id, version);
    } else if ($('include-llm').checked) {
      $('ai-status').textContent = 'Summary unavailable';
      $('ai-report').textContent = 'The AI summary is temporarily unavailable. You can still review the council guidance and planning evidence above.';
    } else {
      $('ai-status').textContent = 'Not requested';
      $('ai-report').textContent = 'The recommendations above are source-based, not AI generated. Enable the AI option and screen again for an explanation.';
    }
  } catch (error) { toast(error.message || 'Analysis could not be completed.'); }
  finally { button.disabled = false; button.querySelector('span').textContent = 'Screen this site'; }
});
$('sample-button').addEventListener('click', () => { setSelected(51.5074, -0.1278, 'Central London example'); $('description').value = 'Redevelopment of an existing house with a rear extension and two new homes'; });
